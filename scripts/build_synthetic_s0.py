"""E4-A / E4-C1 — S0_STANDARD_SYNTHETIC: the official gridfm-datakit pf_small recipe on Sundon.

    uv run --env-file .env python scripts/build_synthetic_s0.py

For each pre-registered seed: `gridfm_datakit` generate (PF mode, official recipe from the
case14 dataset's args.log; configs/experiments/e4_zero_shot.yaml `s0_standard_synthetic`) on the
E1 Sundon case (LTDS planning peak). Seeds are merged into one graphkit dataset with consecutive
scenario ids; the SAME AC gates as every other family are applied and rejections reported.

Outputs
    data/interim/e4/datasets/S0_STANDARD_SYNTHETIC/sundon_33kv/raw/      (gitignored)
    reports/experiments/e4/families/S0_STANDARD_SYNTHETIC_gates.parquet  (per-scenario)
    reports/experiments/e4/families/S0_STANDARD_SYNTHETIC.json
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from cloud2grid.genco import runner
from cloud2grid.genco.opengridfm_export import GATES
from cloud2grid.licensing.registry import REPO_ROOT

CFG = yaml.safe_load((REPO_ROOT / "configs/experiments/e4_zero_shot.yaml").read_text())
S0 = CFG["s0_standard_synthetic"]
WORK = REPO_ROOT / "data/interim/e4"
FAM = "S0_STANDARD_SYNTHETIC"
NETWORK = "sundon_33kv"
OUT = REPO_ROOT / "reports/experiments/e4/families"
TABLES = ["bus_data", "branch_data", "gen_data", "y_bus_data", "runtime_data"]


def datakit_config(seed: int, out_dir: Path) -> dict:
    r = S0["recipe"]
    net_file = REPO_ROOT / S0["network_file"]
    return {
        "network": {"name": NETWORK, "source": "file", "network_dir": str(net_file.parent)},
        "load": {**r["load"], "scenarios": S0["load_scenarios_per_seed"]},
        "topology_perturbation": r["topology_perturbation"],
        "generation_perturbation": r["generation_perturbation"],
        "admittance_perturbation": r["admittance_perturbation"],
        "settings": {
            **r["settings"],
            "data_dir": str(out_dir),
            "seed": seed,
            "num_processes": 8,
            "large_chunk_size": 1000,
            "overwrite": True,
            "enable_solver_logs": False,
        },
    }


def generate(seed: int) -> Path:
    from gridfm_datakit.generate import generate_power_flow_data_distributed

    out = WORK / "s0_raw" / f"seed{seed}"
    conf = WORK / "configs" / f"s0_datakit_seed{seed}.yaml"
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text(yaml.safe_dump(datakit_config(seed, out), sort_keys=False))
    generate_power_flow_data_distributed(str(conf))
    return out / NETWORK / "raw"


def gates(bus: pd.DataFrame, ybus: pd.DataFrame, base_mva: float = 100.0) -> pd.DataFrame:
    """Same AC gates as opengridfm_export.export_stream, recomputed from the tables."""
    rows = []
    lo, hi = GATES["vm_sanity_pu"]
    for sc, b in bus.groupby("scenario"):
        b = b.sort_values("bus")
        n = len(b)
        y = np.zeros((n, n), dtype=complex)
        yb = ybus[ybus["scenario"] == sc]
        y[yb["index1"].astype(int), yb["index2"].astype(int)] = yb["G"] + 1j * yb["B"]
        v = b["Vm"].to_numpy() * np.exp(1j * np.deg2rad(b["Va"].to_numpy()))
        mis = v * np.conj(y @ v) * base_mva - (
            (b["Pg"] - b["Pd"]).to_numpy() + 1j * (b["Qg"] - b["Qd"]).to_numpy()
        )
        p, q = float(np.abs(mis.real).max()), float(np.abs(mis.imag).max())
        vmin, vmax = float(b["Vm"].min()), float(b["Vm"].max())
        rej = None
        if not np.isfinite(b["Vm"]).all():
            rej = "powermodels_not_converged"
        elif max(p, q) > GATES["max_power_mismatch_mva"]:
            rej = "power_balance"
        elif vmin < lo or vmax > hi:
            rej = "voltage_sanity"
        rows.append(
            {
                "scenario_in": int(sc),
                "max_p_mismatch_mw": p,
                "max_q_mismatch_mvar": q,
                "vm_min": vmin,
                "vm_max": vmax,
                "ac_converged": rej is None or rej != "powermodels_not_converged",
                "rejected": rej,
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    t0 = time.perf_counter()
    parts: dict[str, list[pd.DataFrame]] = {t: [] for t in TABLES}
    gate_rows, offset, requested = [], 0, 0
    for seed in S0["seeds"]:
        raw = generate(seed)
        tabs = {t: pd.read_parquet(raw / f"{t}.parquet") for t in TABLES}
        g = gates(tabs["bus_data"], tabs["y_bus_data"])
        g["seed"] = seed
        requested += (
            S0["load_scenarios_per_seed"]
            * S0["recipe"]["topology_perturbation"]["n_topology_variants"]
        )
        keep = g.loc[g["rejected"].isna(), "scenario_in"].tolist()
        remap = {old: offset + i for i, old in enumerate(sorted(keep))}
        g["scenario"] = g["scenario_in"].map(remap)
        # topology intact = every branch in service (datakit N-1 variants switch one element off)
        br = tabs["branch_data"].groupby("scenario")["br_status"].min()
        gen = tabs["gen_data"].groupby("scenario")["in_service"].min()
        g["topology_intact"] = g["scenario_in"].map(
            (br > 0) & gen.reindex(br.index).fillna(1).gt(0)
        )
        ls = tabs["bus_data"].groupby("scenario")["load_scenario_idx"].first()
        g["load_block"] = [f"s{seed}_l{int(x)}" for x in g["scenario_in"].map(ls)]
        gate_rows.append(g)
        for t in TABLES:
            df = tabs[t][tabs[t]["scenario"].isin(keep)].copy()
            df["scenario"] = df["scenario"].map(remap)
            parts[t].append(df.drop(columns=["scenario_partition"], errors="ignore"))
        offset += len(keep)
    dest = WORK / "datasets" / FAM / NETWORK / "raw"
    if dest.parent.exists():
        shutil.rmtree(dest.parent)
    dest.mkdir(parents=True)
    for t in TABLES:
        df = pd.concat(parts[t], ignore_index=True).sort_values("scenario")
        df["scenario_partition"] = df["scenario"] // 1000
        pq.write_to_dataset(
            pa.Table.from_pandas(df, preserve_index=False),
            str(dest / f"{t}.parquet"),
            partition_cols=["scenario_partition"],
        )
    shutil.copy(REPO_ROOT / S0["network_file"], dest.parent / f"{NETWORK}.m")
    G = pd.concat(gate_rows, ignore_index=True)
    OUT.mkdir(parents=True, exist_ok=True)
    G.to_parquet(OUT / f"{FAM}_gates.parquet", index=False)
    summary = {
        "family": FAM,
        "seeds": S0["seeds"],
        "requested_max": requested,
        "generated_by_datakit": int(len(G)),
        "not_returned_by_datakit": int(requested - len(G)),
        "accepted": int(G["rejected"].isna().sum()),
        "rejected": G["rejected"].value_counts().to_dict(),
        "topology_intact_accepted": int(G.loc[G["rejected"].isna(), "topology_intact"].sum()),
        "wall_s": time.perf_counter() - t0,
        **runner.git_commit(),
    }
    (OUT / f"{FAM}.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

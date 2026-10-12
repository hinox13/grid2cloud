"""E5b — synthetic Sundon pools on the BROAD physics-informed operating envelope (static metadata).

    uv run python scripts/build_e5b_training_data.py envelope           # bounds table, source check
    uv run --env-file .env python scripts/build_e5b_training_data.py generate-all [--jobs 7]
    uv run --env-file .env python scripts/build_e5b_training_data.py merge

Identical to E5 (scripts/build_e5_training_data.py) except the datakit LOAD-SCENARIO GENERATOR:
gridfm-datakit's own pipeline runs unchanged (E1 network file + A1 slack limits, random N-1 × 22,
admittance σ 0.2, OPF/PF, DC baseline, E4 AC gates), but its load scenarios come from
cloud2grid.scenarios.envelope.EnvelopeLoadGenerator
(configs/experiments/e5b_operating_envelope.yaml).
No real operating value, S1/S2 state, satellite PV or weather enters any pool.

Outputs
    data/interim/e5b/synthetic/sundon_33kv/raw/ + manifest.parquet           (gitignored)
    reports/tables/e5b_operating_envelope.csv
    reports/experiments/e5b/synthetic_gates.parquet, synthetic.json, envelope_sources.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from cloud2grid.genco import adaptation_e5b as ad
from cloud2grid.genco import runner
from cloud2grid.licensing.registry import REPO_ROOT
from cloud2grid.scenarios import envelope as ev

ENV = yaml.safe_load((REPO_ROOT / "configs/experiments/e5b_operating_envelope.yaml").read_text())
HELD = ENV["held_constant_from_e5"]
NETWORK = ad.NETWORK
TABLES = ["bus_data", "branch_data", "gen_data", "y_bus_data", "runtime_data"]
OUT = REPO_ROOT / "reports/experiments/e5b"
RAW_ROOT = ad.WORK / "synthetic_raw"
SOURCE_TAG = "gridfm-datakit+e5b-envelope"


def cmd_envelope() -> dict:
    e = ev.build_envelope()
    exp = ENV["hv_generation"]["expected"]
    if {k: round(v, 3) for k, v in e["hv_capacity_mw"].items()} != exp:
        raise SystemExit(f"HV generation {e['hv_capacity_mw']} != pre-registered {exp}")
    if e["storage"]["registered_capacity_mw"] != ENV["storage"]["bound_mw"]:
        raise SystemExit("storage bound differs from the pre-registered value")
    if not ev.SOURCES_READ <= ev.ALLOWED_SOURCES:
        raise SystemExit(f"envelope read non-static sources {ev.SOURCES_READ - ev.ALLOWED_SOURCES}")
    t = e["elements"]
    (REPO_ROOT / "reports/tables").mkdir(exist_ok=True)
    t.to_csv(REPO_ROOT / "reports/tables/e5b_operating_envelope.csv", index=False)
    OUT.mkdir(parents=True, exist_ok=True)
    rec = {
        "sources_read": sorted(ev.SOURCES_READ),
        "allowed_sources": sorted(ev.ALLOWED_SOURCES),
        "sites": e["sites"].reset_index().to_dict(orient="records"),
        "hv_generation": e["hv_generation"].to_dict(orient="records"),
        "storage": e["storage"],
    }
    (OUT / "envelope_sources.json").write_text(json.dumps(rec, indent=2, default=str))
    print(t[["element", "min_mw", "max_mw"]].to_string(index=False))
    return rec


def datakit_config(seed: int, out_dir: Path) -> dict:
    net_file = REPO_ROOT / HELD["network_file"]
    return {
        "network": {"name": NETWORK, "source": "file", "network_dir": str(net_file.parent)},
        "load": {"generator": "e5b_envelope", "scenarios": HELD["load_scenarios_per_seed"]},
        "topology_perturbation": HELD["topology_perturbation"],
        "generation_perturbation": HELD["generation_perturbation"],
        "admittance_perturbation": HELD["admittance_perturbation"],
        "settings": {
            **HELD["settings"],
            "data_dir": str(out_dir),
            "seed": seed,
            "num_processes": 8,
            "large_chunk_size": 1000,
            "overwrite": True,
            "enable_solver_logs": False,
        },
    }


def cmd_generate(pool: str, seed: int) -> None:
    import gridfm_datakit.generate as dkg

    dkg.get_load_scenario_generator = lambda _args: ev.EnvelopeLoadGenerator()
    out = RAW_ROOT / pool / f"seed{seed}"
    conf = ad.WORK / "configs" / f"datakit_{pool}_seed{seed}.yaml"
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text(yaml.safe_dump(datakit_config(seed, out), sort_keys=False))
    dkg.generate_power_flow_data_distributed(str(conf))
    (out / "DONE").write_text("ok")


def cmd_generate_all(jobs: int, pools: list[str], extra: int = 0) -> None:
    todo = [
        (p, s)
        for p in pools
        for s in ad.pool_seeds(p, extra if p == "train" else 0)
        if not (RAW_ROOT / p / f"seed{s}" / "DONE").exists()
    ]
    log_dir = ad.WORK / "logs" / "datakit"
    log_dir.mkdir(parents=True, exist_ok=True)

    def one(job: tuple[str, int]) -> tuple[str, int, int]:
        pool, s = job
        with open(log_dir / f"{pool}_{s}.log", "w") as log:
            rc = subprocess.run(
                [sys.executable, __file__, "generate", "--pool", pool, "--seed", str(s)],
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=REPO_ROOT,
            ).returncode
        print(f"{pool} seed {s}: rc={rc}", flush=True)
        return pool, s, rc

    t0 = time.perf_counter()
    with ThreadPoolExecutor(jobs) as ex:
        res = list(ex.map(one, todo))
    bad = [r for r in res if r[2] != 0]
    print(f"{len(todo)} seeds in {time.perf_counter() - t0:.0f} s; failed: {bad}")
    if bad:
        raise SystemExit(1)


def cmd_merge(extra: int = 0) -> None:
    from build_synthetic_s0 import gates  # E4's gate recomputation, unchanged

    parts: dict[str, list[pd.DataFrame]] = {t: [] for t in TABLES}
    gate_rows, manifest, offset, requested = [], [], 0, {}
    per_seed = (
        HELD["load_scenarios_per_seed"] * HELD["topology_perturbation"]["n_topology_variants"]
    )
    for pool in ad.POOLS:
        requested[pool] = 0
        for seed in ad.pool_seeds(pool, extra if pool == "train" else 0):
            raw = RAW_ROOT / pool / f"seed{seed}" / NETWORK / "raw"
            if not raw.exists():
                continue
            requested[pool] += per_seed
            tabs = {t: pd.read_parquet(raw / f"{t}.parquet") for t in TABLES}
            g = gates(tabs["bus_data"], tabs["y_bus_data"])
            g["pool"], g["datakit_seed"] = pool, seed
            keep = g.loc[g["rejected"].isna(), "scenario_in"].tolist()
            remap = {old: offset + i for i, old in enumerate(sorted(keep))}
            g["scenario"] = g["scenario_in"].map(remap)
            ls = tabs["bus_data"].groupby("scenario")["load_scenario_idx"].first()
            g["load_block"] = [f"{pool}_s{seed}_l{int(x)}" for x in g["scenario_in"].map(ls)]
            gate_rows.append(g)
            manifest.append(
                g.loc[
                    g["rejected"].isna(),
                    ["scenario", "pool", "datakit_seed", "scenario_in", "load_block"],
                ]
            )
            for t in TABLES:
                df = tabs[t][tabs[t]["scenario"].isin(keep)].copy()
                df["scenario"] = df["scenario"].map(remap)
                parts[t].append(df.drop(columns=["scenario_partition"], errors="ignore"))
            offset += len(keep)
    dest = ad.ALLOWED_ROOT / NETWORK / "raw"
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
        del df
    shutil.copy(REPO_ROOT / HELD["network_file"], dest.parent / f"{NETWORK}.m")
    M = pd.concat(manifest, ignore_index=True).astype({"scenario": int})
    M["source"] = SOURCE_TAG
    M.to_parquet(ad.ALLOWED_ROOT / "manifest.parquet", index=False)
    G = pd.concat(gate_rows, ignore_index=True)
    OUT.mkdir(parents=True, exist_ok=True)
    G.to_parquet(OUT / "synthetic_gates.parquet", index=False)
    summary = {"pools": {}, "total_accepted": int(offset), **runner.git_commit()}
    for pool in ad.POOLS:
        if not (G.pool == pool).any():
            continue
        summary["pools"][pool] = {
            "datakit_seeds": [
                int(s) for s in sorted(G.loc[G.pool == pool, "datakit_seed"].unique())
            ],
            "requested_max": requested[pool],
            "generated_by_datakit": int((G.pool == pool).sum()),
            "accepted": int(((G.pool == pool) & G.rejected.isna()).sum()),
            "rejected": G.loc[G.pool == pool, "rejected"].value_counts().to_dict(),
            "load_blocks": int(M.loc[M.pool == pool, "load_block"].nunique()),
            "scenario_id_range": [
                int(M.loc[M.pool == pool, "scenario"].min()),
                int(M.loc[M.pool == pool, "scenario"].max()),
            ],
        }
    (OUT / "synthetic.json").write_text(json.dumps(summary, indent=2, default=str))
    print(
        json.dumps(
            {
                p: {k: v for k, v in d.items() if k != "datakit_seeds"}
                for p, d in summary["pools"].items()
            },
            indent=1,
            default=str,
        )
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["envelope", "generate", "generate-all", "merge"])
    ap.add_argument("--pool", choices=ad.POOLS)
    ap.add_argument("--pools", nargs="*", default=list(ad.POOLS))
    ap.add_argument("--seed", type=int)
    ap.add_argument("--jobs", type=int, default=7)
    ap.add_argument("--extra-train-seeds", type=int, default=0)
    a = ap.parse_args()
    if a.command == "envelope":
        cmd_envelope()
    elif a.command == "generate":
        cmd_generate(a.pool, a.seed)
    elif a.command == "generate-all":
        cmd_generate_all(a.jobs, a.pools, a.extra_train_seeds)
    else:
        cmd_merge(a.extra_train_seeds)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    sys.exit(main())

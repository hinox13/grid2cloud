"""E5 — synthetic Sundon adaptation pools (train / val / held-out test) with gridfm-datakit.

    uv run --env-file .env python scripts/build_e5_training_data.py generate-all [--jobs 6]
    uv run --env-file .env python scripts/build_e5_training_data.py merge
    [--representation SUNDON_MERGED_NEAR_ZERO_Z]   (sensitivity network, same seeds)

Same methodology as E4 S0 (configs/experiments/e4_zero_shot.yaml `s0_standard_synthetic`): the
official pf_small recipe, unchanged, on the E1 Sundon case, 43 load scenarios × 22 N-1 variants
per datakit seed, the SAME AC gates. Pools are disjoint datakit seeds
(configs/experiments/e5_topology_adaptation.yaml `synthetic_data.pools`). No real timestamp, UKPN
reading, satellite value or E4 state enters any pool (isolation rule; tests/satellite/test_e5.py).

Outputs
    data/interim/e5/synthetic[_merged]/sundon_33kv/raw/   one graphkit dataset, all pools
    data/interim/e5/synthetic[_merged]/manifest.parquet    scenario → pool, datakit seed, load block
    reports/experiments/e5/synthetic[_merged]_gates.parquet  every generated state, incl. rejections
    reports/experiments/e5/synthetic[_merged].json            counts per pool
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

from cloud2grid.genco import adaptation as ad
from cloud2grid.genco import runner
from cloud2grid.licensing.registry import REPO_ROOT

E4 = yaml.safe_load((REPO_ROOT / "configs/experiments/e4_zero_shot.yaml").read_text())
S0 = E4["s0_standard_synthetic"]
NETWORK = ad.NETWORK
TABLES = ["bus_data", "branch_data", "gen_data", "y_bus_data", "runtime_data"]
OUT = REPO_ROOT / "reports/experiments/e5"


def paths(rep: str) -> dict[str, Path]:
    suffix = "" if rep == "SUNDON_ORIGINAL" else "_merged"
    return {
        "raw_root": ad.WORK / f"synthetic_raw{suffix}",
        "dataset": ad.WORK / f"synthetic{suffix}",
        "network_file": REPO_ROOT / S0["network_file"]
        if rep == "SUNDON_ORIGINAL"
        else ad.WORK / "network_merged" / f"{NETWORK}.m",
        "gates": OUT / f"synthetic{suffix}_gates.parquet",
        "summary": OUT / f"synthetic{suffix}.json",
    }


def datakit_config(seed: int, out_dir: Path, network_file: Path) -> dict:
    """E4 S0 datakit config (build_synthetic_s0.datakit_config), with this seed and network."""
    r = S0["recipe"]
    return {
        "network": {"name": NETWORK, "source": "file", "network_dir": str(network_file.parent)},
        "load": {**r["load"], "scenarios": ad.CFG["synthetic_data"]["load_scenarios_per_seed"]},
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


def cmd_generate(pool: str, seed: int, rep: str) -> None:
    from gridfm_datakit.generate import generate_power_flow_data_distributed

    p = paths(rep)
    out = p["raw_root"] / pool / f"seed{seed}"
    conf = ad.WORK / "configs" / f"datakit_{rep}_{pool}_seed{seed}.yaml"
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text(yaml.safe_dump(datakit_config(seed, out, p["network_file"]), sort_keys=False))
    generate_power_flow_data_distributed(str(conf))
    (out / "DONE").write_text("ok")


def cmd_generate_all(jobs: int, rep: str, pools: list[str]) -> None:
    p = paths(rep)
    todo = [
        (pool, s)
        for pool in pools
        for s in ad.pool_seeds(pool)
        if not (p["raw_root"] / pool / f"seed{s}" / "DONE").exists()
    ]
    log_dir = ad.WORK / "logs" / "datakit"
    log_dir.mkdir(parents=True, exist_ok=True)

    def one(job: tuple[str, int]) -> tuple[str, int, int]:
        pool, s = job
        with open(log_dir / f"{rep}_{pool}_{s}.log", "w") as log:
            rc = subprocess.run(
                [
                    sys.executable,
                    __file__,
                    "generate",
                    "--pool",
                    pool,
                    "--seed",
                    str(s),
                    "--representation",
                    rep,
                ],
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


def cmd_merge(rep: str) -> None:
    from build_synthetic_s0 import gates  # E4's gate recomputation, unchanged

    p = paths(rep)
    parts: dict[str, list[pd.DataFrame]] = {t: [] for t in TABLES}
    gate_rows, manifest, offset = [], [], 0
    per_seed_requested = (
        ad.CFG["synthetic_data"]["load_scenarios_per_seed"]
        * S0["recipe"]["topology_perturbation"]["n_topology_variants"]
    )
    requested: dict[str, int] = {}
    for pool in ad.POOLS:  # test, val, train → contiguous scenario-id ranges
        requested[pool] = 0
        for seed in ad.pool_seeds(pool):
            raw = p["raw_root"] / pool / f"seed{seed}" / NETWORK / "raw"
            if not raw.exists():
                continue
            requested[pool] += per_seed_requested
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
    dest = p["dataset"] / NETWORK / "raw"
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
    shutil.copy(p["network_file"], dest.parent / f"{NETWORK}.m")
    (dest.parent.parent / "n_scenarios.txt").write_text(str(offset))
    M = pd.concat(manifest, ignore_index=True).astype({"scenario": int})
    M["source"] = "gridfm-datakit"
    M["representation"] = rep
    M.to_parquet(p["dataset"] / "manifest.parquet", index=False)
    G = pd.concat(gate_rows, ignore_index=True)
    OUT.mkdir(parents=True, exist_ok=True)
    G.to_parquet(p["gates"], index=False)
    summary = {
        "representation": rep,
        "network_file": str(p["network_file"].relative_to(REPO_ROOT)),
        "pools": {
            pool: {
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
            for pool in ad.POOLS
            if (G.pool == pool).any()
        },
        "total_accepted": int(offset),
        **runner.git_commit(),
    }
    (p["summary"]).write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=1, default=str))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["generate", "generate-all", "merge"])
    ap.add_argument("--pool", choices=ad.POOLS)
    ap.add_argument("--pools", nargs="*", default=list(ad.POOLS))
    ap.add_argument("--seed", type=int)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument(
        "--representation",
        default="SUNDON_ORIGINAL",
        choices=["SUNDON_ORIGINAL", "SUNDON_MERGED_NEAR_ZERO_Z"],
    )
    a = ap.parse_args()
    if a.command == "generate":
        cmd_generate(a.pool, a.seed, a.representation)
    elif a.command == "generate-all":
        cmd_generate_all(a.jobs, a.representation, a.pools)
    else:
        cmd_merge(a.representation)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    sys.exit(main())

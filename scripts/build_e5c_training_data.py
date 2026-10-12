"""E5c — generator-aware synthetic pools, re-encoded retention sets and (after freeze) real S1.

    uv run --env-file .env python scripts/build_e5c_training_data.py generate-all [--jobs 7]
    uv run --env-file .env python scripts/build_e5c_training_data.py merge        # + re-encoding
    uv run python scripts/build_e5c_training_data.py retention                     # E5 / E5b tests
    uv run python scripts/build_e5c_training_data.py real              # ONLY after freeze

Pools: the E5b datakit pipeline (E1 case + A1, random N-1 × 22, admittance σ 0.2, OPF/PF, E4 AC
gates) with the E5c load-scenario generator (E5b envelope + zero-inflated LBUZ generation).
After the AC solve the tables are re-encoded so LBUZ31/32/33 generation is an explicit generator
node on a PQ bus (cloud2grid.genco.generator_aware). Static metadata only.

Outputs: data/interim/e5c/{synthetic,datasets}/ (gitignored); reports/experiments/e5c/
synthetic_gates.parquet, synthetic.json, retention.json, real_reencode.json
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

from cloud2grid.genco import adaptation as ad5
from cloud2grid.genco import adaptation_e5b as ad5b
from cloud2grid.genco import adaptation_e5c as ad
from cloud2grid.genco import runner
from cloud2grid.genco.generator_aware import reencode, reencode_dataset
from cloud2grid.licensing.registry import REPO_ROOT
from cloud2grid.scenarios import envelope_e5c as ev

ENVB = yaml.safe_load((REPO_ROOT / "configs/experiments/e5b_operating_envelope.yaml").read_text())
HELD = ENVB["held_constant_from_e5"]
NETWORK = ad.NETWORK
TABLES = ["bus_data", "branch_data", "gen_data", "y_bus_data", "runtime_data"]
OUT = REPO_ROOT / "reports/experiments/e5c"
RAW_ROOT = ad.WORK / "synthetic_raw"
REGISTRY = REPO_ROOT / "metadata/e5c_checkpoint_registry.yaml"


def datakit_config(seed: int, out_dir: Path) -> dict:
    net_file = REPO_ROOT / HELD["network_file"]
    return {
        "network": {"name": NETWORK, "source": "file", "network_dir": str(net_file.parent)},
        "load": {"generator": "e5c_generator_aware", "scenarios": HELD["load_scenarios_per_seed"]},
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

    dkg.get_load_scenario_generator = lambda _args: ev.E5cLoadGenerator()
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
            g = gates(tabs["bus_data"], tabs["y_bus_data"])  # on the solved (negative-load) form
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
    full = {t: pd.concat(parts[t], ignore_index=True) for t in TABLES}
    full["bus_data"], full["gen_data"] = reencode(
        full["bus_data"], full["gen_data"], ad.GEN_BUSES, ad.PMAX
    )
    dest = ad.ALLOWED_ROOT / NETWORK / "raw"
    if dest.parent.exists():
        shutil.rmtree(dest.parent)
    dest.mkdir(parents=True)
    for t in TABLES:
        df = full[t].sort_values("scenario")
        df["scenario_partition"] = df["scenario"] // 1000
        pq.write_to_dataset(
            pa.Table.from_pandas(df, preserve_index=False),
            str(dest / f"{t}.parquet"),
            partition_cols=["scenario_partition"],
        )
    del full
    shutil.copy(REPO_ROOT / HELD["network_file"], dest.parent / f"{NETWORK}.m")
    M = pd.concat(manifest, ignore_index=True).astype({"scenario": int})
    M["source"] = ad.SOURCE_TAG
    M.to_parquet(ad.ALLOWED_ROOT / "manifest.parquet", index=False)
    G = pd.concat(gate_rows, ignore_index=True)
    OUT.mkdir(parents=True, exist_ok=True)
    G.to_parquet(OUT / "synthetic_gates.parquet", index=False)
    summary = {
        "pools": {},
        "total_accepted": int(offset),
        "representation": "generator-aware (LBUZ31/32/33 explicit gen nodes on PQ buses)",
        **runner.git_commit(),
    }
    for pool in ad.POOLS:
        sel = G.pool == pool
        if not sel.any():
            continue
        summary["pools"][pool] = {
            "datakit_seeds": [int(s) for s in sorted(G.loc[sel, "datakit_seed"].unique())],
            "requested_max": requested[pool],
            "generated_by_datakit": int(sel.sum()),
            "accepted": int((sel & G.rejected.isna()).sum()),
            "rejected": G.loc[sel, "rejected"].value_counts().to_dict(),
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


def cmd_retention() -> None:
    """Re-encode the E5 (narrow) and E5b (broad) held-out synthetic tests for E5c models."""
    out = {}
    for name, mod in (("E5_TEST_GA", ad5), ("E5B_TEST_GA", ad5b)):
        man = mod.assert_synthetic_dataset(mod.ALLOWED_ROOT)
        ids = mod.pool_ids(man, "test").tolist()
        n = reencode_dataset(
            mod.ALLOWED_ROOT / NETWORK / "raw",
            ad.WORK / "datasets" / name / NETWORK / "raw",
            ad.GEN_BUSES,
            ad.PMAX,
            ids,
        )
        out[name] = {
            "source": str(mod.ALLOWED_ROOT.relative_to(REPO_ROOT)),
            "n": n,
            "source_ids_sha256": ad.sha256_ids(ids),
        }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "retention.json").write_text(json.dumps(out, indent=2))
    print(out)


def cmd_real() -> None:
    """Re-encode the E4 S1 export (same 2,829 states) — refused until E5c is frozen."""
    if not REGISTRY.exists() or not yaml.safe_load(REGISTRY.read_text()).get("frozen"):
        raise ad.LeakageError(
            "real states stay hidden until metadata/e5c_checkpoint_registry.yaml is frozen"
        )
    src = REPO_ROOT / "data/interim/e4/datasets/S1_WEATHER_ALIGNED" / NETWORK / "raw"
    dst = ad.WORK / "datasets/S1_WEATHER_ALIGNED_GENAWARE" / NETWORK / "raw"
    n = reencode_dataset(src, dst, ad.GEN_BUSES, ad.PMAX)
    r = (
        REPO_ROOT
        / "data/interim/e4/datasets/S1_WEATHER_ALIGNED"
        / NETWORK
        / "branch_ratings.parquet"
    )
    shutil.copy(r, dst.parent / "branch_ratings.parquet")
    (OUT / "real_reencode.json").write_text(json.dumps({"S1_WEATHER_ALIGNED_GENAWARE": n}))
    print(n)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["generate", "generate-all", "merge", "retention", "real"])
    ap.add_argument("--pool", choices=ad.POOLS)
    ap.add_argument("--pools", nargs="*", default=list(ad.POOLS))
    ap.add_argument("--seed", type=int)
    ap.add_argument("--jobs", type=int, default=7)
    ap.add_argument("--extra-train-seeds", type=int, default=0)
    a = ap.parse_args()
    if a.command == "generate":
        cmd_generate(a.pool, a.seed)
    elif a.command == "generate-all":
        cmd_generate_all(a.jobs, a.pools, a.extra_train_seeds)
    elif a.command == "merge":
        cmd_merge(a.extra_train_seeds)
    elif a.command == "retention":
        cmd_retention()
    else:
        cmd_real()
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    sys.exit(main())

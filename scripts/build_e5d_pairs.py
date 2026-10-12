"""E5d — paired synthetic AC states for response supervision (train / validation / test).

    uv run --env-file .env python scripts/build_e5d_pairs.py --set train [--chunks 6]
    uv run --env-file .env python scripts/build_e5d_pairs.py --set validation
    uv run --env-file .env python scripts/build_e5d_pairs.py --set test

Each pair is two AC-solved states on the E1 planning network (LTDS topology, unperturbed
admittances, intact, A1 slack limits — the E5c physics-probe network) that differ in ONE
controllable input (pv / battery / load). Base states: the E5c envelope sampler with the set's
pre-registered sampler seed; magnitudes: configs/experiments/e5d_response_training.yaml.
Solved with pandapower + PowerModels (E4 export_stream, same AC gates) in parallel chunks, merged,
then re-encoded generator-aware. The AC solutions are the targets.

Outputs: data/interim/e5d/pairs/<set>/{sundon_33kv/raw, pairs.parquet} (gitignored);
reports/experiments/e5d/pairs_<set>.json, pairs_<set>_gates.parquet
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import multiprocessing as mp
import shutil
import sys
import time
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from cloud2grid.genco import adaptation_e5d as ad
from cloud2grid.genco import runner
from cloud2grid.genco.generator_aware import reencode
from cloud2grid.licensing.registry import REPO_ROOT
from cloud2grid.scenarios import response_pairs_e5d as rp

OUT = REPO_ROOT / "reports/experiments/e5d"
ZS = yaml.safe_load((REPO_ROOT / "configs/experiments/e4_zero_shot.yaml").read_text())
TABLES = ["bus_data", "branch_data", "gen_data", "y_bus_data", "runtime_data"]
META = [
    "probe_id",
    "probe_type",
    "magnitude_class",
    "member",
    "node",
    "x_mw",
    "base_id",
    "base_hash",
]


def _probes_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "e5c_probes", REPO_ROOT / "scripts/build_e5c_physics_probes.py"
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _states(pairs: pd.DataFrame, net: Any, loads: dict, sg: dict) -> Iterator[tuple[dict, Any]]:
    for d in pairs.to_dict("records"):
        for node, idx in loads.items():
            net.load.loc[idx, ["p_mw", "q_mvar"]] = [d[f"P:{node}"], d[f"Q:{node}"]]
        for node, idx in sg.items():
            net.sgen.loc[idx, ["p_mw", "q_mvar"]] = [-d[f"P:{node}"], 0.0]
        yield {k: d[k] for k in META}, net


def solve_chunk(chunk: pd.DataFrame, out_root: str) -> pd.DataFrame:
    """AC-solve one chunk of pair states (own process, own Julia session)."""
    from cloud2grid.genco import opengridfm_export as ox

    net, loads, sg = _probes_module().planning_net()
    _, gates = ox.export_stream(
        _states(chunk, net, loads, sg),
        ad.NETWORK,
        Path(out_root),
        include_dc=True,
        slack_limits_mva=ZS["slack_limits_mva"],
    )
    return gates


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=list(ad.PAIR_SETS), required=True)
    ap.add_argument("--chunks", type=int, default=1)
    a = ap.parse_args()
    spec = ad.CFG["response_pairs"]["sets"][a.set]
    seed, n_base = int(spec["sampler_seed"]), int(spec["n_base"])
    t0 = time.perf_counter()
    base = rp.base_states(n_base, seed)
    pairs = rp.response_pairs(base, seed, a.set)
    inj = rp.injection_columns(pairs)
    edges = np.linspace(0, n_base, a.chunks + 1).astype(int)
    tmp = ad.WORK / "pairs_tmp" / a.set
    if tmp.exists():
        shutil.rmtree(tmp)
    chunks = [
        pairs[(pairs.base_id >= lo) & (pairs.base_id < hi)]
        for lo, hi in zip(edges, edges[1:], strict=False)
    ]
    with ProcessPoolExecutor(max_workers=a.chunks, mp_context=mp.get_context("spawn")) as ex:
        futs = [ex.submit(solve_chunk, c, str(tmp / f"chunk{i}")) for i, c in enumerate(chunks)]
        gate_parts = [f.result() for f in futs]
    # ---- merge chunks (consecutive scenario ids), re-encode generator-aware
    parts: dict[str, list[pd.DataFrame]] = {t: [] for t in TABLES}
    gates_all, offset = [], 0
    for i, g in enumerate(gate_parts):
        g = g.reset_index(drop=True)
        acc = g.rejected.isna()
        raw = tmp / f"chunk{i}" / ad.NETWORK / "raw"
        if acc.any():
            tabs = {t: pd.read_parquet(raw / f"{t}.parquet") for t in TABLES}
            for t in TABLES:
                df = tabs[t].drop(columns=["scenario_partition"], errors="ignore")
                df["scenario"] = df["scenario"] + offset
                parts[t].append(df)
            g.loc[acc, "scenario"] = g.loc[acc, "scenario"] + offset
            offset += int(acc.sum())
        gates_all.append(g)
    G = pd.concat(gates_all, ignore_index=True)
    if len(G) != len(pairs):
        raise RuntimeError("gate rows do not match requested states")
    full = {t: pd.concat(parts[t], ignore_index=True) for t in TABLES}
    full["bus_data"], full["gen_data"] = reencode(
        full["bus_data"], full["gen_data"], ad.GEN_BUSES, ad.PMAX
    )
    root = ad.PAIR_ROOT[a.set]
    dest = root / ad.NETWORK / "raw"
    if root.exists():
        shutil.rmtree(root)
    dest.mkdir(parents=True)
    for t in TABLES:
        df = full[t].sort_values("scenario", kind="stable")
        df["scenario_partition"] = df["scenario"] // 1000
        pq.write_to_dataset(
            pa.Table.from_pandas(df, preserve_index=False),
            str(dest / f"{t}.parquet"),
            partition_cols=["scenario_partition"],
        )
    shutil.copy(next((tmp / "chunk0" / ad.NETWORK).glob("*.m")), dest.parent / f"{ad.NETWORK}.m")
    shutil.rmtree(tmp)
    # ---- manifest: one row per state (accepted ones carry their scenario id)
    G = pd.concat([G, pairs[inj].reset_index(drop=True)], axis=1)
    acc = G[G.rejected.isna()].copy()
    acc["scenario"] = acc["scenario"].astype(int)
    acc["complete"] = acc.groupby("probe_id")["member"].transform("nunique") == 2
    acc["set"], acc["sampler_seed"], acc["source"] = a.set, seed, ad.PAIR_SOURCE_TAG
    acc.to_parquet(root / "pairs.parquet", index=False)
    OUT.mkdir(parents=True, exist_ok=True)
    G.drop(columns=inj).to_parquet(OUT / f"pairs_{a.set}_gates.parquet", index=False)
    done = acc[acc.complete & (acc.member == "A")]
    rec = {
        "set": a.set,
        "sampler_seed": seed,
        "base_states": n_base,
        "pairs_requested": int(pairs.probe_id.nunique()),
        "states_requested": int(len(pairs)),
        "states_accepted": int(len(acc)),
        "states_written": int(offset),
        "rejected": G["rejected"].value_counts().to_dict(),
        "complete_pairs": {t: int((done.probe_type == t).sum()) for t in rp.TYPES},
        "complete_pairs_by_class": done.groupby(["probe_type", "magnitude_class"])
        .size()
        .rename("n")
        .reset_index()
        .to_dict("records"),
        "x_mw_abs_range": {
            t: [
                float(done.loc[done.probe_type == t, "x_mw"].abs().min()),
                float(done.loc[done.probe_type == t, "x_mw"].abs().max()),
            ]
            for t in rp.TYPES
        },
        "zero_nonzero_pv_pairs": int(_zero_crossings(acc)),
        "chunks": a.chunks,
        "wall_s": time.perf_counter() - t0,
        "sources_read": sorted(rp.SOURCES_READ),
        **runner.git_commit(),
    }
    (OUT / f"pairs_{a.set}.json").write_text(json.dumps(rec, indent=2, default=str))
    print(
        json.dumps(
            {k: v for k, v in rec.items() if k != "complete_pairs_by_class"}, indent=1, default=str
        )
    )
    return 0


def _zero_crossings(acc: pd.DataFrame) -> int:
    """Complete pv pairs where exactly one member has zero LBUZ generation."""
    pv = acc[acc.complete & (acc.probe_type == "pv")]
    gcols = [c for c in pv.columns if c.startswith("P:EPN:LBUZ3")]
    g = -pv[gcols].sum(axis=1)
    z = (g.abs() < 1e-12).groupby(pv.probe_id).sum()
    return int((z == 1).sum())


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    sys.exit(main())

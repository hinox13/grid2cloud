# ruff: noqa: E501
"""Economic impact: AC-solve counterfactual states and predict them with the frozen models.

Reuses the published E5d pair machinery unchanged:
- `build_e5d_pairs.solve_chunk` solves any table of injection vectors on the E1 planning case
  (pandapower + PowerModels export, the E4 AC gates) into GraphKit raw tables;
- `generator_aware.reencode` applies the E5c/E5d representation;
- GraphKit's own `predict` CLI runs a frozen checkpoint with its own normaliser.
Nothing is trained, and no frozen file is written: outputs go to data/interim/economic_impact/pipeline/.

A state table has one row per state: META columns (`state_id`, `scenario_id`, `role`, `action`,
`dpv_mw`, `dbat_mw`) plus `P:<node>` / `Q:<node>` injections in the E5d convention
(+ withdrawal: load, battery charging; − generation: LBUZ31/32/33).
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import time
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import torch
import yaml

from cloud2grid.genco import adaptation_e5d as ad
from cloud2grid.genco import runner
from cloud2grid.genco.generator_aware import reencode
from cloud2grid.licensing.registry import REPO_ROOT

WORK = REPO_ROOT / "data/interim/economic_impact/pipeline"
TABLES = ["bus_data", "branch_data", "gen_data", "y_bus_data", "runtime_data"]
META = ["state_id", "scenario_id", "role", "action", "dpv_mw", "dbat_mw"]
MODELS = {  # the two published, frozen checkpoints (release cloud2grid-models-v1)
    "E5c": "e5c_ft_n10000_s2",
    "E5d": "e5d_l1_s0",
}
PV_NODES = ["EPN:LBUZ31", "EPN:LBUZ32", "EPN:LBUZ33"]
BATTERY = "EPN:CHAP31"


def _load(name: str, rel: str):  # noqa: ANN202
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


PAIRS = _load("economic_build_e5d_pairs", "scripts/build_e5d_pairs.py")
TRAIN = _load("economic_train_e5d", "scripts/train_e5d.py")


def _pairs_frame(states: pd.DataFrame) -> pd.DataFrame:
    """Adapt a state table to the columns solve_chunk expects (its META names)."""
    f = states.copy()
    f["probe_id"], f["probe_type"], f["magnitude_class"] = f.state_id, "economic", "economic"
    f["member"], f["node"], f["x_mw"] = f.role, BATTERY, f.dbat_mw
    f["base_id"], f["base_hash"] = f.scenario_id, ""
    return f


def solve(states: pd.DataFrame, name: str) -> tuple[Path, pd.DataFrame]:
    """AC-solve every state, re-encode generator-aware, write a GraphKit dataset root.

    Returns the root and a manifest: one row per requested state with its GraphKit scenario id
    (NaN if an AC gate rejected it)."""
    tmp = WORK / "tmp" / name
    shutil.rmtree(tmp, ignore_errors=True)
    t0 = time.perf_counter()
    gates = PAIRS.solve_chunk(_pairs_frame(states), str(tmp)).reset_index(drop=True)
    wall = time.perf_counter() - t0
    if len(gates) != len(states):
        raise RuntimeError("gate rows do not match requested states")
    raw = tmp / ad.NETWORK / "raw"
    tabs = {t: pd.read_parquet(raw / f"{t}.parquet").drop(columns=["scenario_partition"], errors="ignore") for t in TABLES}
    tabs["bus_data"], tabs["gen_data"] = reencode(tabs["bus_data"], tabs["gen_data"], ad.GEN_BUSES, ad.PMAX)
    root = WORK / "datasets" / name
    shutil.rmtree(root, ignore_errors=True)
    dest = root / ad.NETWORK / "raw"
    dest.mkdir(parents=True)
    for t in TABLES:
        df = tabs[t].sort_values("scenario", kind="stable")
        df["scenario_partition"] = df["scenario"] // 1000
        pq.write_to_dataset(pa.Table.from_pandas(df, preserve_index=False), str(dest / f"{t}.parquet"),
                            partition_cols=["scenario_partition"])  # fmt: skip
    shutil.copy(next((tmp / ad.NETWORK).glob("*.m")), dest.parent / f"{ad.NETWORK}.m")
    shutil.rmtree(tmp)
    man = states[META].reset_index(drop=True).copy()
    man["scenario"] = gates["scenario"].where(gates["rejected"].isna())
    man["rejected"] = gates["rejected"]
    man.attrs["solve_export_wall_s"] = wall
    man.to_parquet(root / "manifest.parquet", index=False)
    return root, man


def predict(model: str, root: Path, name: str, gpu: str = "", ids: list[int] | None = None) -> tuple[Path, float]:
    """Run GraphKit predict with a frozen checkpoint (gpu "" = CPU). Returns output dir, wall s."""
    run = MODELS[model]
    weights, stats = TRAIN.weights_of(run)
    if ids is None:
        ids = list(range(pd.read_parquet(root / ad.NETWORK / "raw/bus_data.parquet", columns=["scenario"])["scenario"].nunique()))
    n = len(ids)
    split = WORK / "splits" / name
    split.mkdir(parents=True, exist_ok=True)
    for nm, x in (("train", []), ("val", []), ("test", ids)):
        torch.save(torch.tensor(x, dtype=torch.long), split / f"{nm}.pt")
    conf = runner.write_config(
        yaml.safe_load(TRAIN.ft5.RECIPE.read_text()), WORK / "configs" / f"{run}__{name}.yaml",
        networks=[ad.NETWORK], scenarios=[n], split_by_load_scenario_idx=False,
        split_from_existing_files=str(split), workers=4, test_ratio=1.0, val_ratio=0.0,
    )  # fmt: skip
    out = WORK / "predictions" / run / name
    shutil.rmtree(out, ignore_errors=True)
    args = [
        "--config", str(conf), "--config_conversion", TRAIN.ft5.E4["graphkit"]["config_conversion"],
        "--data_path", str(root), "--model_path", str(weights), "--normalizer_stats", str(stats),
        "--log_dir", str(WORK / "mlruns"), "--exp_name", "economic_predict", "--run_name", f"{run}__{name}",
        "--output_path", str(out),
    ]  # fmt: skip
    res = runner.run_cli("predict", args, WORK / "logs" / f"predict_{run}__{name}.log", gpu)
    return out, float(res["wall_s"])


def read_predictions(out: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    bus = pd.read_parquet(out / f"{ad.NETWORK}_predictions.parquet")
    br = pd.read_parquet(out / f"{ad.NETWORK}_branch_predictions.parquet")
    return bus, br


def import_mw(bus: pd.DataFrame, col: str) -> pd.Series:
    """Grid import per scenario: the slack (REF) bus active injection (MW)."""
    ref = bus[bus["REF"] == 1]
    return ref.groupby("scenario")[col].sum()

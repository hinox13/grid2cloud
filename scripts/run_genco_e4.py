"""E4 — GENCO zero-shot inference with the official tooling (no weights change).

    uv run python scripts/run_genco_e4.py fetch
    uv run python scripts/run_genco_e4.py reproduce          # paper §5.5.3 zero-shot on IEEE 118
    uv run python scripts/run_genco_e4.py fit-normalizer      # fixed per-unit base from S0
    uv run python scripts/run_genco_e4.py predict --family S1_WEATHER_ALIGNED [--own-normalizer]

`predict` runs `gridfm_graphkit predict` on a family dataset (data/interim/e4/datasets/<family>)
with EVERY scenario in the scored split (split files), the pretrained transfer checkpoint and the
fixed normalizer from S0 (configs/experiments/e4_zero_shot.yaml `normalizer`).
Outputs: data/interim/e4/predictions/<family>/ (bus + branch parquet) and
reports/experiments/e4/runs/<family>.json (command, wall time, environment).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import torch
import yaml

from cloud2grid.genco import runner
from cloud2grid.licensing.registry import REPO_ROOT

CFG = yaml.safe_load((REPO_ROOT / "configs/experiments/e4_zero_shot.yaml").read_text())
CKPT = REPO_ROOT / "data/raw/opengridfm/checkpoints/genco-pf-transfer"
WORK = REPO_ROOT / "data/interim/e4"
OUT = REPO_ROOT / "reports/experiments/e4"
NETWORK = "sundon_33kv"


def eval_config() -> dict:
    g = CFG["graphkit"]
    p = WORK / "configs" / "case118_eval.yaml"
    if not p.exists():
        runner.fetch_github(
            g["eval_config_repo"], g["eval_config_revision"], g["eval_config_path"], p
        )
    return yaml.safe_load(p.read_text())


def cmd_fetch() -> None:
    m = CFG["model"]
    runner.fetch_hf(m["repo_id"], m["revision"], ["pretraining/*"], CKPT, m["source_id"])
    runner.fetch_hf(m["repo_id"], m["revision"], ["data/case118_ieee/raw/*"], CKPT, m["source_id"])
    runner.fetch_hf(
        m["repo_id"],
        m["revision"],
        ["mlflow/eval/finetune_case118_0_eval/artifacts/test/*.csv"],
        CKPT,
        m["source_id"],
    )
    eval_config()
    print("fetched")


def cmd_reproduce() -> None:
    cfg = eval_config()
    conf = runner.write_config(cfg, WORK / "configs" / "case118_eval_local.yaml", workers=8)
    run = runner.run_cli(
        "evaluate",
        [
            "--config",
            str(conf),
            "--config_conversion",
            CFG["graphkit"]["config_conversion"],
            "--data_path",
            str(CKPT / "data"),
            "--model_path",
            str(CKPT / CFG["model"]["weights"]),
            "--log_dir",
            str(WORK / "mlruns"),
            "--exp_name",
            "e4_reproduce",
            "--run_name",
            "zero_shot_case118",
        ],
        WORK / "logs" / "reproduce_case118.log",
    )
    runs = [
        t.parent.parent
        for t in (WORK / "mlruns").glob("*/*/tags/mlflow.runName")
        if t.read_text().strip() == "zero_shot_case118"
    ]
    latest = max(runs, key=lambda p: p.stat().st_mtime)
    got = pd.read_csv(latest / "artifacts" / "test" / "case118_ieee_metrics.csv")
    got = dict(zip(got["Metric"], got["Value"].astype(float), strict=True))
    ref = CFG["reproduction"]["reference"]
    tol = CFG["reproduction"]["rel_tolerance"]
    cmp = {
        k: {"ours": got.get(k), "paper": v, "rel_diff": (got.get(k) - v) / v}
        for k, v in ref.items()
    }
    ok = all(abs(c["rel_diff"]) <= tol for c in cmp.values())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "reproduction_case118_zero_shot.json").write_text(
        json.dumps(
            {
                "pass": ok,
                "comparison": cmp,
                "run": run,
                "mlflow_run": str(latest.relative_to(REPO_ROOT)),
                "environment": runner.environment(),
                "model": CFG["model"],
            },
            indent=2,
            default=str,
        )
    )
    print(json.dumps(cmp, indent=1), "\nPASS" if ok else "\nFAIL")
    if not ok:
        raise SystemExit(1)


def dataset_dir(family: str) -> Path:
    return WORK / "datasets" / family


def cmd_fit_normalizer(family: str = "S0_STANDARD_SYNTHETIC") -> None:
    """Per-unit base: graphkit's own HeteroDataMVANormalizer.fit on ALL scenarios of `family`
    (S0 = the fixed reference used for every family; other families only for the sensitivity)."""
    from gridfm_graphkit.datasets.normalizers import HeteroDataMVANormalizer

    raw = dataset_dir(family) / NETWORK / "raw"
    n = pd.read_parquet(raw / "bus_data.parquet", columns=["scenario"])["scenario"].nunique()
    norm = HeteroDataMVANormalizer(SimpleNamespace(data=SimpleNamespace(baseMVA=100)))
    stats = norm.fit(str(raw), list(range(n)))
    path = (
        WORK
        / "normalizer"
        / ("S0_normalizer_stats.pt" if family.startswith("S0") else f"{family}_normalizer_stats.pt")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({NETWORK: stats}, path)
    info = {k: float(v) for k, v in stats.items()}
    (OUT / f"normalizer_{family}.json").write_text(
        json.dumps({"fitted_on": family, "n_scenarios": n, **info}, indent=2)
    )
    print(info)


def write_splits(raw: Path, dest: Path) -> int:
    n = pd.read_parquet(raw / "bus_data.parquet", columns=["scenario"])["scenario"].nunique()
    dest.mkdir(parents=True, exist_ok=True)
    torch.save(torch.tensor([], dtype=torch.long), dest / "train.pt")
    torch.save(torch.tensor([], dtype=torch.long), dest / "val.pt")
    torch.save(torch.arange(n, dtype=torch.long), dest / "test.pt")  # every scenario is scored
    return n


def cmd_predict(family: str, own_normalizer: bool, tag: str) -> None:
    root = dataset_dir(family)
    raw = root / NETWORK / "raw"
    n = write_splits(raw, root / "splits")
    cfg = eval_config()
    conf = runner.write_config(
        cfg,
        WORK / "configs" / f"{family}{tag}.yaml",
        networks=[NETWORK],
        scenarios=[n],
        split_by_load_scenario_idx=False,
        split_from_existing_files=str(root / "splits"),
        workers=4,
        test_ratio=1.0,
        val_ratio=0.0,
    )
    out = WORK / "predictions" / f"{family}{tag}"
    args = [
        "--config",
        str(conf),
        "--config_conversion",
        CFG["graphkit"]["config_conversion"],
        "--data_path",
        str(root),
        "--model_path",
        str(CKPT / CFG["model"]["weights"]),
        "--log_dir",
        str(WORK / "mlruns"),
        "--exp_name",
        "e4_predict",
        "--run_name",
        f"{family}{tag}",
        "--output_path",
        str(out),
    ]
    stats = f"{family}_normalizer_stats.pt" if own_normalizer else "S0_normalizer_stats.pt"
    args += ["--normalizer_stats", str(WORK / "normalizer" / stats)]
    run = runner.run_cli("predict", args, WORK / "logs" / f"predict_{family}{tag}.log")
    OUT.joinpath("runs").mkdir(parents=True, exist_ok=True)
    (OUT / "runs" / f"{family}{tag}.json").write_text(
        json.dumps(
            {
                "family": family,
                "n_scenarios": n,
                "normalizer": "own (fitted on this family)" if own_normalizer else "S0 fixed",
                "run": run,
                "seconds_per_scenario": run["wall_s"] / max(n, 1),
                "environment": runner.environment(),
                "model": CFG["model"],
                "output": str(out.relative_to(REPO_ROOT)),
            },
            indent=2,
            default=str,
        )
    )
    print(f"{family}{tag}: {n} scenarios in {run['wall_s']:.1f} s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["fetch", "reproduce", "fit-normalizer", "predict"])
    ap.add_argument("--family")
    ap.add_argument("--own-normalizer", action="store_true")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    if a.command == "fetch":
        cmd_fetch()
    elif a.command == "reproduce":
        cmd_reproduce()
    elif a.command == "fit-normalizer":
        cmd_fit_normalizer(a.family or "S0_STANDARD_SYNTHETIC")
    else:
        cmd_predict(a.family, a.own_normalizer, a.tag or ("_ownnorm" if a.own_normalizer else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

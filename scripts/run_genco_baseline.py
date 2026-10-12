"""E0 — reproduce a minimal GENCO power-flow evaluation with the official OpenGridFM tooling.

    uv sync --extra genco
    uv run python scripts/run_genco_baseline.py [--config <experiment yaml>]

Steps: licence gate → pinned Hugging Face downloads (+ provenance) → `gridfm_graphkit evaluate`
(subprocess, unchanged upstream CLI) → metrics.json / config.yaml / run_info.json in
reports/experiments/e0_genco_baseline/, including a comparison with the GENCO paper numbers.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yaml

from cloud2grid.licensing import Registry, Use, require
from cloud2grid.licensing.registry import REPO_ROOT
from cloud2grid.utils import provenance

DEFAULT_CONFIG = REPO_ROOT / "configs" / "experiments" / "e0_genco_baseline.yaml"
PACKAGES = [
    "gridfm-graphkit",
    "gridfm-datakit",
    "torch",
    "torch-geometric",
    "torch-scatter",
    "lightning",
    "mlflow",
    "numpy",
    "pandas",
    "huggingface-hub",
]


def download(cfg: dict[str, Any], registry: Registry) -> tuple[Path, Path]:
    from huggingface_hub import snapshot_download

    m, d, p = cfg["model"], cfg["dataset"], cfg["paths"]
    data_dir = REPO_ROOT / p["data_root"] / d["network"] / "raw"
    ckpt_root = REPO_ROOT / p["checkpoint_root"]

    snapshot_download(d["repo_id"], repo_type="dataset", revision=d["revision"], local_dir=data_dir)
    provenance.record(
        data_dir,
        source_id=cfg["source_ids"]["dataset"],
        revision=d["revision"],
        url=f"https://huggingface.co/datasets/{d['repo_id']}",
        licence=registry.sources[cfg["source_ids"]["dataset"]].licence,
    )
    snapshot_download(
        m["repo_id"],
        revision=m["revision"],
        local_dir=ckpt_root,
        allow_patterns=[f"{m['subfolder']}/*"],
    )
    ckpt_dir = ckpt_root / m["subfolder"]
    provenance.record(
        ckpt_dir,
        source_id=cfg["source_ids"]["model"],
        revision=m["revision"],
        url=f"https://huggingface.co/{m['repo_id']}/tree/{m['revision']}/{m['subfolder']}",
        licence=registry.sources[cfg["source_ids"]["model"]].licence,
    )
    return data_dir, ckpt_dir


def evaluate(cfg: dict[str, Any], ckpt_dir: Path, run_name: str) -> tuple[Path, float, list[str]]:
    m, p, e = cfg["model"], cfg["paths"], cfg["evaluate"]
    work = REPO_ROOT / p["work_dir"]
    mlruns = work / "mlruns"
    work.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "gridfm_graphkit",
        "evaluate",
        "--config_conversion",
        e["config_conversion"],
        "--config",
        str(ckpt_dir / m["config_file"]),
        "--data_path",
        str(REPO_ROOT / p["data_root"]),
        "--model_path",
        str(ckpt_dir / m["weights_file"]),
        "--normalizer_stats",
        str(ckpt_dir / m["normalizer_stats_file"]),
        "--log_dir",
        str(mlruns),
        "--exp_name",
        cfg["experiment_id"],
        "--run_name",
        run_name,
        *e.get("extra_args", []),
    ]
    env = {
        **os.environ,
        "MLFLOW_ALLOW_FILE_STORE": "true",
        "MLFLOW_DISABLE_AGENT_HINT": "1",
        "CUDA_VISIBLE_DEVICES": str(e["cuda_visible_devices"]),
    }
    log_path = work / f"evaluate_{run_name}.log"
    print(f"$ {' '.join(cmd)}\n  (log: {log_path.relative_to(REPO_ROOT)})", flush=True)
    start = time.perf_counter()
    with log_path.open("w") as log:
        result = subprocess.run(cmd, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
    elapsed = time.perf_counter() - start
    if result.returncode != 0:
        raise SystemExit(f"gridfm_graphkit evaluate failed ({result.returncode}); see {log_path}")

    runs = [
        tag.parent.parent
        for tag in mlruns.glob("*/*/tags/mlflow.runName")
        if tag.read_text().strip() == run_name
    ]
    if len(runs) != 1:
        raise SystemExit(f"expected one MLflow run named {run_name!r}, found {len(runs)}")
    return runs[0], elapsed, cmd


def read_metric_csv(path: Path) -> dict[str, float]:
    df = pd.read_csv(path)
    return dict(zip(df["Metric"], df["Value"].astype(float), strict=True))


def split_digest(splits: dict[str, list[int]]) -> dict[str, str]:
    return {
        k: hashlib.sha256(json.dumps(sorted(v)).encode()).hexdigest() for k, v in splits.items()
    }


def environment_info(cuda_visible_devices: str) -> dict[str, Any]:
    import torch

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()

    host_gpus = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    used = [int(i) for i in cuda_visible_devices.split(",") if i.strip()]
    driver = ""
    if shutil.which("nvidia-smi"):
        driver = (
            subprocess.run(
                ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                check=False,
            )
            .stdout.split("\n")[0]
            .strip()
        )
    return {
        "git_commit": git("rev-parse", "HEAD"),
        "git_dirty": bool(git("status", "--porcelain")),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "cuda_available": torch.cuda.is_available(),
        "torch_cuda": torch.version.cuda,
        "gpus_on_host": host_gpus,
        "evaluate_cuda_visible_devices": cuda_visible_devices,
        "evaluate_gpus": [host_gpus[i] for i in used if i < len(host_gpus)] or "cpu",
        "nvidia_driver": driver,
        "packages": {name: version(name) for name in PACKAGES},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    cfg = yaml.safe_load(args.config.read_text())

    registry = Registry.load()
    for role, use in [("dataset", Use.DOWNLOAD), ("model", Use.DOWNLOAD), ("code", Use.PROCESS)]:
        require(cfg["source_ids"][role], use, registry)

    started = dt.datetime.now(dt.UTC)
    run_name = started.strftime("run_%Y%m%dT%H%M%SZ")
    t0 = time.perf_counter()
    _, ckpt_dir = download(cfg, registry)
    download_s = time.perf_counter() - t0

    run_dir, evaluate_s, cmd = evaluate(cfg, ckpt_dir, run_name)
    network = cfg["dataset"]["network"]
    artifacts = run_dir / "artifacts"
    metrics = read_metric_csv(artifacts / "test" / f"{network}_metrics.csv")
    rmse = pd.read_csv(artifacts / "test" / f"{network}_RMSE.csv").set_index("Metric")
    splits = json.loads((artifacts / "stats" / f"{network}_scenario_splits.json").read_text())

    ref = cfg["reference"]
    comparison = {}
    for name, ref_value in ref["metrics"].items():
        rel = (metrics[name] - ref_value) / ref_value
        comparison[name] = {
            "ours": metrics[name],
            "paper": ref_value,
            "rel_diff": rel,
            "within_tolerance": abs(rel) <= ref["rel_tolerance"],
        }
    try:
        ref_splits = requests.get(ref["split_url"], timeout=120).json()
        split_match: bool | None = all(
            sorted(splits[k]) == sorted(ref_splits[k]) for k in ("train", "val", "test")
        )
    except (requests.RequestException, ValueError, KeyError):
        split_match = None

    out = REPO_ROOT / cfg["paths"]["output_dir"]
    out.mkdir(parents=True, exist_ok=True)
    reproduced = all(c["within_tolerance"] for c in comparison.values()) and split_match is True
    (out / "metrics.json").write_text(
        json.dumps(
            {
                "experiment_id": cfg["experiment_id"],
                "run_name": run_name,
                "provenance_class": "PREDICTED (GENCO) vs SIMULATED (datakit AC power flow)",
                "network": network,
                "split": "test",
                "n_scenarios": {k: len(v) for k, v in splits.items()},
                "metrics": metrics,
                "rmse": rmse.to_dict(orient="index"),
                "reference_comparison": comparison,
                "rel_tolerance": ref["rel_tolerance"],
                "split_matches_paper_eval": split_match,
                "reproduced_within_tolerance": reproduced,
            },
            indent=2,
        )
        + "\n"
    )

    gridfm_cfg = yaml.safe_load((ckpt_dir / cfg["model"]["config_file"]).read_text())
    (out / "config.yaml").write_text(
        yaml.safe_dump({"experiment": cfg, "gridfm_model_config": gridfm_cfg}, sort_keys=False)
    )
    (out / "run_info.json").write_text(
        json.dumps(
            {
                "started_at": started.isoformat(timespec="seconds"),
                "runtime_s": {
                    "download_and_hash": round(download_s, 1),
                    "evaluate": round(evaluate_s, 1),
                },
                "command": [
                    Path(c).relative_to(REPO_ROOT).as_posix() if c.startswith(str(REPO_ROOT)) else c
                    for c in cmd
                ],
                "mlflow_run_dir": run_dir.relative_to(REPO_ROOT).as_posix(),
                "split_sha256": split_digest(splits),
                "environment": environment_info(str(cfg["evaluate"]["cuda_visible_devices"])),
            },
            indent=2,
        )
        + "\n"
    )

    print(json.dumps(comparison, indent=2))
    print(f"split matches paper eval: {split_match}; reproduced: {reproduced}")
    print(f"wrote {out.relative_to(REPO_ROOT)}/{{metrics.json,config.yaml,run_info.json}}")
    return 0 if reproduced else 1


if __name__ == "__main__":
    sys.exit(main())

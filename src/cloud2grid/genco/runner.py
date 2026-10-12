"""Run the official gridfm-graphkit CLI (unchanged) and record exact provenance (E4).

GENCO is never reimplemented here: inference is `python -m gridfm_graphkit evaluate|predict`
in a subprocess, exactly as in E0. This module only pins downloads, writes graphkit YAML
configs, runs the CLI, and captures the environment.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

import requests
import torch
import yaml

from cloud2grid.licensing import Registry, Use, require
from cloud2grid.licensing.registry import REPO_ROOT
from cloud2grid.utils import provenance

PACKAGES = [
    "gridfm-graphkit",
    "gridfm-datakit",
    "torch",
    "torch-geometric",
    "torch-scatter",
    "lightning",
    "pandapower",
    "numpy",
    "pandas",
]


def git_commit() -> dict[str, Any]:
    run = lambda *a: subprocess.run(a, capture_output=True, text=True, cwd=REPO_ROOT).stdout.strip()  # noqa: E731
    return {
        "git_commit": run("git", "rev-parse", "HEAD"),
        "working_tree_dirty": bool(run("git", "status", "--porcelain")),
    }


def environment() -> dict[str, Any]:
    gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {p: version(p) for p in PACKAGES},
        "cuda_available": torch.cuda.is_available(),
        "gpu": gpu,
        "torch_cuda": torch.version.cuda,
        **git_commit(),
    }


def fetch_hf(
    repo_id: str, revision: str, patterns: list[str], local_dir: Path, source_id: str
) -> Path:
    from huggingface_hub import snapshot_download

    reg = Registry.load()
    require(source_id, Use.DOWNLOAD, reg)
    snapshot_download(repo_id, revision=revision, local_dir=local_dir, allow_patterns=patterns)
    for pat in patterns:
        sub = local_dir / pat.split("/*")[0].rstrip("*").rstrip("/")
        if sub.exists():
            provenance.record(
                sub,
                source_id=source_id,
                revision=revision,
                url=f"https://huggingface.co/{repo_id}/tree/{revision}/{pat}",
                licence=reg.sources[source_id].licence,
            )
    return local_dir


def fetch_github(repo: str, revision: str, path: str, dest: Path) -> Path:
    url = f"https://raw.githubusercontent.com/{repo}/{revision}/{path}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    provenance.record(
        dest, source_id="gridfm_graphkit", revision=revision, url=url, licence="Apache-2.0"
    )
    return dest


def write_config(base: dict[str, Any], dest: Path, **data_overrides: Any) -> Path:
    cfg = yaml.safe_load(yaml.safe_dump(base))
    cfg["data"].update(data_overrides)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(yaml.safe_dump(cfg, sort_keys=False))
    return dest


def run_cli(command: str, args: list[str], log: Path, cuda: str = "0") -> dict[str, Any]:
    cmd = [sys.executable, "-m", "gridfm_graphkit", command, *args]
    env = {
        **os.environ,
        "MLFLOW_ALLOW_FILE_STORE": "true",
        "MLFLOW_DISABLE_AGENT_HINT": "1",
        "CUDA_VISIBLE_DEVICES": cuda,
    }
    log.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    with log.open("w") as fh:
        rc = subprocess.run(
            cmd, env=env, stdout=fh, stderr=subprocess.STDOUT, check=False
        ).returncode
    wall = time.perf_counter() - t0
    if rc != 0:
        raise RuntimeError(f"gridfm_graphkit {command} failed ({rc}); see {log}")
    return {"command": [str(c) for c in cmd], "wall_s": wall, "log": str(log)}

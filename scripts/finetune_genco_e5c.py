"""E5c — GENCO adaptation on generator-aware synthetic data, E5 OFFICIAL workflow unchanged.

    uv run python scripts/finetune_genco_e5c.py prepare
    uv run python scripts/finetune_genco_e5c.py ladder [--gpus 0 1]
    uv run python scripts/finetune_genco_e5c.py predict --run RUN --target TARGET

Targets: synthetic_test / synthetic_val (E5c pools), e5_test_ga / e5b_test_ga (re-encoded E5 / E5b
held-out tests), probes_validation / probes_test (paired physics probes) and — ONLY for runs listed
in the frozen metadata/e5c_checkpoint_registry.yaml — S1_WEATHER_ALIGNED_GENAWARE.
Training = scripts/finetune_genco_e5.py bound to the E5c dataset / pools / names / outputs.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import torch
import yaml

from cloud2grid.genco import adaptation_e5c as ad
from cloud2grid.genco import runner
from cloud2grid.licensing.registry import REPO_ROOT

_spec = importlib.util.spec_from_file_location("ft5", REPO_ROOT / "scripts/finetune_genco_e5.py")
ft5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ft5)

OUT = REPO_ROOT / "reports/experiments/e5c"
REGISTRY = REPO_ROOT / "metadata/e5c_checkpoint_registry.yaml"
SYN_TARGETS = {
    "e5_test_ga": ad.WORK / "datasets/E5_TEST_GA",
    "e5b_test_ga": ad.WORK / "datasets/E5B_TEST_GA",
    "probes_validation": ad.WORK / "probes/validation",
    "probes_test": ad.WORK / "probes/test",
}
REAL_TARGETS = {"S1_WEATHER_ALIGNED_GENAWARE": ad.WORK / "datasets/S1_WEATHER_ALIGNED_GENAWARE"}

ft5.ad = ad
ft5.OUT = OUT
ft5.REGISTRY = REGISTRY
ft5.dataset_root = lambda rep="SUNDON_ORIGINAL": ad.ALLOWED_ROOT


def runs_spec() -> list[tuple[int, int, str]]:
    jobs = [
        (int(n), s, "pretrained") for n, seeds in ad.CFG["ladder"]["seeds"].items() for s in seeds
    ]
    return sorted(jobs, key=lambda j: (j[0], j[1]))


ft5.runs_spec = runs_spec
ft5.scratch_spec = lambda: []


def frozen_runs() -> set[str]:
    if not REGISTRY.exists():
        return set()
    reg = yaml.safe_load(REGISTRY.read_text())
    if not reg.get("frozen"):
        return set()
    ok = set()
    for r in reg.get("evaluable_on_real", []):
        c = reg["checkpoints"].get(r) or reg["post_freeze_curve_runs"].get(r)
        for k in ("checkpoint", "normalizer"):
            if ad.sha256_file(REPO_ROOT / c[k]["path"]) != c[k]["sha256"]:
                raise ad.LeakageError(f"{r}: {k} changed after freezing")
        ok.add(r)
    return ok


ft5.frozen_runs = frozen_runs


def weights_of(run: str) -> tuple[Path, Path]:
    if run == "zero_shot":
        return ft5.PRETRAINED, ft5.E4_NORMALIZERS["e4_s0"]
    d = ad.WORK / "checkpoints" / run
    return d / "best_model_state_dict.pt", d / "normalizer_stats.pt"


def cmd_predict(run: str, target: str, gpu: str = "0") -> dict:
    if target in REAL_TARGETS:
        if run != "zero_shot" and run not in frozen_runs():
            raise ad.LeakageError(
                f"{target} is hidden until {run} is listed in the frozen "
                f"{REGISTRY.relative_to(REPO_ROOT)}"
            )
        root = REAL_TARGETS[target]
    elif target in SYN_TARGETS:
        root = SYN_TARGETS[target]
    elif target in ("synthetic_test", "synthetic_val"):
        return _e5_cmd_predict(run, target, None, gpu)
    else:
        raise ValueError(f"unknown target {target}")
    n = pd.read_parquet(root / ad.NETWORK / "raw/bus_data.parquet", columns=["scenario"])[
        "scenario"
    ].nunique()
    ids = list(range(n))
    weights, stats = weights_of(run)
    split_dir = ad.WORK / "splits" / f"predict_{target}"
    split_dir.mkdir(parents=True, exist_ok=True)
    for nm, x in (("train", []), ("val", []), ("test", ids)):
        torch.save(torch.tensor(x, dtype=torch.long), split_dir / f"{nm}.pt")
    base_cfg = yaml.safe_load(ft5.RECIPE.read_text())
    conf = runner.write_config(
        base_cfg,
        ad.WORK / "configs" / f"predict_{run}__{target}.yaml",
        networks=[ad.NETWORK],
        scenarios=[n],
        split_by_load_scenario_idx=False,
        split_from_existing_files=str(split_dir),
        workers=4,
        test_ratio=1.0,
        val_ratio=0.0,
    )
    out = ad.WORK / "predictions" / run / target
    args = [
        "--config",
        str(conf),
        "--config_conversion",
        ft5.E4["graphkit"]["config_conversion"],
        "--data_path",
        str(root),
        "--model_path",
        str(weights),
        "--normalizer_stats",
        str(stats),
        "--log_dir",
        str(ad.WORK / "mlruns"),
        "--exp_name",
        "e5c_predict",
        "--run_name",
        f"{run}__{target}",
        "--output_path",
        str(out),
    ]
    res = runner.run_cli(
        "predict", args, ad.WORK / "logs" / f"predict_{run}__{target}.log", cuda=gpu
    )
    rec = {
        "run": run,
        "target": target,
        "n_scenarios": n,
        "normalizer": str(Path(stats).relative_to(REPO_ROOT)),
        "normalizer_sha256": ad.sha256_file(stats),
        "weights_sha256": ad.sha256_file(weights),
        "wall_s": res["wall_s"],
        "seconds_per_scenario": res["wall_s"] / max(n, 1),
        "output": str(out.relative_to(REPO_ROOT)),
        "environment": runner.environment(),
    }
    (OUT / "predict").mkdir(parents=True, exist_ok=True)
    (OUT / "predict" / f"{run}__{target}.json").write_text(json.dumps(rec, indent=2, default=str))
    print(f"predict {run} → {target}: {n} in {res['wall_s']:.1f} s", flush=True)
    return rec


_e5_cmd_predict = ft5.cmd_predict
ft5.cmd_predict = lambda run, target, normalizer=None, gpu="0": (
    _e5_cmd_predict(run, target, normalizer, gpu)
    if target in ("synthetic_test", "synthetic_val")
    else cmd_predict(run, target, gpu)
)


def cmd_ladder(gpus: list[str], only: list[str] | None) -> None:
    orig_train = ft5.cmd_train

    def train_and_score(n: int, s: int, init: str, gpu: str, rep: str = "SUNDON_ORIGINAL") -> dict:
        rec = orig_train(n, s, init, gpu, rep)
        for t in SYN_TARGETS:
            cmd_predict(ad.run_name(n, s, init), t, gpu=gpu)
        return rec

    ft5.cmd_train = train_and_score
    ft5.cmd_ladder(gpus, False, only)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["prepare", "train", "predict", "ladder"])
    ap.add_argument("--n", type=int)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--gpu", default="0")
    ap.add_argument("--gpus", nargs="*", default=["0", "1"])
    ap.add_argument("--run")
    ap.add_argument("--target")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.command == "prepare":
        ft5.cmd_prepare("SUNDON_ORIGINAL")
    elif a.command == "train":
        ft5.cmd_train(a.n, a.seed, "pretrained", a.gpu)
    elif a.command == "predict":
        cmd_predict(a.run, a.target, a.gpu)
    else:
        cmd_ladder(a.gpus, a.only)
    return 0


if __name__ == "__main__":
    sys.exit(main())

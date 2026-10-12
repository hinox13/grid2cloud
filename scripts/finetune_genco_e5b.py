"""E5b — GENCO topology adaptation on the broad envelope, with the E5 OFFICIAL workflow unchanged.

    uv run python scripts/finetune_genco_e5b.py prepare
    uv run python scripts/finetune_genco_e5b.py ladder [--gpus 0 1] [--scratch]
    uv run python scripts/finetune_genco_e5b.py predict --run RUN --target synthetic_test
    uv run python scripts/finetune_genco_e5b.py predict --run RUN --target e5_synthetic_test

This is scripts/finetune_genco_e5.py (unchanged code path: `gridfm_graphkit finetune`, the paper's
case118_N recipe, graphkit fit_on_train normalizer, best epoch by synthetic validation loss) bound
to the E5b dataset, pools, run names, outputs and registry. Real populations (S0/S1/S2/E4D) are
REFUSED until metadata/e5b_checkpoint_registry.yaml is frozen; afterwards only the runs it lists
may be scored on them (the selected checkpoint, plus the pre-registered post-freeze curve runs).

Outputs: data/interim/e5b/{checkpoints,predictions,splits,configs,mlruns}/ (gitignored);
reports/experiments/e5b/runs/<run>.json, predict/<run>__<target>.json, splits.json
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import torch
import yaml

from cloud2grid.genco import adaptation as ad5
from cloud2grid.genco import adaptation_e5b as ad
from cloud2grid.licensing.registry import REPO_ROOT

_spec = importlib.util.spec_from_file_location("ft5", REPO_ROOT / "scripts/finetune_genco_e5.py")
ft5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ft5)

OUT = REPO_ROOT / "reports/experiments/e5b"
REGISTRY = REPO_ROOT / "metadata/e5b_checkpoint_registry.yaml"
E5_REGISTRY = REPO_ROOT / "metadata/e5_checkpoint_registry.yaml"
REAL_TARGETS = set(ft5.WEATHER_FAMILIES)

# bind the E5 workflow to E5b (module globals are read at call time)
ft5.ad = ad
ft5.OUT = OUT
ft5.REGISTRY = REGISTRY
ft5.dataset_root = lambda rep="SUNDON_ORIGINAL": ad.ALLOWED_ROOT


def runs_spec() -> list[tuple[int, int, str]]:
    jobs = [
        (int(n), s, "pretrained") for n, seeds in ad.CFG["ladder"]["seeds"].items() for s in seeds
    ]
    return sorted(jobs, key=lambda j: (j[0], j[1]))


def scratch_spec() -> list[tuple[int, int, str]]:
    return [
        (int(n), s, "scratch")
        for n, seeds in ad.CFG["ladder"]["scratch_optional"].items()
        for s in seeds
    ]


ft5.runs_spec = runs_spec
ft5.scratch_spec = scratch_spec


def frozen_runs() -> set[str]:
    """Runs allowed on real populations: listed in the FROZEN E5b registry, hashes verified."""
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


def cmd_predict(run: str, target: str, normalizer: str | None = None, gpu: str = "0") -> dict:
    """E5b runs on E5b synthetic pools or E5's synthetic test; real targets only after freeze.
    E5 checkpoints (`ft_n*`) may be scored here on S1 only for the post-freeze curve."""
    if target in REAL_TARGETS and run != "zero_shot" and run not in frozen_runs():
        raise ad.LeakageError(
            f"{target} is hidden until {run} is listed in the frozen "
            f"{REGISTRY.relative_to(REPO_ROOT)}"
        )
    if run.startswith("ft_"):  # an E5 checkpoint (post-freeze diagnostic curve only)
        weights = ad5.WORK / "checkpoints" / run / "best_model_state_dict.pt"
        stats = ad5.WORK / "checkpoints" / run / "normalizer_stats.pt"
        if target == "synthetic_test":  # E5 model on the E5b held-out synthetic test
            man = ad.assert_synthetic_dataset(ad.ALLOWED_ROOT)
            return _predict(
                run,
                target,
                weights,
                stats,
                gpu,
                root=ad.ALLOWED_ROOT,
                ids=ad.pool_ids(man, "test").tolist(),
            )
        if target not in REAL_TARGETS:
            raise ValueError(f"unsupported target {target} for an E5 checkpoint")
        return _predict(run, target, weights, stats, gpu)
    if target == "e5_synthetic_test":
        man = ad5.assert_synthetic_dataset(ad5.ALLOWED_ROOT)
        ids = ad5.pool_ids(man, "test").tolist()
        if run == "zero_shot":
            weights, stats = ft5.PRETRAINED, ft5.E4_NORMALIZERS["e4_s0"]
        else:
            weights = ad.WORK / "checkpoints" / run / "best_model_state_dict.pt"
            stats = ad.WORK / "checkpoints" / run / "normalizer_stats.pt"
        return _predict(run, target, weights, stats, gpu, root=ad5.ALLOWED_ROOT, ids=ids)
    return ft5.cmd_predict(run, target, normalizer, gpu)


def _predict(
    run: str,
    target: str,
    weights: Path,
    stats: Path,
    gpu: str,
    root: Path | None = None,
    ids: list[int] | None = None,
) -> dict:
    """Same `gridfm_graphkit predict` call as E5, for E5 checkpoints / the E5 synthetic test."""
    import json

    from cloud2grid.genco import runner

    if root is None:
        root = ft5.E4_WORK / "datasets" / target
        n = pd.read_parquet(root / ad.NETWORK / "raw/bus_data.parquet", columns=["scenario"])[
            "scenario"
        ].nunique()
        ids = list(range(n))
    split_dir = ad.WORK / "splits" / f"predict_{target}"
    split_dir.mkdir(parents=True, exist_ok=True)
    for nm, x in (("train", []), ("val", []), ("test", ids)):
        torch.save(torch.tensor(x, dtype=torch.long), split_dir / f"{nm}.pt")
    base_cfg = yaml.safe_load(ft5.RECIPE.read_text())
    conf = runner.write_config(
        base_cfg,
        ad.WORK / "configs" / f"predict_{run}__{target}.yaml",
        networks=[ad.NETWORK],
        scenarios=[len(ids)],
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
        "e5b_predict",
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
        "n_scenarios": len(ids),
        "normalizer": str(stats.relative_to(REPO_ROOT)),
        "normalizer_sha256": ad.sha256_file(stats),
        "weights_sha256": ad.sha256_file(weights),
        "wall_s": res["wall_s"],
        "seconds_per_scenario": res["wall_s"] / max(len(ids), 1),
        "output": str(out.relative_to(REPO_ROOT)),
        "environment": runner.environment(),
    }
    (OUT / "predict").mkdir(parents=True, exist_ok=True)
    (OUT / "predict" / f"{run}__{target}.json").write_text(json.dumps(rec, indent=2, default=str))
    print(f"predict {run} → {target}: {len(ids)} in {res['wall_s']:.1f} s", flush=True)
    return rec


ft5.frozen_runs = frozen_runs
_e5_cmd_predict = ft5.cmd_predict
ft5.cmd_predict = lambda run, target, normalizer=None, gpu="0": (
    _e5_cmd_predict(run, target, normalizer, gpu)
    if target in ("synthetic_test", "synthetic_val") or target in REAL_TARGETS
    else cmd_predict(run, target, normalizer, gpu)
)


def cmd_ladder(gpus: list[str], include_scratch: bool, only: list[str] | None) -> None:
    """E5 ladder loop; each finished run is also scored on the E5 synthetic test (retention)."""
    orig_train = ft5.cmd_train

    def train_and_retain(n: int, s: int, init: str, gpu: str, rep: str = "SUNDON_ORIGINAL") -> dict:
        rec = orig_train(n, s, init, gpu, rep)
        cmd_predict(ad.run_name(n, s, init), "e5_synthetic_test", gpu=gpu)
        return rec

    ft5.cmd_train = train_and_retain
    ft5.cmd_ladder(gpus, include_scratch, only)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["prepare", "train", "predict", "ladder"])
    ap.add_argument("--n", type=int)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--init", choices=["pretrained", "scratch"], default="pretrained")
    ap.add_argument("--gpu", default="0")
    ap.add_argument("--gpus", nargs="*", default=["0", "1"])
    ap.add_argument("--run")
    ap.add_argument("--target")
    ap.add_argument("--normalizer", choices=list(ft5.E4_NORMALIZERS))
    ap.add_argument("--scratch", action="store_true")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.command == "prepare":
        ft5.cmd_prepare("SUNDON_ORIGINAL")
    elif a.command == "train":
        ft5.cmd_train(a.n, a.seed, a.init, a.gpu)
    elif a.command == "predict":
        cmd_predict(a.run, a.target, a.normalizer, a.gpu)
    else:
        cmd_ladder(a.gpus, a.scratch, a.only)
    return 0


if __name__ == "__main__":
    sys.exit(main())

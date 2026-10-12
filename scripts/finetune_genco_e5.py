"""E5 — topology-only adaptation of GENCO with the OFFICIAL graphkit workflow (synthetic only).

    uv run python scripts/finetune_genco_e5.py prepare                 # splits + isolation checks
    uv run python scripts/finetune_genco_e5.py ladder [--gpus 0 1]     # pre-registered ladder
    uv run python scripts/finetune_genco_e5.py train --n 1000 --seed 0 [--init scratch] [--gpu 0]
    uv run python scripts/finetune_genco_e5.py predict --run ft_n1000_s0 --target synthetic_test
    uv run python scripts/finetune_genco_e5.py predict --run zero_shot --target synthetic_test

Training = `gridfm_graphkit finetune` (pretrained transfer checkpoint) or `train` (scratch) with the
GENCO paper's transfer recipe (model repo finetune/case118_N/case118_N.yaml, unchanged apart from
the network, split files and seed; configs/experiments/e5_topology_adaptation.yaml). graphkit fits
the normalizer on the training split (fit_on_train) and keeps the best epoch by synthetic
validation loss. Every input is checked by cloud2grid.genco.adaptation (isolation rule).

`predict` on an E4 weather family is REFUSED unless the run is the frozen checkpoint in
metadata/e5_checkpoint_registry.yaml (or `zero_shot`, the E4 model) — weather stays hidden.

Outputs
    data/interim/e5/checkpoints/<run>/{best_model_state_dict.pt, normalizer_stats.pt}  (gitignored)
    data/interim/e5/predictions/<run>/<target>/                                         (gitignored)
    reports/experiments/e5/runs/<run>.json, predict/<run>__<target>.json, splits.json
"""

from __future__ import annotations

import argparse
import json
import queue
import shutil
import sys
import threading
from pathlib import Path

import pandas as pd
import torch
import yaml

from cloud2grid.genco import adaptation as ad
from cloud2grid.genco import runner
from cloud2grid.licensing.registry import REPO_ROOT

E4 = yaml.safe_load((REPO_ROOT / "configs/experiments/e4_zero_shot.yaml").read_text())
CKPT = REPO_ROOT / "data/raw/opengridfm/checkpoints/genco-pf-transfer"
PRETRAINED = CKPT / E4["model"]["weights"]
RECIPE = CKPT / "finetune/case118_1000/case118_1000.yaml"
E4_WORK = REPO_ROOT / "data/interim/e4"
E4_NORMALIZERS = {
    "e4_s0": E4_WORK / "normalizer/S0_normalizer_stats.pt",
    "e4_s1own": E4_WORK / "normalizer/S1_WEATHER_ALIGNED_normalizer_stats.pt",
}
OUT = REPO_ROOT / "reports/experiments/e5"
REGISTRY = REPO_ROOT / "metadata/e5_checkpoint_registry.yaml"
WEATHER_FAMILIES = {
    "S0_STANDARD_SYNTHETIC",  # E4 family: evaluated only after freezing, like the weather ones
    "S1_WEATHER_ALIGNED",
    "S1_WEATHER_ALIGNED_BASE_LTDS",
    "E4D_TIMELINE",
    *(f"S2_MATCHED_PV_CONTROL_s{s}" for s in range(101, 111)),
}
MERGED_TARGETS = {"S1_WEATHER_ALIGNED_MERGED", "synthetic_merged_test"}


def dataset_root(rep: str = "SUNDON_ORIGINAL") -> Path:
    return ad.WORK / ("synthetic" if rep == "SUNDON_ORIGINAL" else "synthetic_merged")


def runs_spec() -> list[tuple[int, int, str]]:
    lad = ad.CFG["ladder"]
    jobs = [(int(n), s, "pretrained") for n, seeds in lad["seeds"].items() for s in seeds]
    jobs.sort(key=lambda j: (j[0], j[1]))  # ascending: never start at 50k
    return jobs


def scratch_spec() -> list[tuple[int, int, str]]:
    return [
        (int(n), s, "scratch")
        for n, seeds in ad.CFG["ladder"]["scratch_secondary"]["runs"].items()
        for s in seeds
    ]


def split_ids(
    n: int, seed: int, rep: str = "SUNDON_ORIGINAL"
) -> tuple[list, list, list, pd.DataFrame]:
    man = ad.assert_synthetic_dataset(dataset_root(rep))
    train = ad.training_subset(ad.pool_ids(man, "train"), n, seed)
    val = ad.validation_subset(ad.pool_ids(man, "val"), n)
    test = ad.pool_ids(man, "test").tolist()
    ad.assert_split_ids(man, train, val, test)
    return train, val, test, man


def cmd_prepare(rep: str = "SUNDON_ORIGINAL") -> None:
    man = ad.assert_synthetic_dataset(dataset_root(rep))
    out = {
        "representation": rep,
        "pools": {p: int((man.pool == p).sum()) for p in ad.POOLS},
        "test_ids_sha256": ad.sha256_ids(ad.pool_ids(man, "test").tolist()),
        "val_pool_sha256": ad.sha256_ids(ad.pool_ids(man, "val").tolist()),
        "runs": {},
    }
    for n, s, init in runs_spec() + scratch_spec():
        tr, va, te, _ = split_ids(n, s, rep)
        out["runs"][ad.run_name(n, s, init, rep)] = {
            "n_train": len(tr),
            "n_val": len(va),
            "n_test": len(te),
            "train_sha256": ad.sha256_ids(tr),
            "val_sha256": ad.sha256_ids(va),
        }
    OUT.mkdir(parents=True, exist_ok=True)
    suffix = "" if rep == "SUNDON_ORIGINAL" else "_merged"
    (OUT / f"splits{suffix}.json").write_text(json.dumps(out, indent=2))
    print(json.dumps({k: v for k, v in out.items() if k != "runs"}, indent=1))


def graphkit_config(split_dir: Path, seed: int, name: str) -> Path:
    base = yaml.safe_load(RECIPE.read_text())
    base["seed"] = int(seed)
    return runner.write_config(
        base,
        ad.WORK / "configs" / f"{name}.yaml",
        networks=[ad.NETWORK],
        scenarios=[1],  # ignored by graphkit when split files are given
        split_by_load_scenario_idx=False,
        split_from_existing_files=str(split_dir),
        workers=8,
    )


def mlflow_run_dir(exp_root: Path, name: str) -> Path:
    runs = [
        t.parent.parent
        for t in exp_root.glob("*/*/tags/mlflow.runName")
        if t.read_text().strip() == name
    ]
    if not runs:
        raise FileNotFoundError(f"no mlflow run named {name}")
    return max(runs, key=lambda p: p.stat().st_mtime)


def read_metric(run_dir: Path, metric: str) -> pd.DataFrame:
    p = run_dir / "metrics" / metric
    return pd.read_csv(p, sep=" ", header=None, names=["ts", "value", "step"])


def cmd_train(n: int, seed: int, init: str, gpu: str, rep: str = "SUNDON_ORIGINAL") -> dict:
    name = ad.run_name(n, seed, init, rep)
    train, val, test, man = split_ids(n, seed, rep)
    split_dir = ad.WORK / "splits" / name
    hashes = ad.write_splits(split_dir, train, val, test)
    conf = graphkit_config(split_dir, seed, name)
    args = [
        "--config",
        str(conf),
        "--config_conversion",
        E4["graphkit"]["config_conversion"],
        "--data_path",
        str(dataset_root(rep)),
        "--log_dir",
        str(ad.WORK / "mlruns"),
        "--exp_name",
        "e5_adaptation",
        "--run_name",
        name,
    ]
    if init == "pretrained":
        args += ["--model_path", str(PRETRAINED)]
    cmd = "finetune" if init == "pretrained" else "train"
    run = runner.run_cli(cmd, args, ad.WORK / "logs" / f"{cmd}_{name}.log", cuda=gpu)
    rd = mlflow_run_dir(ad.WORK / "mlruns", name)
    dest = ad.WORK / "checkpoints" / name
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(rd / "artifacts/model/best_model_state_dict.pt", dest / "best_model_state_dict.pt")
    shutil.copy(rd / "artifacts/stats/normalizer_stats.pt", dest / "normalizer_stats.pt")
    # graphkit's own record of the splits it used must equal ours
    used = json.loads((rd / "artifacts/stats" / f"{ad.NETWORK}_scenario_splits.json").read_text())
    if sorted(used["train"]) != train or sorted(used["val"]) != val or sorted(used["test"]) != test:
        raise ad.LeakageError(f"{name}: graphkit used different splits than written")
    vl = read_metric(rd, "Validation loss")
    ep = read_metric(rd, "epoch")
    best_step = int(vl.loc[vl["value"].idxmin(), "step"])
    best_epoch = int(ep.loc[(ep["step"] - best_step).abs().idxmin(), "value"])
    rec = {
        "run": name,
        "n_train": n,
        "seed": seed,
        "init": init,
        "representation": rep,
        "command": cmd,
        "wall_s": run["wall_s"],
        "gpu_index": gpu,
        "epochs_run": int(ep["value"].max()) + 1,
        "best_epoch": best_epoch,
        "best_validation_loss": float(vl["value"].min()),
        "validation_loss_curve": vl["value"].round(6).tolist(),
        "split_sha256": hashes,
        "n_val": len(val),
        "n_test": len(test),
        "checkpoint": {
            "path": str((dest / "best_model_state_dict.pt").relative_to(REPO_ROOT)),
            "sha256": ad.sha256_file(dest / "best_model_state_dict.pt"),
        },
        "normalizer": ad.normalizer_summary(dest / "normalizer_stats.pt"),
        "normalizer_fitted_on": f"training split only ({len(train)} synthetic states)",
        "init_checkpoint": E4["model"] if init == "pretrained" else "random (graphkit train)",
        "recipe": str(RECIPE.relative_to(REPO_ROOT)),
        "graphkit_config": str(conf.relative_to(REPO_ROOT)),
        "mlflow_run": str(rd.relative_to(REPO_ROOT)),
        "log": run["log"],
        "environment": runner.environment(),
    }
    (OUT / "runs").mkdir(parents=True, exist_ok=True)
    (OUT / "runs" / f"{name}.json").write_text(json.dumps(rec, indent=2, default=str))
    print(
        f"{name}: {rec['wall_s'] / 60:.1f} min, best epoch {best_epoch}/{rec['epochs_run']}",
        flush=True,
    )
    return rec


def frozen_runs() -> set[str]:
    if not REGISTRY.exists():
        return set()
    reg = yaml.safe_load(REGISTRY.read_text())
    if not reg.get("frozen"):
        return set()
    ok = set()
    for r in reg.get("evaluable_on_weather", []):
        c = reg["checkpoints"][r]
        if ad.sha256_file(REPO_ROOT / c["checkpoint"]["path"]) != c["checkpoint"]["sha256"]:
            raise ad.LeakageError(f"{r}: weights changed after freezing")
        if ad.sha256_file(REPO_ROOT / c["normalizer"]["path"]) != c["normalizer"]["sha256"]:
            raise ad.LeakageError(f"{r}: normalizer changed after freezing")
        ok.add(r)
    return ok


def cmd_predict(run: str, target: str, normalizer: str | None = None, gpu: str = "0") -> dict:
    hidden = target in WEATHER_FAMILIES or target in MERGED_TARGETS - {"synthetic_merged_test"}
    if hidden and run != "zero_shot" and run not in frozen_runs():
        raise ad.LeakageError(
            f"{target} is hidden until {run} is frozen in {REGISTRY.relative_to(REPO_ROOT)}"
        )
    if run == "zero_shot":
        weights, stats = PRETRAINED, E4_NORMALIZERS["e4_s0"]
    else:
        weights = ad.WORK / "checkpoints" / run / "best_model_state_dict.pt"
        stats = ad.WORK / "checkpoints" / run / "normalizer_stats.pt"
    if normalizer:
        stats = E4_NORMALIZERS[normalizer]
    tag = f"{target}" + (f"__norm_{normalizer}" if normalizer else "")
    if target in ("synthetic_test", "synthetic_val", "synthetic_merged_test"):
        rep = (
            "SUNDON_MERGED_NEAR_ZERO_Z" if target == "synthetic_merged_test" else "SUNDON_ORIGINAL"
        )
        root = dataset_root(rep)
        man = ad.assert_synthetic_dataset(root)
        ids = ad.pool_ids(man, "val" if target == "synthetic_val" else "test").tolist()
    else:
        base = ad.WORK / "datasets" if target in MERGED_TARGETS else E4_WORK / "datasets"
        root = base / target
        n = pd.read_parquet(root / ad.NETWORK / "raw/bus_data.parquet", columns=["scenario"])[
            "scenario"
        ].nunique()
        ids = list(range(n))
    split_dir = ad.WORK / "splits" / f"predict_{target}"
    split_dir.mkdir(parents=True, exist_ok=True)
    for nm, x in (("train", []), ("val", []), ("test", ids)):
        torch.save(torch.tensor(x, dtype=torch.long), split_dir / f"{nm}.pt")
    base_cfg = yaml.safe_load(RECIPE.read_text())
    conf = runner.write_config(
        base_cfg,
        ad.WORK / "configs" / f"predict_{run}__{tag}.yaml",
        networks=[ad.NETWORK],
        scenarios=[len(ids)],
        split_by_load_scenario_idx=False,
        split_from_existing_files=str(split_dir),
        workers=4,
        test_ratio=1.0,
        val_ratio=0.0,
    )
    out = ad.WORK / "predictions" / run / tag
    args = [
        "--config",
        str(conf),
        "--config_conversion",
        E4["graphkit"]["config_conversion"],
        "--data_path",
        str(root),
        "--model_path",
        str(weights),
        "--normalizer_stats",
        str(stats),
        "--log_dir",
        str(ad.WORK / "mlruns"),
        "--exp_name",
        "e5_predict",
        "--run_name",
        f"{run}__{tag}",
        "--output_path",
        str(out),
    ]
    res = runner.run_cli("predict", args, ad.WORK / "logs" / f"predict_{run}__{tag}.log", cuda=gpu)
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
    (OUT / "predict" / f"{run}__{tag}.json").write_text(json.dumps(rec, indent=2, default=str))
    print(f"predict {run} → {tag}: {len(ids)} in {res['wall_s']:.1f} s", flush=True)
    return rec


def cmd_ladder(gpus: list[str], include_scratch: bool, only: list[str] | None) -> None:
    jobs = runs_spec() + (scratch_spec() if include_scratch else [])
    if only:
        jobs = [j for j in jobs if ad.run_name(*j) in only]
    jobs = [j for j in jobs if not (OUT / "runs" / f"{ad.run_name(*j)}.json").exists()]
    q: queue.Queue = queue.Queue()
    for j in jobs:
        q.put(j)
    errors: list[str] = []

    def worker(gpu: str) -> None:
        while True:
            try:
                n, s, init = q.get_nowait()
            except queue.Empty:
                return
            name = ad.run_name(n, s, init)
            try:
                cmd_train(n, s, init, gpu)
                for target in ("synthetic_test", "synthetic_val"):
                    cmd_predict(name, target, gpu=gpu)
            except Exception as e:  # noqa: BLE001 — reported, the ladder continues
                errors.append(f"{name}: {type(e).__name__}: {e}")
                print(errors[-1], flush=True)

    threads = [threading.Thread(target=worker, args=(g,)) for g in gpus]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print("ladder done; errors:", errors)
    if errors:
        raise SystemExit(1)


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
    ap.add_argument("--normalizer", choices=list(E4_NORMALIZERS))
    ap.add_argument("--scratch", action="store_true")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--representation", default="SUNDON_ORIGINAL")
    a = ap.parse_args()
    if a.command == "prepare":
        cmd_prepare(a.representation)
    elif a.command == "train":
        cmd_train(a.n, a.seed, a.init, a.gpu, a.representation)
    elif a.command == "predict":
        cmd_predict(a.run, a.target, a.normalizer, a.gpu)
    else:
        cmd_ladder(a.gpus, a.scratch, a.only)
    return 0


if __name__ == "__main__":
    sys.exit(main())

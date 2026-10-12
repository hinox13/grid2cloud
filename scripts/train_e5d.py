"""E5d — response-aware GENCO adaptation with the OFFICIAL graphkit CLI + plugin task.

    uv run python scripts/train_e5d.py prepare               # checks, pre-processing, splits.json
    uv run python scripts/train_e5d.py ladder --gpus 0 1 --per-gpu 3  # the six pre-registered runs
    uv run python scripts/train_e5d.py train --lam 1 --seed 0 [--gpu 0]
    uv run python scripts/train_e5d.py predict --run RUN --target TARGET [--gpu 0]

Training = `gridfm_graphkit finetune --plugins cloud2grid.genco.response_task` from the
genco-pf-transfer pretrained checkpoint with the E5 recipe (finetune/case118_1000, unchanged), the
E5c synthetic pool and the E5c n10000 split files of the same seed (hash-checked), plus the
`response:` section (λ, κ, Huber δ, 8 pairs per type, E5d train / validation pair sets).
Monitor = "Validation total loss" (best checkpoint, early stopping, LR plateau).

Prediction uses the UNCHANGED `PowerFlow` task (the plugin adds no parameter). Targets:
synthetic_test / synthetic_val (E5c pool), e5_test_ga / e5b_test_ga (re-encoded retention sets),
probes_validation / probes_test (E5c probes), pairs_train / pairs_validation / pairs_test (E5d)
and — ONLY for runs listed in the frozen metadata/e5d_checkpoint_registry.yaml —
S1_WEATHER_ALIGNED_GENAWARE. `--run` may also be zero_shot or a frozen E5c run (baseline).

Outputs: data/interim/e5d/{checkpoints,predictions,configs,logs,mlruns}/ (gitignored);
reports/experiments/e5d/{runs/<run>.json, predict/<run>__<target>.json, splits.json}
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import queue
import shutil
import sys
import threading
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import yaml

from cloud2grid.genco import adaptation_e5c as ad5c
from cloud2grid.genco import adaptation_e5d as ad
from cloud2grid.genco import runner
from cloud2grid.licensing.registry import REPO_ROOT
from cloud2grid.scenarios import response_pairs_e5d as rp

_spec = importlib.util.spec_from_file_location("ft5", REPO_ROOT / "scripts/finetune_genco_e5.py")
ft5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ft5)

OUT = REPO_ROOT / "reports/experiments/e5d"
REGISTRY = REPO_ROOT / "metadata/e5d_checkpoint_registry.yaml"
PLUGIN = "cloud2grid.genco.response_task"
MONITOR = "Validation total loss"
SYN_TARGETS = {
    "e5_test_ga": ad.E5C_WORK / "datasets/E5_TEST_GA",
    "e5b_test_ga": ad.E5C_WORK / "datasets/E5B_TEST_GA",
    "probes_validation": ad.E5C_WORK / "probes/validation",
    "probes_test": ad.E5C_WORK / "probes/test",
    **{f"pairs_{s}": ad.PAIR_ROOT[s] for s in ad.PAIR_SETS},
}
REAL_TARGETS = {"S1_WEATHER_ALIGNED_GENAWARE": ad.E5C_WORK / "datasets/S1_WEATHER_ALIGNED_GENAWARE"}


# ------------------------------------------------------------------ prepare
def base_hashes(root: Path) -> set[str]:
    """Base-state identities of an E5d pair set (member A = the base state)."""
    a = pd.read_parquet(root / "pairs.parquet").query("member == 'A'")
    cols = rp.injection_columns(a)
    if not cols:
        raise ValueError(f"no injection columns in {root}")
    return {rp.base_hash(r, cols) for _, r in a[cols].iterrows()}


def e5c_probe_base_hashes(name: str) -> set[str]:
    """E5c probe bases, regenerated with the E5c sampler and seed (its manifest has no
    injections); the regeneration is verified against the recorded probe x_mw."""
    from cloud2grid.scenarios import envelope_e5c as ev

    pc = ad5c.CFG["physics_probes"]
    seed = int(pc["seeds"][name])
    base = rp.base_states(int(pc["n_base_states"]), seed)
    regen = ev.probe_pairs(base, seed).query("member == 'A'").set_index("probe_id").x_mw
    man = pd.read_parquet(ad.E5C_WORK / "probes" / name / "probes.parquet")
    rec = man.query("member == 'A'").set_index("probe_id").x_mw
    if not np.allclose(regen.reindex(rec.index).to_numpy(), rec.to_numpy(), atol=1e-9):
        raise ValueError(f"E5c {name} probes could not be regenerated from their seed")
    cols = rp.injection_columns(base)
    return {rp.base_hash(r, cols) for _, r in base[cols].iterrows()}


def cmd_prepare() -> dict:
    from gridfm_graphkit.datasets.normalizers import HeteroDataMVANormalizer
    from gridfm_graphkit.datasets.powergrid_hetero_dataset import HeteroGridDatasetDisk
    from gridfm_graphkit.io.param_handler import NestedNamespace

    out: dict = {"e5c_splits": {}, "pair_sets": {}, "base_overlap": {}}
    for s in sorted({seed for _, seed, _ in ad.runs_spec()}):
        out["e5c_splits"][s] = ad.assert_e5c_splits(s)
    hashes = {}
    dummy = HeteroDataMVANormalizer(NestedNamespace(data={"baseMVA": 100}))
    for s in ad.PAIR_SETS:
        man = ad.assert_pair_set(ad.PAIR_ROOT[s])
        pairs = ad.complete_pairs(man)
        out["pair_sets"][s] = {
            "complete_pairs": pairs.probe_type.value_counts().to_dict(),
            "states": int(man.scenario.nunique()),
            "manifest_sha256": ad.sha256_file(ad.PAIR_ROOT[s] / "pairs.parquet"),
        }
        HeteroGridDatasetDisk(root=str(ad.PAIR_ROOT[s] / ad.NETWORK), data_normalizer=dummy)
        hashes[s] = base_hashes(ad.PAIR_ROOT[s])
    for s in ("validation", "test"):
        hashes[f"e5c_probes_{s}"] = e5c_probe_base_hashes(s)
    names = list(hashes)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            out["base_overlap"][f"{a}|{b}"] = len(hashes[a] & hashes[b])
    if any(out["base_overlap"].values()):
        raise ad.LeakageError(f"base states shared between sets: {out['base_overlap']}")
    out["n_base"] = {k: len(v) for k, v in hashes.items()}
    out.update(runner.git_commit())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "splits.json").write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps(out, indent=1, default=str))
    return out


# ------------------------------------------------------------------ train
def graphkit_config(lam: float, seed: int, name: str, split_dir: Path) -> Path:
    base = yaml.safe_load(ft5.RECIPE.read_text())
    base["seed"] = int(seed)
    base["task"]["task_name"] = "PowerFlowResponse"
    base["callbacks"].update(
        early_stopping_monitor=MONITOR, checkpoint_monitor=MONITOR, lr_scheduler_monitor=MONITOR
    )
    base["response"] = {
        "lam": float(lam),
        "kappa": ad.KAPPA,
        "huber_delta": ad.HUBER_DELTA,
        "pairs_per_type": ad.PAIRS_PER_TYPE,
        "train_pairs": str(ad.PAIR_ROOT["train"]),
        "val_pairs": str(ad.PAIR_ROOT["validation"]),
        "workers": 3,
    }
    return runner.write_config(
        base,
        ad.WORK / "configs" / f"{name}.yaml",
        networks=[ad.NETWORK],
        scenarios=[1],
        split_by_load_scenario_idx=False,
        split_from_existing_files=str(split_dir),
        workers=6,
    )


def cmd_train(lam: float, seed: int, gpu: str) -> dict:
    name = ad.run_name(lam, seed)
    hashes = ad.assert_e5c_splits(seed)
    for s in ("train", "validation"):
        ad.assert_pair_set(ad.PAIR_ROOT[s])
    ad5c.assert_synthetic_dataset(ad.ABS_ROOT)
    split_dir = ad.e5c_split_dir(seed)
    conf = graphkit_config(lam, seed, name, split_dir)
    args = [
        "--config", str(conf),
        "--config_conversion", ft5.E4["graphkit"]["config_conversion"],
        "--data_path", str(ad.ABS_ROOT),
        "--log_dir", str(ad.WORK / "mlruns"),
        "--exp_name", "e5d_response",
        "--run_name", name,
        "--model_path", str(ft5.PRETRAINED),
        "--plugins", PLUGIN,
    ]  # fmt: skip
    run = runner.run_cli("finetune", args, ad.WORK / "logs" / f"finetune_{name}.log", cuda=gpu)
    rd = ft5.mlflow_run_dir(ad.WORK / "mlruns", name)
    dest = ad.WORK / "checkpoints" / name
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(rd / "artifacts/model/best_model_state_dict.pt", dest / "best_model_state_dict.pt")
    shutil.copy(rd / "artifacts/stats/normalizer_stats.pt", dest / "normalizer_stats.pt")
    shutil.copy(rd / "artifacts/stats/response_sigma.json", dest / "response_sigma.json")
    used = json.loads((rd / "artifacts/stats" / f"{ad.NETWORK}_scenario_splits.json").read_text())
    got = {k: ad.sha256_ids(used[k]) for k in ("train", "val", "test")}
    if got != hashes:
        raise ad.LeakageError(f"{name}: graphkit used different splits than E5c n10000 s{seed}")
    vt = ft5.read_metric(rd, MONITOR)
    vl = ft5.read_metric(rd, "Validation loss")
    vr = ft5.read_metric(rd, "Validation response loss")
    ep = ft5.read_metric(rd, "epoch")
    best_step = int(vt.loc[vt["value"].idxmin(), "step"])
    best_epoch = int(ep.loc[(ep["step"] - best_step).abs().idxmin(), "value"])
    e5c_norm = ad.E5C_WORK / "checkpoints" / ad5c.run_name(ad.N_TRAIN, seed) / "normalizer_stats.pt"
    rec = {
        "run": name,
        "lambda": lam,
        "seed": seed,
        "role": next(r for la, s, r in ad.runs_spec() if la == lam and s == seed),
        "n_train": ad.N_TRAIN,
        "wall_s": run["wall_s"],
        "gpu_index": gpu,
        "epochs_run": int(ep["value"].max()) + 1,
        "best_epoch": best_epoch,
        "best_validation_total_loss": float(vt["value"].min()),
        "validation_loss_at_best": float(vl.loc[(vl["step"] - best_step).abs().idxmin(), "value"]),
        "validation_response_loss_at_best": float(
            vr.loc[(vr["step"] - best_step).abs().idxmin(), "value"]
        ),
        "validation_total_loss_curve": vt["value"].round(6).tolist(),
        "validation_response_loss_curve": vr["value"].round(6).tolist(),
        "split_sha256": got,
        "checkpoint": {
            "path": str((dest / "best_model_state_dict.pt").relative_to(REPO_ROOT)),
            "sha256": ad.sha256_file(dest / "best_model_state_dict.pt"),
        },
        "normalizer": ad5c.normalizer_summary(dest / "normalizer_stats.pt"),
        "normalizer_identical_to_e5c": ad.sha256_file(dest / "normalizer_stats.pt")
        == ad.sha256_file(e5c_norm),
        "normalizer_fitted_on": f"training split only ({ad.N_TRAIN} E5c synthetic states)",
        "response_sigma": json.loads((dest / "response_sigma.json").read_text()),
        "response_sigma_sha256": ad.sha256_file(dest / "response_sigma.json"),
        "init_checkpoint": ft5.E4["model"],
        "recipe": str(ft5.RECIPE.relative_to(REPO_ROOT)),
        "graphkit_config": str(conf.relative_to(REPO_ROOT)),
        "mlflow_run": str(rd.relative_to(REPO_ROOT)),
        "log": run["log"],
        "environment": runner.environment(),
    }
    (OUT / "runs").mkdir(parents=True, exist_ok=True)
    (OUT / "runs" / f"{name}.json").write_text(json.dumps(rec, indent=2, default=str))
    print(f"{name}: {rec['wall_s'] / 60:.1f} min, best epoch {best_epoch}/{rec['epochs_run']}")
    return rec


# ------------------------------------------------------------------ predict
def frozen_runs() -> set[str]:
    if not REGISTRY.exists():
        return set()
    reg = yaml.safe_load(REGISTRY.read_text())
    if not reg.get("frozen"):
        return set()
    ok = set()
    for r in reg.get("evaluable_on_real", []):
        c = reg["checkpoints"].get(r) or reg["post_freeze_runs"].get(r)
        for k in ("checkpoint", "normalizer"):
            if ad.sha256_file(REPO_ROOT / c[k]["path"]) != c[k]["sha256"]:
                raise ad.LeakageError(f"{r}: {k} changed after freezing")
        ok.add(r)
    return ok


def weights_of(run: str) -> tuple[Path, Path]:
    if run == "zero_shot":
        return ft5.PRETRAINED, ft5.E4_NORMALIZERS["e4_s0"]
    d = (ad.E5C_WORK if run.startswith("e5c_") else ad.WORK) / "checkpoints" / run
    return d / "best_model_state_dict.pt", d / "normalizer_stats.pt"


def cmd_predict(run: str, target: str, gpu: str = "0") -> dict:
    if target in REAL_TARGETS:
        if run.startswith("e5d_") and run not in frozen_runs():
            raise ad.LeakageError(f"{target} is hidden until {run} is frozen in {REGISTRY.name}")
        if not run.startswith("e5d_"):
            raise ValueError("real-state predictions of earlier models are E5c's (reused)")
        root = REAL_TARGETS[target]
        ids = None
    elif target in SYN_TARGETS:
        root = SYN_TARGETS[target]
        if target.startswith("pairs_"):
            ad.assert_pair_set(root)
        ids = None
    elif target in ("synthetic_test", "synthetic_val"):
        root = ad.ABS_ROOT
        man = ad5c.assert_synthetic_dataset(root)
        ids = ad5c.pool_ids(man, "val" if target == "synthetic_val" else "test").tolist()
    else:
        raise ValueError(f"unknown target {target}")
    if ids is None:
        n = pd.read_parquet(root / ad.NETWORK / "raw/bus_data.parquet", columns=["scenario"])
        ids = list(range(n["scenario"].nunique()))
    weights, stats = weights_of(run)
    split_dir = ad.WORK / "splits" / f"predict_{target}"
    split_dir.mkdir(parents=True, exist_ok=True)
    for nm, x in (("train", []), ("val", []), ("test", ids)):
        torch.save(torch.tensor(x, dtype=torch.long), split_dir / f"{nm}.pt")
    conf = runner.write_config(
        yaml.safe_load(ft5.RECIPE.read_text()),
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
        "--config", str(conf),
        "--config_conversion", ft5.E4["graphkit"]["config_conversion"],
        "--data_path", str(root),
        "--model_path", str(weights),
        "--normalizer_stats", str(stats),
        "--log_dir", str(ad.WORK / "mlruns"),
        "--exp_name", "e5d_predict",
        "--run_name", f"{run}__{target}",
        "--output_path", str(out),
    ]  # fmt: skip
    res = runner.run_cli("predict", args, ad.WORK / "logs" / f"predict_{run}__{target}.log", gpu)
    rec = {
        "run": run,
        "target": target,
        "n_scenarios": len(ids),
        "normalizer": str(Path(stats).relative_to(REPO_ROOT)),
        "normalizer_sha256": ad.sha256_file(stats),
        "weights_sha256": ad.sha256_file(weights),
        "wall_s": res["wall_s"],
        "output": str(out.relative_to(REPO_ROOT)),
        "environment": runner.environment(),
    }
    (OUT / "predict").mkdir(parents=True, exist_ok=True)
    (OUT / "predict" / f"{run}__{target}.json").write_text(json.dumps(rec, indent=2, default=str))
    print(f"predict {run} → {target}: {len(ids)} in {res['wall_s']:.1f} s", flush=True)
    return rec


SCORE_TARGETS = [
    "synthetic_test",
    "synthetic_val",
    "e5_test_ga",
    "e5b_test_ga",
    "pairs_validation",
    "pairs_test",
    "probes_validation",
    "probes_test",
]


def cmd_ladder(gpus: list[str], per_gpu: int, only: list[str] | None) -> None:
    jobs = [(lam, s) for lam, s, _ in ad.runs_spec()]
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
                lam, s = q.get_nowait()
            except queue.Empty:
                return
            name = ad.run_name(lam, s)
            try:
                cmd_train(lam, s, gpu)
                for t in SCORE_TARGETS:
                    cmd_predict(name, t, gpu)
            except Exception as e:  # noqa: BLE001 — reported, the ladder continues
                errors.append(f"{name}: {type(e).__name__}: {e}")
                print(errors[-1], flush=True)

    threads = [threading.Thread(target=worker, args=(g,)) for g in gpus for _ in range(per_gpu)]
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
    ap.add_argument("--lam", type=float)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--gpu", default="0")
    ap.add_argument("--gpus", nargs="*", default=["0", "1"])
    ap.add_argument("--per-gpu", type=int, default=3)
    ap.add_argument("--run")
    ap.add_argument("--target")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.command == "prepare":
        cmd_prepare()
    elif a.command == "train":
        cmd_train(a.lam, a.seed, a.gpu)
    elif a.command == "predict":
        cmd_predict(a.run, a.target, a.gpu)
    else:
        cmd_ladder(a.gpus, a.per_gpu, a.only)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# ruff: noqa: E501  (report lines kept on one line)
"""Independent verification of the frozen Cloud2Grid E5c and E5d models (release `cloud2grid-models-v1`).

    uv sync --extra genco
    uv run python reproduce/verify_models.py                 # CPU (default)
    uv run python reproduce/verify_models.py --device gpu    # optional CUDA GPU

Steps:
  1. locate the release assets in reproduce/.assets/ or download them (GitHub Release, or --base-url);
  2. check every asset's SHA256 against reproduce/assets.json, and the checkpoint / normaliser
     hashes against the frozen registries committed in this repository (metadata/);
  3. run GraphKit `predict` with each checkpoint and ITS OWN normaliser on the held-out synthetic
     verification data (E5d test pairs: 3,000 states; E5c test pool: 2,804 states);
  4. compute response and state metrics with reproduce/metrics.py;
  5. cross-check: (A) the metric code applied to the FROZEN predictions reproduces the published
     tables; (B) fresh predictions agree with the frozen ones; (C) fresh metrics agree with the
     published values;
  6. evaluate the pre-declared claims and write reproduce/output/ (report, JSON, CSV, figure).

Needs no credentials, no training data and no development directory. Exit code 0 only if every
check passes. Real-state (2024) results are NOT reproducible from this package (see report).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import metrics as M  # noqa: E402

NET = "sundon_33kv"
MODELS = {  # run -> (asset, registry, label)
    "e5c_ft_n10000_s2": ("cloud2grid-e5c-ft-n10000-s2.tar.gz", "metadata/e5c_checkpoint_registry.yaml", "E5c"),
    "e5d_l1_s0": ("cloud2grid-e5d-l1-s0.tar.gz", "metadata/e5d_checkpoint_registry.yaml", "E5d"),
}
DATA_ASSET = "cloud2grid-verification-synthetic-v1.tar.gz"
SETS = {"e5d_test_pairs": "pairs_test", "e5c_test": "synthetic_test"}  # verification set -> published table target
FAMILIES = ("import", "branch_P", "Vm", "Va")

# Tolerances (verification v2; see reproduce/README.md "Numerical reproducibility").
# The frozen predictions were made on a GPU, where GraphKit/PyG inference is NOT deterministic
# (most likely scatter-add reduction order; not isolated): two identical GPU runs differed by up to ~0.2 MW in decoded import and branch
# flow (mean ~0.03 MW), because flows over near-ideal branches amplify float32 angle rounding.
# CPU inference is bit-for-bit deterministic. Primary outputs (Vm, Va) agree to ~1e-5.
TOL_DEFINITION = 1e-6  # (A) relative: same predictions + same definitions must give the same numbers
TOL_PRED = {"Vm_pu": 1e-3, "Va_rad": 1e-3, "import_mean_mw": 0.1, "import_mw": 1.0, "branch_P_mw": 1.0}  # (B) |fresh − frozen|: max, except import_mean
TOL_METRIC_REL, TOL_METRIC_ABS = 0.01, {"rel_err": 0.01, "slope": 0.005, "mw": 0.05, "mva": 0.005, "pu": 1e-4, "share": 0.005, "ratio": 0.005}  # (C)
INFORMATIONAL = ("branch_Q",)  # reactive-flow responses: in no claim, dominated by numerical noise for PV pairs


# ------------------------------------------------------------------ assets
def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_assets(spec: dict, assets_dir: Path, base_url: str | None) -> dict[str, str]:
    assets_dir.mkdir(parents=True, exist_ok=True)
    res = {}
    for name, a in spec["assets"].items():
        p = assets_dir / name
        if not p.exists():
            url = (base_url or spec["download_base_url"]).rstrip("/") + "/" + name
            print(f"  downloading {url}", flush=True)
            tmp = p.with_suffix(p.suffix + ".part")
            with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:  # noqa: S310 (fixed https / user-given URL)
                shutil.copyfileobj(r, f)
            tmp.rename(p)
        got = sha256(p)
        res[name] = "PASS" if got == a["sha256"] else f"FAIL (got {got})"
        print(f"  {name}: sha256 {res[name]}", flush=True)
    return res


def extract(assets_dir: Path, work: Path, names: list[str]) -> None:
    for n in names:
        with tarfile.open(assets_dir / n) as tf:
            tf.extractall(work, filter="data")


# ------------------------------------------------------------------ inference
def predict(run: str, model_dir: Path, data_dir: Path, out: Path, work: Path, device: str) -> float:
    n = pd.read_parquet(data_dir / NET / "raw/bus_data.parquet", columns=["scenario"])["scenario"].nunique()
    split = work / "splits" / data_dir.name
    split.mkdir(parents=True, exist_ok=True)
    import torch

    for nm, ids in (("train", []), ("val", []), ("test", list(range(n)))):
        torch.save(torch.tensor(ids, dtype=torch.long), split / f"{nm}.pt")
    conf = work / "configs" / f"{run}__{data_dir.name}.yaml"
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text((model_dir / "graphkit_predict_config.yaml").read_text().replace("{N_SCENARIOS}", str(n)).replace("{SPLIT_DIR}", str(split)))
    env = {**os.environ, "MLFLOW_ALLOW_FILE_STORE": "true", "MLFLOW_DISABLE_AGENT_HINT": "1"}
    if device == "cpu":
        env["CUDA_VISIBLE_DEVICES"] = ""
    cmd = [sys.executable, "-m", "gridfm_graphkit", "predict", "--config", str(conf), "--config_conversion", "auto_inline",
           "--data_path", str(data_dir), "--model_path", str(model_dir / "best_model_state_dict.pt"),
           "--normalizer_stats", str(model_dir / "normalizer_stats.pt"), "--log_dir", str(work / "mlruns"),
           "--exp_name", "verify", "--run_name", f"{run}__{data_dir.name}", "--output_path", str(out)]  # fmt: skip
    log = work / "logs" / f"predict_{run}__{data_dir.name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    with open(log, "w") as fh:
        rc = subprocess.run(cmd, env=env, stdout=fh, stderr=subprocess.STDOUT, check=False).returncode
    if rc != 0:
        raise RuntimeError(f"gridfm_graphkit predict failed ({rc}); see {log}")
    return time.perf_counter() - t0


def load_pred(d: Path, fresh: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    if fresh:
        return pd.read_parquet(d / f"{NET}_predictions.parquet"), pd.read_parquet(d / f"{NET}_branch_predictions.parquet")
    return pd.read_parquet(d / "bus.parquet"), pd.read_parquet(d / "branch.parquet")


def pred_agreement(fb: pd.DataFrame, fbr: pd.DataFrame, zb: pd.DataFrame, zbr: pd.DataFrame) -> dict[str, float]:
    k = ["scenario", "bus"]
    b = fb.merge(zb, on=k, suffixes=("", "_z"))
    assert len(b) == len(zb) == len(fb), "fresh and frozen predictions cover different scenario × bus rows"
    ref = b[b["REF"] == 1]
    br_f = fbr.assign(k=fbr.groupby(["scenario", "from_bus", "to_bus"]).cumcount())
    br_z = zbr.assign(k=zbr.groupby(["scenario", "from_bus", "to_bus"]).cumcount())
    br = br_f.merge(br_z, on=["scenario", "from_bus", "to_bus", "k"], suffixes=("", "_z"))
    targets_identical = bool(np.allclose(b["Vm_target"], b["Vm_target_z"], atol=1e-6) and np.allclose(b["Pg_target"], b["Pg_target_z"], atol=1e-4))
    return {"import_mw": float((ref["Pg_pred"] - ref["Pg_pred_z"]).abs().max()), "Vm_pu": float((b["Vm_pred"] - b["Vm_pred_z"]).abs().max()),
            "Va_rad": float((b["Va_pred"] - b["Va_pred_z"]).abs().max()), "branch_P_mw": float((br["Pft"] - br["Pft_z"]).abs().max()),
            "import_mean_mw": float((ref["Pg_pred"] - ref["Pg_pred_z"]).abs().mean()),
            "ac_targets_identical": targets_identical}  # fmt: skip


# ------------------------------------------------------------------ comparison helpers
def published(root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    R = pd.read_csv(root / "reports/tables/e5d_response_probes.csv")
    S = pd.read_csv(root / "reports/tables/e5d_seed_results.csv").set_index("run")
    return R[R["target"] == "pairs_test"], S


def response_values(T: pd.DataFrame) -> dict[str, float]:
    a = T[T["magnitude_class"] == "all"].set_index(["probe_type", "family"])
    out = {}
    for k in M.TYPES:
        out[f"{k}.import.slope_ratio"] = float(a.loc[(k, "import"), "slope_ratio"])
        for f in (*FAMILIES, "branch_Q"):
            out[f"{k}.{f}.rel_err"] = float(a.loc[(k, f), "rel_err"])
    return out


STATIC_KEYS = {"PBE_mean": "mva", "P_residual": "mw", "V_error": "pu", "import_mae_mw": "mw", "import_bias_mw": "mw", "import_sign_accuracy_big": "share", "import_corr": "ratio"}


def within(calc: float, pub: float, kind: str) -> bool:
    return abs(calc - pub) <= max(TOL_METRIC_REL * abs(pub), TOL_METRIC_ABS[kind])


# ------------------------------------------------------------------ claims (pre-declared; thresholds = the pre-registered E5d gates)
def claims(v: dict) -> list[dict]:
    c, d = v["e5c_ft_n10000_s2"], v["e5d_l1_s0"]
    out = [
        {"id": "C1", "claim": "E5c is blind to PV: its import barely responds to a PV change", "criterion": "E5c pv import slope ratio < 0.1 and relative error > 0.9",
         "holds": c["pv.import.slope_ratio"] < 0.1 and c["pv.import.rel_err"] > 0.9},
        {"id": "C2", "claim": "E5d recovers the PV import response", "criterion": "E5d pv slope ratio in [0.8, 1.2] and relative error <= 0.25 (RS1, RS2)",
         "holds": 0.8 <= d["pv.import.slope_ratio"] <= 1.2 and d["pv.import.rel_err"] <= 0.25},
        {"id": "C3", "claim": "E5d reproduces the battery and load import responses", "criterion": "battery and load: slope ratio in [0.8, 1.2] and relative error <= 0.25",
         "holds": all(0.8 <= d[f"{k}.import.slope_ratio"] <= 1.2 and d[f"{k}.import.rel_err"] <= 0.25 for k in ("battery", "load"))},
        {"id": "C4", "claim": "E5d reproduces the distributed response (branch P, Vm, Va) for PV, battery and load", "criterion": "relative error <= 0.5 for all nine (RS3–RS5)",
         "holds": all(d[f"{k}.{f}.rel_err"] <= 0.5 for k in M.TYPES for f in ("branch_P", "Vm", "Va"))},
        {"id": "C5", "claim": "Both models keep an absolute import limitation on held-out synthetic states", "criterion": "import MAE > 5 MW (fails ST4) and sign accuracy on |AC| >= 5 MW < 0.99 (fails ST3), both models",
         "holds": all(x["import_mae_mw"] > 5 and x["import_sign_accuracy_big"] < 0.99 for x in (c, d))},
    ]  # fmt: skip
    return out


# ------------------------------------------------------------------ figure
def figure(deltas: dict, vals: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    col = {"E5c": "#2a78d6", "E5d": "#d97706", "ink": "#0f172a", "muted": "#5f6b84"}
    fig, axs = plt.subplots(1, 2, figsize=(14, 5.2), dpi=150, gridspec_kw={"width_ratios": [1, 1.6]})
    ax = axs[0]
    for run, (_, _, lab) in MODELS.items():
        g, a = deltas[run]
        ax.scatter(a, g, s=8, alpha=0.5, lw=0, color=col[lab], label=f"{lab} (slope ratio {vals[run]['pv.import.slope_ratio']:.3f})")
    lim = [min(a.min(), 0) - 0.2, max(a.max(), 0) + 0.2]
    ax.plot(lim, lim, color=col["ink"], lw=1, ls="--", label="AC (perfect response)")
    ax.set_xlabel("AC Δimport for a PV change (MW)")
    ax.set_ylabel("GENCO Δimport (MW)")
    ax.set_title("PV → import response, held-out test pairs", loc="left", fontweight="bold", fontsize=10.5)
    ax.legend(frameon=False, fontsize=8)
    ax = axs[1]
    labels = [f"{k}\n{f}" for k in M.TYPES for f in FAMILIES]
    x = np.arange(len(labels))
    for i, (run, (_, _, lab)) in enumerate(MODELS.items()):
        ax.bar(x + (i - 0.5) * 0.38, [vals[run][f"{k}.{f}.rel_err"] for k in M.TYPES for f in FAMILIES], width=0.38, color=col[lab], label=lab)
    ax.axhline(0.25, color=col["muted"], lw=1, ls="--")
    ax.axhline(0.5, color=col["muted"], lw=1, ls=":")
    ax.text(-0.45, 0.26, "import gate 0.25", ha="left", fontsize=7.5, color=col["muted"])
    ax.text(-0.45, 0.51, "distributed gate 0.5", ha="left", fontsize=7.5, color=col["muted"])
    ax.set_xticks(x, labels, fontsize=7.5)
    ax.set_ylabel("relative error Σ|Δpred − ΔAC| / Σ|ΔAC|")
    ax.set_title("Response error by input and quantity (0 = exact, 1 = no response)", loc="left", fontweight="bold", fontsize=10.5)
    ax.legend(frameon=False, fontsize=8)
    for a_ in axs:
        a_.spines[["top", "right"]].set_visible(False)
        a_.grid(color="#e7ecf3", lw=0.6)
        a_.set_axisbelow(True)
    fig.suptitle("Cloud2Grid frozen models: independent re-inference on held-out synthetic data", x=0.01, ha="left", fontweight="bold")
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--assets-dir", type=Path, default=HERE / ".assets")
    ap.add_argument("--base-url", default=None, help="override the GitHub Release download URL (e.g. a mirror)")
    ap.add_argument("--work-dir", type=Path, default=HERE / ".work")
    ap.add_argument("--out-dir", type=Path, default=HERE / "output")
    ap.add_argument("--device", choices=["cpu", "gpu"], default="cpu")
    a = ap.parse_args()
    t_start = time.perf_counter()
    spec = json.loads((HERE / "assets.json").read_text())
    rep: dict = {"release": spec["release"], "device": a.device, "checks": {}}
    print(f"[1/6] assets ({spec['release']})", flush=True)
    rep["checks"]["asset_sha256"] = fetch_assets(spec, a.assets_dir, a.base_url)
    if any(v != "PASS" for v in rep["checks"]["asset_sha256"].values()):
        print("asset hash mismatch: stopping", flush=True)
        return 2
    if a.work_dir.exists():
        shutil.rmtree(a.work_dir)
    a.work_dir.mkdir(parents=True)
    extract(a.assets_dir, a.work_dir, list(spec["assets"]))
    data = a.work_dir / "cloud2grid-verification-synthetic-v1"
    print("[2/6] package integrity and registry hashes", flush=True)
    integ = {}
    for run, (_, reg_path, lab) in MODELS.items():
        md = a.work_dir / run
        man = json.loads((md / "checkpoint_manifest.json").read_text())
        reg = yaml.safe_load((ROOT / reg_path).read_text())["checkpoints"][run]
        files_ok = all(sha256(md / f) == h for f, h in man["files_sha256"].items())
        integ[lab] = {"package_files": files_ok,
                      "checkpoint_matches_public_registry": sha256(md / "best_model_state_dict.pt") == reg["checkpoint"]["sha256"],
                      "normalizer_matches_public_registry": sha256(md / "normalizer_stats.pt") == reg["normalizer"]["sha256"]}  # fmt: skip
        import torch

        sd = torch.load(md / "best_model_state_dict.pt", map_location="cpu", weights_only=True)  # safe loader (no pickled code)
        integ[lab]["loads_with_weights_only"] = bool(len(sd) > 0)
        integ[lab]["n_parameters"] = int(sum(v.numel() for v in sd.values()))
    dman = json.loads((data / "MANIFEST.json").read_text())
    integ["verification_data_files"] = all(sha256(data / f) == h for f, h in dman["files_sha256"].items())
    rep["checks"]["integrity"] = integ
    print(json.dumps(integ, indent=1), flush=True)
    pairs = M.complete_pairs(pd.read_parquet(data / "e5d_test_pairs/pairs.parquet"))
    pubR, pubS = published(ROOT)
    print(f"[3/6] inference ({a.device}): 2 models × 2 held-out sets", flush=True)
    fresh, frozen, wall = {}, {}, {}
    for run in MODELS:
        for s in SETS:
            out = a.work_dir / "predictions" / run / s
            wall[f"{run}/{s}"] = round(predict(run, a.work_dir / run, data / s, out, a.work_dir, a.device), 1)
            fresh[(run, s)] = load_pred(out, True)
            frozen[(run, s)] = load_pred(data / "frozen_predictions" / run / s, False)
            print(f"  {run} on {s}: {wall[f'{run}/{s}']} s", flush=True)
    rep["inference_wall_s"] = wall
    print("[4/6] metrics and cross-checks", flush=True)
    A, B, C, vals, deltas = {}, {}, {}, {}, {}
    for run, (_, _, lab) in MODELS.items():
        pub_r = response_values(pubR[pubR["run"] == run])
        pub_s = pubS.loc[run]
        Tz = M.response_table(*frozen[(run, "e5d_test_pairs")], pairs)
        Tf = M.response_table(*fresh[(run, "e5d_test_pairs")], pairs)
        rz, rf = response_values(Tz), response_values(Tf)
        sz = M.static_metrics(*frozen[(run, "e5c_test")])
        sf = M.static_metrics(*fresh[(run, "e5c_test")])
        # (A) definitions: frozen predictions -> published numbers
        A[lab] = {"response_max_rel_diff": max(abs(rz[k] - pub_r[k]) / max(abs(pub_r[k]), 1e-12) for k in pub_r),
                  "static_max_rel_diff": max(abs(sz[k] - pub_s[k]) / max(abs(pub_s[k]), 1e-12) for k in STATIC_KEYS)}  # fmt: skip
        A[lab]["pass"] = A[lab]["response_max_rel_diff"] <= TOL_DEFINITION and A[lab]["static_max_rel_diff"] <= TOL_DEFINITION
        # (B) fresh vs frozen predictions
        B[lab] = {s: pred_agreement(*fresh[(run, s)], *frozen[(run, s)]) for s in SETS}
        B[lab]["pass"] = all(B[lab][s][k] <= TOL_PRED[k] for s in SETS for k in TOL_PRED) and all(B[lab][s]["ac_targets_identical"] for s in SETS)
        # (C) fresh metrics vs published
        rows = []
        for k, pv in pub_r.items():
            kind = "slope" if k.endswith("slope_ratio") else "rel_err"
            info = any(f".{f}." in k for f in INFORMATIONAL)
            rows.append({"model": lab, "set": "e5d_test_pairs", "metric": k, "published": pv, "frozen_recomputed": rz[k], "fresh_inference": rf[k],
                         "within_tolerance": None if info else within(rf[k], pv, kind)})  # fmt: skip
        for k, kind in STATIC_KEYS.items():
            rows.append({"model": lab, "set": "e5c_test", "metric": k, "published": float(pub_s[k]), "frozen_recomputed": sz[k], "fresh_inference": sf[k], "within_tolerance": within(sf[k], float(pub_s[k]), kind)})
        C[lab] = rows
        vals[run] = {**rf, **sf}
        sel = (pairs["probe_type"] == "pv").to_numpy()
        g, ac = M.pair_deltas(*fresh[(run, "e5d_test_pairs")], pairs)["import"]
        deltas[run] = (g[sel, 0], ac[sel, 0])
    table = pd.DataFrame([r for v in C.values() for r in v])
    rep["checks"]["A_definitions_reproduce_published_from_frozen_predictions"] = A
    rep["checks"]["B_fresh_vs_frozen_predictions"] = B
    scored = table[table["within_tolerance"].notna()]
    rep["checks"]["C_fresh_metrics_within_tolerance"] = {"n_scored": int(len(scored)), "n_within": int(scored["within_tolerance"].astype(bool).sum()),
                                                         "n_informational": int(table["within_tolerance"].isna().sum()), "pass": bool(scored["within_tolerance"].astype(bool).all())}  # fmt: skip
    rep["numerical_note"] = ("GPU inference is not bit-deterministic; CPU inference is. Small response errors (e.g. E5d PV import ~0.02–0.03) "
                             "include float32 noise in the decoded import; the published values were computed from one GPU run.")
    print("[5/6] claims", flush=True)
    cl = claims(vals)
    metric_ok = rep["checks"]["C_fresh_metrics_within_tolerance"]["pass"] and all(A[x]["pass"] and B[x]["pass"] for x in A)
    for c in cl:
        c["independently_reproduced"] = bool(c["holds"] and metric_ok)
    rep["claims"] = cl
    rep["not_reproducible_from_this_package"] = [
        "Real 2024 Sundon results (e.g. PV → import slope AC −1.02, E5c −0.04, E5d −1.07 MW/MW; E5d +13 MW import offset; E5D-D transfer verdict): "
        "they require the real operating states (UKPN measurements + satellite-derived PV), which are not in this release.",
        "Training: this package verifies inference of frozen checkpoints; it does not retrain them.",
    ]
    print("[6/6] outputs", flush=True)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(a.out_dir / "metric_comparison.csv", index=False)
    figure(deltas, vals, a.out_dir / "response_comparison.png")
    rep["all_checks_pass"] = bool(metric_ok and all(v == "PASS" for v in rep["checks"]["asset_sha256"].values())
                                  and all(all(v for k, v in integ[x].items() if k != "n_parameters") for x in ("E5c", "E5d")) and integ["verification_data_files"])  # fmt: skip
    rep["wall_s_total"] = round(time.perf_counter() - t_start, 1)
    (a.out_dir / "verification_results.json").write_text(json.dumps(rep, indent=2, default=str))
    lines = [f"# Cloud2Grid model verification ({spec['release']})", "",
             f"Device: {a.device}. All checks pass: **{rep['all_checks_pass']}**. Total time {rep['wall_s_total']} s.", "",
             "| Claim | Criterion | Holds on fresh inference | Independently reproduced |", "|---|---|---|---|"]  # fmt: skip
    lines += [f"| {c['id']} {c['claim']} | {c['criterion']} | {c['holds']} | **{c['independently_reproduced']}** |" for c in cl]
    lines += ["", "| Key metric | E5c published | E5c fresh | E5d published | E5d fresh |", "|---|---|---|---|---|"]
    key = ["pv.import.slope_ratio", "pv.import.rel_err", "pv.branch_P.rel_err", "pv.Vm.rel_err", "pv.Va.rel_err", "battery.import.slope_ratio", "load.import.slope_ratio", "import_mae_mw", "import_sign_accuracy_big", "PBE_mean"]
    t = table.set_index(["model", "metric"])
    lines += [f"| {k} | {t.loc[('E5c', k), 'published']:.4f} | {t.loc[('E5c', k), 'fresh_inference']:.4f} | {t.loc[('E5d', k), 'published']:.4f} | {t.loc[('E5d', k), 'fresh_inference']:.4f} |" for k in key]
    lines += ["", "**Not reproducible from this package:**"] + [f"- {x}" for x in rep["not_reproducible_from_this_package"]]
    (a.out_dir / "verification_report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines), flush=True)
    return 0 if rep["all_checks_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

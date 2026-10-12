"""E5c evaluation: synthetic static + physics-response gates, robustness-aware selection, freeze,
real transfer with PV response. Rules: configs/experiments/e5c_selection.yaml.

    uv run python scripts/evaluate_e5c.py synthetic    # synthetic only: gates, retention, selection
    uv run python scripts/evaluate_e5c.py freeze       # metadata/e5c_checkpoint_registry.yaml
    uv run --env-file .env python scripts/evaluate_e5c.py transfer   # only after freeze

Outputs: reports/tables/e5c_*.csv, reports/figures/e5c_*.png, reports/experiments/e5c/*.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from cloud2grid.evaluation import genco_metrics as gm  # noqa: E402
from cloud2grid.evaluation import transitions as tr  # noqa: E402
from cloud2grid.genco import adaptation_e5c as ad  # noqa: E402
from cloud2grid.genco import runner  # noqa: E402
from cloud2grid.licensing.registry import REPO_ROOT  # noqa: E402

_s = importlib.util.spec_from_file_location("ev5b", REPO_ROOT / "scripts/evaluate_e5b.py")
ev5b = importlib.util.module_from_spec(_s)
_s.loader.exec_module(ev5b)

SEL = ad.SEL
OUT = REPO_ROOT / "reports/experiments/e5c"
TABLES = REPO_ROOT / "reports/tables"
FIGS = REPO_ROOT / "reports/figures"
REGISTRY = REPO_ROOT / "metadata/e5c_checkpoint_registry.yaml"
E5B_REGISTRY = REPO_ROOT / "metadata/e5b_checkpoint_registry.yaml"
NET = ad.NETWORK
E4W = REPO_ROOT / "data/interim/e4"
SIGN_MW = 5.0
TARGET_ROOT = {
    "synthetic_test": ad.ALLOWED_ROOT,
    "synthetic_val": ad.ALLOWED_ROOT,
    "e5_test_ga": ad.WORK / "datasets/E5_TEST_GA",
    "e5b_test_ga": ad.WORK / "datasets/E5B_TEST_GA",
    "probes_validation": ad.WORK / "probes/validation",
    "probes_test": ad.WORK / "probes/test",
}


def pdir(run: str, target: str) -> Path:
    return ad.WORK / "predictions" / run / target


def ids_of(target: str, man: pd.DataFrame) -> list[int] | None:
    if target == "synthetic_test":
        return ad.pool_ids(man, "test").tolist()
    if target == "synthetic_val":
        return ad.pool_ids(man, "val").tolist()
    return None


def static_metrics(run: str, target: str, dc: pd.DataFrame, blocks: pd.Series | None) -> dict:
    d = pdir(run, target)
    bus = pd.read_parquet(d / f"{NET}_predictions.parquet")
    br = pd.read_parquet(d / f"{NET}_branch_predictions.parquet")
    m = gm.scenario_metrics(bus, br, None).merge(dc.reset_index(), on="scenario", how="left")
    m = m.merge(ad.ref_import(bus).reset_index(), on="scenario", how="left")
    m["block"] = blocks.reindex(m["scenario"]).to_numpy() if blocks is not None else m["scenario"]
    row = ev5b.summarise(m, bus)
    big = m["ac_import_mw"].abs() >= SIGN_MW
    row["import_sign_accuracy_big"] = float(
        (np.sign(m.loc[big, "ac_import_mw"]) == np.sign(m.loc[big, "genco_import_mw"])).mean()
    )
    row["share_near_zero_import"] = float((~big).mean())
    return row


def probe_metrics(run: str, target: str) -> dict:
    """AC-derived response metrics on paired probes (synthetic)."""
    man = pd.read_parquet(TARGET_ROOT[target] / "probes.parquet")
    man = man[man.complete]
    d = pdir(run, target)
    bus = pd.read_parquet(d / f"{NET}_predictions.parquet")
    br = pd.read_parquet(d / f"{NET}_branch_predictions.parquet")
    imp = ad.ref_import(bus)
    a = man[man.member == "A"].set_index("probe_id")
    b = man[man.member == "B"].set_index("probe_id")
    pairs = pd.DataFrame(
        {
            "scenario_i": a.scenario,
            "scenario_j": b.reindex(a.index).scenario,
            "probe_type": a.probe_type,
            "x_mw": a.x_mw,
        }
    ).reset_index()
    t = tr.transition_metrics(bus, br, pairs)
    t["dI_ac"] = (
        imp.loc[t.scenario_j, "ac_import_mw"].to_numpy()
        - imp.loc[t.scenario_i, "ac_import_mw"].to_numpy()
    )
    t["dI_pred"] = (
        imp.loc[t.scenario_j, "genco_import_mw"].to_numpy()
        - imp.loc[t.scenario_i, "genco_import_mw"].to_numpy()
    )
    out: dict[str, Any] = {}
    for kind, g in t.groupby("probe_type"):
        x = g.x_mw.to_numpy()
        s_ac = float((g.dI_ac * x).sum() / (x**2).sum())
        s_g = float((g.dI_pred * x).sum() / (x**2).sum())
        out.update(
            {
                f"{kind}_n_pairs": int(len(g)),
                f"{kind}_slope_ac": s_ac,
                f"{kind}_slope_genco": s_g,
                f"{kind}_slope_ratio": s_g / s_ac,
                f"{kind}_response_mae_mw": float((g.dI_pred - g.dI_ac).abs().mean()),
                f"{kind}_response_rel_mae": float(
                    (g.dI_pred - g.dI_ac).abs().mean() / g.dI_ac.abs().mean()
                ),
                f"{kind}_branch_dP_err_mw": float(g.dP_err_mean_abs.mean()),
                f"{kind}_branch_dP_ac_mw": float(g.dP_ac_mean_abs.mean()),
                f"{kind}_dVm_err_pu": float(g.dVm_err_mean_abs.mean()),
                f"{kind}_dVm_ac_pu": float(g.dVm_ac_mean_abs.mean()),
            }
        )
    return out


def gates_for(rec: dict, zs: dict) -> dict:
    g = {
        "ST1_pbe": rec["PBE_mean"] <= 0.10 * zs["PBE_mean"],
        "ST2_active_vs_dc": rec["P_residual"] <= 5.0 * rec["dc_P_residual"],
        "ST3_import_sign": rec["import_sign_accuracy_big"] >= 0.99,
        "ST4_import_mae": rec["import_mae_mw"] <= 5.0,
        "ST5_voltage": rec["V_error"] <= 0.015,
    }
    for k in ("pv", "battery", "load"):
        g[f"RS1_slope_{k}"] = 0.8 <= rec.get(f"val_{k}_slope_ratio", np.nan) <= 1.2
        g[f"RS2_mae_{k}"] = rec.get(f"val_{k}_response_rel_mae", np.inf) <= 0.25
    g["RT1_e5_narrow"] = rec.get("e5_test_ga_PBE_mean", np.inf) <= 2.0 * 1.2697
    g["RT2_e5b_broad"] = rec.get("e5b_test_ga_PBE_mean", np.inf) <= 2.0 * 0.5864
    g["static_pass"] = all(g[k] for k in g if k.startswith("ST"))
    g["response_pass"] = all(g[k] for k in g if k.startswith("RS"))
    g["retention_pass"] = g["RT1_e5_narrow"] and g["RT2_e5b_broad"]
    g["eligible"] = g["static_pass"] and g["response_pass"] and g["retention_pass"]
    g["n_criteria_passed"] = int(sum(bool(v) for k, v in g.items() if k[:2] in ("ST", "RS", "RT")))
    return g


# ------------------------------------------------------------------ synthetic
def cmd_synthetic() -> dict:
    man = ad.assert_synthetic_dataset(ad.ALLOWED_ROOT)
    blocks = man.set_index("scenario")["load_block"]
    dcs = {}
    for t in ("synthetic_test", "synthetic_val", "e5_test_ga", "e5b_test_ga"):
        ids = ids_of(t, man)
        root = TARGET_ROOT[t]
        dcs[t] = gm.dc_baseline_frames(
            ev5b.read_raw(root, ids), ev5b.read_raw(root, ids, table="branch_data")
        )
    runs = [{"run": "zero_shot", "n_train": 0, "seed": None}]
    runs += [json.loads(p.read_text()) for p in sorted((OUT / "runs").glob("e5c_*.json"))]
    rows = []
    for r in runs:
        rec: dict[str, Any] = {"run": r["run"], "n_train": r["n_train"], "seed": r["seed"]}
        if not (pdir(r["run"], "synthetic_test") / f"{NET}_predictions.parquet").exists():
            continue
        rec.update(static_metrics(r["run"], "synthetic_test", dcs["synthetic_test"], blocks))
        for t in ("synthetic_val", "e5_test_ga", "e5b_test_ga"):
            if (pdir(r["run"], t) / f"{NET}_predictions.parquet").exists():
                s = static_metrics(r["run"], t, dcs[t], blocks if t == "synthetic_val" else None)
                for k in ("PBE_mean", "P_residual", "V_error", "branch_P_error", "import_mae_mw"):
                    rec[f"{t}_{k}"] = s[k]
        for t, pre in (("probes_validation", "val"), ("probes_test", "test")):
            if (pdir(r["run"], t) / f"{NET}_predictions.parquet").exists():
                rec.update({f"{pre}_{k}": v for k, v in probe_metrics(r["run"], t).items()})
        for k in ("wall_s", "best_epoch", "epochs_run", "best_validation_loss"):
            rec[k] = r.get(k)
        rec["normalizer_baseMVA"] = (r.get("normalizer") or {}).get("baseMVA")
        rec["checkpoint_sha256"] = (r.get("checkpoint") or {}).get("sha256")
        rec["normalizer_sha256"] = (r.get("normalizer") or {}).get("sha256")
        rows.append(rec)
    S = pd.DataFrame(rows)
    zs = S[S.run == "zero_shot"].iloc[0].to_dict()
    G = pd.DataFrame(
        [
            {"run": r["run"], **(gates_for(r, zs) if r["run"] != "zero_shot" else {})}
            for r in S.to_dict("records")
        ]
    )
    S = S.merge(G, on="run", how="left")
    S.to_csv(TABLES / "e5c_synthetic_robustness.csv", index=False)
    probe_cols = [
        c
        for c in S
        if c.startswith(("val_", "test_"))
        and ("slope" in c or "mae" in c or "err" in c or "_ac" in c)
    ]
    S[["run", "n_train", "seed", *probe_cols]].to_csv(
        TABLES / "e5c_physics_probe_results.csv", index=False
    )
    # learning curve over seeds
    lc = []
    metrics = [
        "PBE_mean",
        "P_residual",
        "branch_P_error",
        "V_error",
        "angle_error",
        "import_mae_mw",
        "synthetic_val_PBE_mean",
        "e5_test_ga_PBE_mean",
        "e5b_test_ga_PBE_mean",
        "test_pv_slope_ratio",
        "test_battery_slope_ratio",
        "test_load_slope_ratio",
        "test_pv_response_rel_mae",
        "wall_s",
    ]
    for n, g in S.groupby("n_train"):
        row = {"n_train": int(n), "seeds": int(len(g))}
        for c in metrics:
            if c in g and g[c].notna().any():
                row[c], row[f"{c}_min"], row[f"{c}_max"] = (
                    float(g[c].mean()),
                    float(g[c].min()),
                    float(g[c].max()),
                )
        row["dc_P_residual"] = float(g["dc_P_residual"].mean())
        lc.append(row)
    LC = pd.DataFrame(lc)
    LC.to_csv(TABLES / "e5c_learning_curve.csv", index=False)
    sel, flagged, why = select(S)
    res = {
        "zero_shot_on_e5c_test": {k: zs[k] for k in ("PBE_mean", "P_residual", "dc_P_residual")},
        "eligible_runs": S.loc[S.eligible.fillna(False).astype(bool), "run"].tolist(),
        "selected": sel,
        "selected_flagged": flagged,
        "selection_trace": why,
        **runner.git_commit(),
    }
    (OUT / "synthetic_evaluation.json").write_text(json.dumps(res, indent=2, default=str))
    figure(LC)
    cols = [
        "run",
        "PBE_mean",
        "P_residual",
        "import_mae_mw",
        "import_sign_accuracy_big",
        "val_pv_slope_ratio",
        "val_battery_slope_ratio",
        "val_load_slope_ratio",
        "e5_test_ga_PBE_mean",
        "e5b_test_ga_PBE_mean",
        "synthetic_val_PBE_mean",
        "n_criteria_passed",
        "eligible",
    ]
    print(S[[c for c in cols if c in S]].round(4).to_string(index=False))
    print(
        json.dumps({k: res[k] for k in ("eligible_runs", "selected", "selected_flagged")}, indent=1)
    )
    return res


def select(S: pd.DataFrame) -> tuple[str | None, bool, dict]:
    """Pre-registered hierarchical rule (e5c_selection.yaml checkpoint_selection)."""
    ft = S[S.run.str.startswith("e5c_ft_")].copy()
    if ft.empty:
        return None, False, {}
    cv = ft.groupby("n_train")["synthetic_val_PBE_mean"].agg(
        lambda x: float(x.std(ddof=1) / x.mean()) if len(x) > 1 else np.inf
    )
    ft["size_cv"] = ft.n_train.map(cv)
    elig = ft[ft.eligible.fillna(False).astype(bool)]
    if len(elig):
        best = elig.synthetic_val_PBE_mean.min()
        tie = elig[elig.synthetic_val_PBE_mean <= 1.10 * best].sort_values(
            ["size_cv", "n_train", "synthetic_val_PBE_mean"]
        )
        return (
            tie.iloc[0].run,
            False,
            {"eligible": elig.run.tolist(), "best_val_pbe": best, "tie_set": tie.run.tolist()},
        )
    ranked = ft.sort_values(
        ["n_criteria_passed", "synthetic_val_PBE_mean"], ascending=[False, True]
    )
    return ranked.iloc[0].run, True, {"eligible": [], "fallback_rank": ranked.run.tolist()[:6]}


def figure(LC: pd.DataFrame) -> None:
    g = LC[LC.n_train > 0]
    fig, ax = plt.subplots(1, 3, figsize=(15, 3.8))
    for c, lab in (
        ("PBE_mean", "E5c test"),
        ("e5_test_ga_PBE_mean", "E5 narrow test"),
        ("e5b_test_ga_PBE_mean", "E5b broad test"),
    ):
        ax[0].errorbar(
            g.n_train,
            g[c],
            yerr=[g[c] - g[f"{c}_min"], g[f"{c}_max"] - g[c]],
            fmt="o-",
            capsize=3,
            label=lab,
        )
    ax[0].set_title("PBE (MVA) on synthetic test sets", fontsize=9)
    for c, lab in (
        ("test_pv_slope_ratio", "PV"),
        ("test_battery_slope_ratio", "battery"),
        ("test_load_slope_ratio", "load"),
    ):
        if c in g:
            ax[1].errorbar(
                g.n_train,
                g[c],
                yerr=[g[c] - g[f"{c}_min"], g[f"{c}_max"] - g[c]],
                fmt="o-",
                capsize=3,
                label=lab,
            )
    ax[1].axhspan(0.8, 1.2, color="green", alpha=0.1, label="gate band")
    ax[1].set_title("Response slope ratio GENCO / AC (test probes)", fontsize=9)
    ax[2].errorbar(g.n_train, g["P_residual"], fmt="o-", label="GENCO active residual")
    ax[2].axhline(g["dc_P_residual"].mean(), color="grey", ls=":", label="DC-PF")
    ax[2].set_title("Active residual (MW), E5c test", fontsize=9)
    for a in ax:
        a.set_xscale("log")
        a.set_xlabel("synthetic training states")
        a.legend(fontsize=7)
    ax[0].set_yscale("log")
    ax[2].set_yscale("log")
    fig.tight_layout()
    fig.savefig(FIGS / "e5c_learning_curve.png", dpi=120)
    plt.close(fig)


# ------------------------------------------------------------------ freeze
def cmd_freeze() -> None:
    res = json.loads((OUT / "synthetic_evaluation.json").read_text())
    sel = res["selected"]
    rec = json.loads((OUT / "runs" / f"{sel}.json").read_text())
    S = pd.read_csv(TABLES / "e5c_synthetic_robustness.csv").set_index("run")
    curve = {}
    for p in sorted((OUT / "runs").glob("e5c_ft_*.json")):
        r = json.loads(p.read_text())
        curve[r["run"]] = {
            "checkpoint": r["checkpoint"],
            "normalizer": {k: r["normalizer"][k] for k in ("path", "sha256", "baseMVA")},
        }
    import hashlib

    def h(p: str) -> str:
        return hashlib.sha256((REPO_ROOT / p).read_bytes()).hexdigest()

    reg = {
        "schema": "cloud2grid E5c checkpoint registry v1",
        "frozen": True,
        "frozen_before_real_state_evaluation": True,
        "selection_rule": SEL["checkpoint_selection"],
        "selected": sel,
        "selected_flagged": res["selected_flagged"],
        "selection_trace": res["selection_trace"],
        "evaluable_on_real": [sel, *[r for r in curve if r != sel]],
        "checkpoints": {
            sel: {
                "n_train": rec["n_train"],
                "seed": rec["seed"],
                "checkpoint": rec["checkpoint"],
                "normalizer": rec["normalizer"],
                "normalizer_fitted_on": rec["normalizer_fitted_on"],
                "training_split_sha256": rec["split_sha256"],
                "best_epoch": rec["best_epoch"],
                "epochs_run": rec["epochs_run"],
                "graphkit_config": rec["graphkit_config"],
                "mlflow_run": rec["mlflow_run"],
                "synthetic_evidence": {
                    k: (
                        None
                        if pd.isna(S.at[sel, k])
                        else (
                            bool(S.at[sel, k])
                            if isinstance(S.at[sel, k], (bool, np.bool_))
                            else float(S.at[sel, k])
                        )
                    )
                    for k in (
                        "PBE_mean",
                        "P_residual",
                        "synthetic_val_PBE_mean",
                        "e5_test_ga_PBE_mean",
                        "e5b_test_ga_PBE_mean",
                        "val_pv_slope_ratio",
                        "val_battery_slope_ratio",
                        "val_load_slope_ratio",
                        "n_criteria_passed",
                        "eligible",
                    )
                },
            }
        },
        "post_freeze_curve_runs": curve,
        "config_sha256": {
            p: h(p)
            for p in (
                "configs/experiments/e5c_generator_aware.yaml",
                "configs/experiments/e5c_selection.yaml",
            )
        },
        "selection_table_sha256": h("reports/tables/e5c_synthetic_robustness.csv"),
        **runner.git_commit(),
    }
    REGISTRY.write_text(yaml.safe_dump(reg, sort_keys=False, allow_unicode=True))
    print(yaml.safe_dump(reg["checkpoints"], sort_keys=False))


def frozen() -> dict:
    if not REGISTRY.exists() or not yaml.safe_load(REGISTRY.read_text()).get("frozen"):
        raise SystemExit("E5c registry not frozen: real states stay hidden")
    reg = yaml.safe_load(REGISTRY.read_text())
    c = reg["checkpoints"][reg["selected"]]
    for k in ("checkpoint", "normalizer"):
        if ad.sha256_file(REPO_ROOT / c[k]["path"]) != c[k]["sha256"]:
            raise SystemExit(f"{k} changed after freezing")
    return reg


# ------------------------------------------------------------------ real transfer
def real_frame(
    pred: Path, root: Path, fam: str = "S1_WEATHER_ALIGNED"
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    gates = pd.read_parquet(REPO_ROOT / "reports/experiments/e4/families" / f"{fam}_gates.parquet")
    bus = pd.read_parquet(pred / f"{NET}_predictions.parquet")
    br = pd.read_parquet(pred / f"{NET}_branch_predictions.parquet")
    ratings = pd.read_parquet(root / NET / "branch_ratings.parquet")
    m = gm.scenario_metrics(bus, br, ratings)
    m = m.merge(gm.dc_baseline(root / NET / "raw").reset_index(), on="scenario")
    m = m.merge(ad.ref_import(bus).reset_index(), on="scenario", how="left")
    acc = gates[gates["rejected"].isna()].copy()
    acc["scenario"] = acc["scenario"].astype(int)
    m = m.merge(acc, on="scenario", how="left")
    m["block"] = pd.to_datetime(m["slot"], utc=True).dt.strftime("%Y-%m-%d")
    m["scenario_id"] = fam + ":" + m["scenario"].astype(str)
    return m, bus, br


def branch_pv_slopes(br: pd.DataFrame, feats: pd.DataFrame) -> pd.DataFrame:
    """Per directed branch: OLS PV coefficient of P_ft (with load, CHAP31), AC vs model."""
    x = feats
    load = x[[f"Pd {n}" for n in ev5b.LOAD_NODES]].sum(axis=1)
    rows = []
    for (f, t), g in br.groupby(["from_bus", "to_bus"]):
        g = g.groupby("scenario")[["Pft", "Pft_target"]].sum()
        xx = x.reindex(g.index)
        X = np.column_stack(
            [np.ones(len(g)), load.reindex(g.index), xx[f"Pd {ev5b.BATT}"], xx["pv_injection_mw"]]
        )
        ok = np.isfinite(X).all(1)
        b_ac = np.linalg.lstsq(X[ok], g.Pft_target.to_numpy()[ok], rcond=None)[0][3]
        b_g = np.linalg.lstsq(X[ok], g.Pft.to_numpy()[ok], rcond=None)[0][3]
        rows.append({"from_bus": f, "to_bus": t, "pv_slope_ac": b_ac, "pv_slope_model": b_g})
    return pd.DataFrame(rows)


def cmd_transfer() -> None:
    reg = frozen()
    sel = reg["selected"]
    feats = ev5b.state_features(E4W / "datasets/S1_WEATHER_ALIGNED")
    e5b_sel = yaml.safe_load(E5B_REGISTRY.read_text())["selected"]
    models = {
        "zero-shot (E4)": (
            ev5b.pred_dir("zero_shot", "S1_WEATHER_ALIGNED"),
            E4W / "datasets/S1_WEATHER_ALIGNED",
        ),
        "E5": (
            ev5b.pred_dir(ev5b.e5_selected(), "S1_WEATHER_ALIGNED"),
            E4W / "datasets/S1_WEATHER_ALIGNED",
        ),
        "E5b": (ev5b.pred_dir(e5b_sel, "S1_WEATHER_ALIGNED"), E4W / "datasets/S1_WEATHER_ALIGNED"),
        "E5c": (
            pdir(sel, "S1_WEATHER_ALIGNED_GENAWARE"),
            ad.WORK / "datasets/S1_WEATHER_ALIGNED_GENAWARE",
        ),
    }
    rows, frames, bsl = [], {}, []
    for lab, (pd_, root) in models.items():
        m, bus, br = real_frame(pd_, root)
        frames[lab] = m
        r = {"model": lab, **ev5b.summarise(m, bus), **ev5b.import_sensitivity(m, feats)}
        big = m.ac_import_mw.abs() >= SIGN_MW
        r["import_sign_accuracy_big"] = float(
            (np.sign(m.ac_import_mw[big]) == np.sign(m.genco_import_mw[big])).mean()
        )
        b = branch_pv_slopes(br, feats).assign(model=lab)
        r["branch_pv_slope_median_abs_err"] = float(
            (b.pv_slope_model - b.pv_slope_ac).abs().median()
        )
        bsl.append(b)
        rows.append(r)
    T = pd.DataFrame(rows)
    T.to_csv(TABLES / "e5c_real_transfer.csv", index=False)
    pd.concat(bsl).to_csv(TABLES / "e5c_branch_pv_slopes.csv", index=False)
    imp = T[
        [
            "model",
            "import_sign_accuracy",
            "import_sign_accuracy_big",
            "import_mae_mw",
            "import_bias_mw",
            "import_corr",
            "import_sd_pred_mw",
            "import_sd_ac_mw",
            "import_dynamic_range",
            "ac_slope_load",
            "genco_slope_load",
            "ac_slope_chap31",
            "genco_slope_chap31",
            "ac_slope_pv",
            "genco_slope_pv",
        ]
    ]
    imp.to_csv(TABLES / "e5c_import_diagnostic.csv", index=False)
    pv = T[["model", "ac_slope_pv", "genco_slope_pv", "branch_pv_slope_median_abs_err"]].copy()
    pv["pv_slope_ratio"] = pv.genco_slope_pv / pv.ac_slope_pv
    pv.to_csv(TABLES / "e5c_pv_response.csv", index=False)
    c = T.set_index("model").loc["E5c"]
    b5 = T.set_index("model").loc["E5b"]
    crit = {
        "R1_active": c.P_residual <= 2.885,
        "R2_pbe": (c.PBE_mean <= 3.318) and (c.PBE_q95 <= 10.0),
        "R3_import": (c.import_sign_accuracy_big >= 0.99)
        and (c.import_mae_mw <= 5.0)
        and (c.import_corr >= 0.9)
        and (0.75 <= c.import_sd_pred_mw / c.import_sd_ac_mw <= 1.33),
        "R4_voltage": (c.vm_tracking_median_r >= 0.8) and (c.V_error <= 0.01),
        "R5_pv_response": 0.8 <= c.genco_slope_pv / c.ac_slope_pv <= 1.2,
    }
    success = all(bool(v) for v in crit.values())
    pv_gap_e5c = abs(c.genco_slope_pv - c.ac_slope_pv)
    pv_gap_e5b = abs(b5.genco_slope_pv - c.ac_slope_pv)
    if success:
        verdict = "E5C-A_REAL_TRANSFER_SUCCESSFUL"
    elif (not crit["R5_pv_response"]) and pv_gap_e5c > 0.5 * pv_gap_e5b:
        verdict = "E5C-B_GENERATOR_AWARE_SYNTHETIC_ADAPTATION_STILL_INSUFFICIENT"
    else:
        verdict = "E5C-C_PARTIAL_OR_INCONCLUSIVE"
    res = {
        "selected": sel,
        "criteria": {k: bool(v) for k, v in crit.items()},
        "REAL_TRANSFER_SUCCESS": success,
        "pv_slope_gap": {"E5c": pv_gap_e5c, "E5b": pv_gap_e5b},
        "verdict": verdict,
        "selected_flagged": reg["selected_flagged"],
        "environment": runner.environment(),
    }
    (OUT / "real_transfer.json").write_text(json.dumps(res, indent=2, default=str))
    cols = [
        "model",
        "PBE_mean",
        "PBE_q50",
        "PBE_q95",
        "PBE_max",
        "P_residual",
        "Q_residual",
        "V_error",
        "angle_error",
        "branch_P_error",
        "branch_Q_error",
        "vm_tracking_median_r",
        "import_mae_mw",
        "import_corr",
        "genco_slope_pv",
        "ac_slope_pv",
    ]
    print(T[cols].round(4).to_string(index=False))
    print(
        json.dumps(
            {k: res[k] for k in ("criteria", "verdict", "pv_slope_gap")}, indent=1, default=str
        )
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["synthetic", "freeze", "transfer"])
    a = ap.parse_args()
    for d in (TABLES, FIGS, OUT):
        d.mkdir(parents=True, exist_ok=True)
    {"synthetic": cmd_synthetic, "freeze": cmd_freeze, "transfer": cmd_transfer}[a.command]()
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    sys.exit(main())

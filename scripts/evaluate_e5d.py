"""E5d evaluation: scale inspection, synthetic static + response + retention gates, selection,
freeze, real transfer with PV / battery / load response.
Rules: configs/experiments/e5d_selection.yaml.

    uv run python scripts/evaluate_e5d.py scale        # report-only, BEFORE training (synthetic)
    uv run python scripts/evaluate_e5d.py synthetic    # gates, response tables, selection
    uv run python scripts/evaluate_e5d.py freeze       # metadata/e5d_checkpoint_registry.yaml
    uv run --env-file .env python scripts/evaluate_e5d.py transfer   # ONLY after the freeze commit

Outputs: reports/tables/e5d_*.csv, reports/figures/e5d_*.png, reports/experiments/e5d/*.json
"""

from __future__ import annotations

import argparse
import hashlib
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

from cloud2grid.genco import adaptation_e5c as ad5c  # noqa: E402
from cloud2grid.genco import adaptation_e5d as ad  # noqa: E402
from cloud2grid.genco import runner  # noqa: E402
from cloud2grid.licensing.registry import REPO_ROOT  # noqa: E402


def _load(name: str, path: str) -> Any:
    s = importlib.util.spec_from_file_location(name, REPO_ROOT / path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


ev5b = _load("ev5b", "scripts/evaluate_e5b.py")
ev5c = _load("ev5c", "scripts/evaluate_e5c.py")

SEL = ad.SEL
OUT = REPO_ROOT / "reports/experiments/e5d"
TABLES = REPO_ROOT / "reports/tables"
FIGS = REPO_ROOT / "reports/figures"
REGISTRY = REPO_ROOT / "metadata/e5d_checkpoint_registry.yaml"
E5C_REGISTRY = REPO_ROOT / "metadata/e5c_checkpoint_registry.yaml"
NET = ad.NETWORK
E4W = REPO_ROOT / "data/interim/e4"
SIGN_MW = 5.0
E5C_RUNS = [ad5c.run_name(ad.N_TRAIN, s) for s in (0, 1, 2)]
E5C_FROZEN_TEST_PBE = 0.6136112110675996  # e5c_ft_n10000_s2, E5c held-out test (registry)
PAIR_TARGETS = {
    "pairs_validation": ad.PAIR_ROOT["validation"],
    "pairs_test": ad.PAIR_ROOT["test"],
    "probes_validation": ad.E5C_WORK / "probes/validation",
    "probes_test": ad.E5C_WORK / "probes/test",
}


def pdir(run: str, target: str) -> Path:
    """E5d predictions first; E5c's own (frozen) predictions for E5c runs / zero-shot otherwise."""
    d = ad.WORK / "predictions" / run / target
    if (d / f"{NET}_predictions.parquet").exists():
        return d
    return ad.E5C_WORK / "predictions" / run / target


ev5c.pdir = pdir  # ev5c.static_metrics reads predictions through this


# ------------------------------------------------------------------ response metrics
def _pairs(target: str) -> pd.DataFrame:
    root = PAIR_TARGETS[target]
    if target.startswith("pairs_"):
        p = ad.complete_pairs(ad.assert_pair_set(root))
    else:  # E5c probes: same layout, no magnitude classes
        m = pd.read_parquet(root / "probes.parquet")
        m = m[m.complete]
        a = m[m.member == "A"].set_index("probe_id")
        b = m[m.member == "B"].set_index("probe_id").reindex(a.index)
        p = pd.DataFrame(
            {
                "probe_type": a.probe_type,
                "magnitude_class": "e5c_probe",
                "x_mw": a.x_mw,
                "scenario_a": a.scenario.astype(int),
                "scenario_b": b.scenario.astype(int),
            }
        ).reset_index()
    return p


def pair_elements(run: str, target: str) -> tuple[pd.DataFrame, dict[str, tuple]]:
    """Per family (import MW, branch P MW, branch Q MVAr, Vm pu on PQ, Va deg on non-REF):
    (ΔGENCO, ΔAC) arrays [n_pairs, n_elements]."""
    pairs = _pairs(target)
    d = pdir(run, target)
    bus = pd.read_parquet(d / f"{NET}_predictions.parquet")
    br = pd.read_parquet(d / f"{NET}_branch_predictions.parquet")
    i, j = pairs.scenario_a.to_numpy(), pairs.scenario_b.to_numpy()
    out: dict[str, tuple] = {}
    imp = ad.ref_import(bus)
    out["import"] = tuple(
        (imp.loc[j, c].to_numpy() - imp.loc[i, c].to_numpy())[:, None]
        for c in ("genco_import_mw", "ac_import_mw")
    )
    pq = bus.groupby("bus")["PQ"].max().astype(bool)
    nonref = ~bus.groupby("bus")["REF"].max().astype(bool)
    for name, cp, ct, mask, scale in (
        ("Vm", "Vm_pred", "Vm_target", pq, 1.0),
        ("Va", "Va_pred", "Va_target", nonref, 180.0 / np.pi),
    ):
        P = bus.pivot(index="scenario", columns="bus", values=cp).loc[:, mask[mask].index]
        T = bus.pivot(index="scenario", columns="bus", values=ct).loc[:, mask[mask].index]
        out[name] = (
            (P.loc[j].to_numpy() - P.loc[i].to_numpy()) * scale,
            (T.loc[j].to_numpy() - T.loc[i].to_numpy()) * scale,
        )
    b2 = br.copy()
    b2["k"] = b2.groupby(["scenario", "from_bus", "to_bus"]).cumcount()
    for name, cp, ct in (("branch_P", "Pft", "Pft_target"), ("branch_Q", "Qft", "Qft_target")):
        P = b2.pivot_table(index="scenario", columns=["from_bus", "to_bus", "k"], values=cp)
        T = b2.pivot_table(index="scenario", columns=["from_bus", "to_bus", "k"], values=ct)
        out[name] = (
            P.loc[j].to_numpy() - P.loc[i].to_numpy(),
            T.loc[j].to_numpy() - T.loc[i].to_numpy(),
        )
    return pairs, out


def response_table(run: str, target: str) -> pd.DataFrame:
    """Rows: (probe_type, magnitude_class|'all', family) with slope / correlation / errors."""
    pairs, el = pair_elements(run, target)
    rows = []
    groups = [("all", np.ones(len(pairs), bool))]
    groups += [(c, (pairs.magnitude_class == c).to_numpy()) for c in pairs.magnitude_class.unique()]
    for k in ad.TYPES:
        tk = (pairs.probe_type == k).to_numpy()
        for cls, cm in groups:
            sel = tk & cm
            if not sel.any() or (cls != "all" and cls == "e5c_probe"):
                continue
            x = pairs.x_mw.to_numpy()[sel]
            for o, (dg, da) in el.items():
                g, a = dg[sel], da[sel]
                ok = np.isfinite(g) & np.isfinite(a)
                gf, af = g[ok], a[ok]
                row = {
                    "run": run,
                    "target": target,
                    "probe_type": k,
                    "magnitude_class": cls,
                    "family": o,
                    "n_pairs": int(sel.sum()),
                    "abs_err_mean": float(np.abs(gf - af).mean()),
                    "ac_abs_mean": float(np.abs(af).mean()),
                    "rel_err": float(np.abs(gf - af).sum() / np.abs(af).sum()),
                    "corr": float(np.corrcoef(gf, af)[0, 1]) if gf.std() > 0 else np.nan,
                    "gain": float((gf * af).sum() / (af * af).sum()),  # GENCO on AC, through 0
                }
                if o == "import":
                    s_ac = float((a[:, 0] * x).sum() / (x * x).sum())
                    s_g = float((g[:, 0] * x).sum() / (x * x).sum())
                    row.update(slope_ac=s_ac, slope_genco=s_g, slope_ratio=s_g / s_ac)
                rows.append(row)
    return pd.DataFrame(rows)


def response_summary(T: pd.DataFrame, prefix: str) -> dict[str, float]:
    a = T[T.magnitude_class == "all"].set_index(["probe_type", "family"])
    out = {}
    for k in ad.TYPES:
        out[f"{prefix}_{k}_slope_ratio"] = float(a.loc[(k, "import"), "slope_ratio"])
        out[f"{prefix}_{k}_import_rel_mae"] = float(a.loc[(k, "import"), "rel_err"])
        for o in ("branch_P", "branch_Q", "Vm", "Va"):
            out[f"{prefix}_{k}_{o}_rel_err"] = float(a.loc[(k, o), "rel_err"])
    return out


# ------------------------------------------------------------------ gates
def gates_for(rec: dict, zs: dict) -> dict:
    """Pre-registered 23 criteria (e5d_selection.yaml synthetic_gate)."""
    g = {
        "ST1_pbe": rec["PBE_mean"] <= 0.10 * zs["PBE_mean"],
        "ST2_active_vs_dc": rec["P_residual"] <= 5.0 * rec["dc_P_residual"],
        "ST3_import_sign": rec["import_sign_accuracy_big"] >= 0.99,
        "ST4_import_mae": rec["import_mae_mw"] <= 5.0,
        "ST5_voltage": rec["V_error"] <= 0.015,
    }
    for k in ad.TYPES:
        g[f"RS1_slope_{k}"] = 0.8 <= rec.get(f"val_{k}_slope_ratio", np.nan) <= 1.2
        g[f"RS2_mae_{k}"] = rec.get(f"val_{k}_import_rel_mae", np.inf) <= 0.25
        g[f"RS3_branchP_{k}"] = rec.get(f"val_{k}_branch_P_rel_err", np.inf) <= 0.5
        g[f"RS4_Vm_{k}"] = rec.get(f"val_{k}_Vm_rel_err", np.inf) <= 0.5
        g[f"RS5_Va_{k}"] = rec.get(f"val_{k}_Va_rel_err", np.inf) <= 0.5
    g["RT1_e5_narrow"] = rec.get("e5_test_ga_PBE_mean", np.inf) <= 2.539
    g["RT2_e5b_broad"] = rec.get("e5b_test_ga_PBE_mean", np.inf) <= 1.173
    g["RT3_e5c_test"] = rec["PBE_mean"] <= 1.5 * E5C_FROZEN_TEST_PBE
    crit = [k for k in g if k[:2] in ("ST", "RS", "RT")]
    g["static_pass"] = all(g[k] for k in crit if k.startswith("ST"))
    g["pv_response_pass"] = all(g[k] for k in crit if k.startswith("RS") and k.endswith("_pv"))
    g["battery_load_response_pass"] = all(
        g[k] for k in crit if k.startswith("RS") and not k.endswith("_pv")
    )
    g["response_pass"] = g["pv_response_pass"] and g["battery_load_response_pass"]
    g["retention_pass"] = all(g[k] for k in crit if k.startswith("RT"))
    g["eligible"] = g["static_pass"] and g["response_pass"] and g["retention_pass"]
    g["n_criteria_passed"] = int(sum(bool(g[k]) for k in crit))
    return g


def select(S: pd.DataFrame) -> tuple[str | None, bool, dict]:
    """Pre-registered hierarchical rule (e5d_selection.yaml checkpoint_selection)."""
    c = S[S.run.str.startswith("e5d_") & (S["lambda"] > 0)].copy()
    if c.empty:
        return None, False, {}
    cv = c.groupby("lambda")["synthetic_val_PBE_mean"].agg(
        lambda x: float(x.std(ddof=1) / x.mean()) if len(x) > 1 else np.inf
    )
    c["lam_cv"] = c["lambda"].map(cv)
    c["lam_dist"] = np.abs(np.log(c["lambda"]))
    elig = c[c.eligible.astype(bool)]
    if len(elig):
        best = elig.synthetic_val_PBE_mean.min()
        tie = elig[elig.synthetic_val_PBE_mean <= 1.10 * best].sort_values(
            ["lam_cv", "lam_dist", "synthetic_val_PBE_mean"]
        )
        return (
            tie.iloc[0].run,
            False,
            {
                "eligible": elig.run.tolist(),
                "best_val_pbe": float(best),
                "tie_set": tie.run.tolist(),
            },
        )
    keys = ["static_pass", "pv_response_pass", "battery_load_response_pass", "retention_pass"]
    ranked = c.assign(**{k: c[k].astype(bool) for k in keys}).sort_values(
        [*keys, "n_criteria_passed", "synthetic_val_PBE_mean"],
        ascending=[False] * 5 + [True],
    )
    return ranked.iloc[0].run, True, {"eligible": [], "fallback_rank": ranked.run.tolist()}


# ------------------------------------------------------------------ synthetic
def cmd_synthetic() -> dict:
    man = ad5c.assert_synthetic_dataset(ad.ABS_ROOT)
    blocks = man.set_index("scenario")["load_block"]
    dcs = {}
    for t in ("synthetic_test", "synthetic_val", "e5_test_ga", "e5b_test_ga"):
        ids = ev5c.ids_of(t, man)
        root = ev5c.TARGET_ROOT[t]
        dcs[t] = ev5c.gm.dc_baseline_frames(
            ev5b.read_raw(root, ids), ev5b.read_raw(root, ids, table="branch_data")
        )
    runs = [{"run": "zero_shot", "lambda": np.nan, "seed": None, "role": "zero-shot (E4)"}]
    runs += [
        {"run": r, "lambda": 0.0, "seed": s, "role": "baseline E5c (ordinary loss)"}
        for s, r in enumerate(E5C_RUNS)
    ]
    runs += [json.loads(p.read_text()) for p in sorted((OUT / "runs").glob("e5d_*.json"))]
    rows, resp = [], []
    for r in runs:
        rec: dict[str, Any] = {k: r.get(k) for k in ("run", "lambda", "seed", "role")}
        rec.update(ev5c.static_metrics(r["run"], "synthetic_test", dcs["synthetic_test"], blocks))
        for t in ("synthetic_val", "e5_test_ga", "e5b_test_ga"):
            s = ev5c.static_metrics(r["run"], t, dcs[t], blocks if t == "synthetic_val" else None)
            for k in ("PBE_mean", "P_residual", "V_error", "branch_P_error", "import_mae_mw"):
                rec[f"{t}_{k}"] = s[k]
        for t, pre in (
            ("pairs_validation", "val"),
            ("pairs_test", "test"),
            ("probes_validation", "e5cval"),
            ("probes_test", "e5ctest"),
        ):
            T = response_table(r["run"], t)
            resp.append(T)
            rec.update(response_summary(T, pre))
        for k in ("wall_s", "best_epoch", "epochs_run", "best_validation_total_loss"):
            rec[k] = r.get(k)
        rec["checkpoint_sha256"] = (r.get("checkpoint") or {}).get("sha256")
        rows.append(rec)
    S = pd.DataFrame(rows)
    zs = S[S.run == "zero_shot"].iloc[0].to_dict()
    G = pd.DataFrame(
        [
            {"run": r["run"], **gates_for(r, zs)}
            for r in S.to_dict("records")
            if r["run"] != "zero_shot"
        ]
    )
    S = S.merge(G, on="run", how="left")
    S.to_csv(TABLES / "e5d_seed_results.csv", index=False)
    R = pd.concat(resp, ignore_index=True)
    R.to_csv(TABLES / "e5d_response_probes.csv", index=False)
    sel, flagged, why = select(S)
    srow = S.set_index("run").loc[sel]
    syn_pv = (0.8 <= srow["test_pv_slope_ratio"] <= 1.2) and (
        srow["test_pv_import_rel_mae"] <= 0.25
    )
    res = {
        "zero_shot_on_e5c_test": {k: zs[k] for k in ("PBE_mean", "P_residual", "dc_P_residual")},
        "eligible_runs": S.loc[S.eligible.fillna(False).astype(bool), "run"].tolist(),
        "selected": sel,
        "selected_flagged": flagged,
        "selection_trace": why,
        "SYN_PV_LEARNED_selected_on_test_pairs": bool(syn_pv),
        **runner.git_commit(),
    }
    (OUT / "synthetic_evaluation.json").write_text(json.dumps(res, indent=2, default=str))
    figure(S, R)
    cols = [
        "run",
        "PBE_mean",
        "P_residual",
        "import_mae_mw",
        "import_sign_accuracy_big",
        "V_error",
        "val_pv_slope_ratio",
        "val_pv_import_rel_mae",
        "val_battery_slope_ratio",
        "val_load_slope_ratio",
        "val_pv_branch_P_rel_err",
        "val_pv_Vm_rel_err",
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


def figure(S: pd.DataFrame, R: pd.DataFrame) -> None:
    order = [r for r in ["zero_shot", *E5C_RUNS] if r in set(S.run)]
    order += sorted(r for r in S.run if r.startswith("e5d_"))
    T = R[(R.target == "pairs_test") & (R.family == "import") & (R.magnitude_class == "all")]
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.2))
    w = 0.27
    for i, k in enumerate(ad.TYPES):
        v = T[T.probe_type == k].set_index("run").reindex(order)
        ax[0].bar(np.arange(len(order)) + (i - 1) * w, v.slope_ratio, w, label=k)
        ax[1].bar(np.arange(len(order)) + (i - 1) * w, v.rel_err, w, label=k)
    ax[0].axhspan(0.8, 1.2, color="green", alpha=0.12, label="gate band")
    ax[0].set_title("Import response slope ratio GENCO / AC (E5d test pairs)", fontsize=9)
    ax[1].axhline(0.25, color="green", ls=":", label="gate 0.25")
    ax[1].set_title("Import response relative MAE (E5d test pairs)", fontsize=9)
    s = S.set_index("run").reindex(order)
    ax[2].bar(np.arange(len(order)), s.PBE_mean, color="grey")
    ax[2].axhline(1.5 * E5C_FROZEN_TEST_PBE, color="red", ls=":", label="RT3 limit")
    ax[2].set_title("Absolute accuracy: PBE (MVA), E5c held-out test", fontsize=9)
    for a in ax:
        a.set_xticks(np.arange(len(order)))
        a.set_xticklabels(order, rotation=40, ha="right", fontsize=7)
        a.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(FIGS / "e5d_synthetic_response.png", dpi=120)
    plt.close(fig)


# ------------------------------------------------------------------ freeze
def _h(p: str | Path) -> str:
    return hashlib.sha256((REPO_ROOT / p).read_bytes()).hexdigest()


def cmd_freeze() -> None:
    res = json.loads((OUT / "synthetic_evaluation.json").read_text())
    sel = res["selected"]
    S = pd.read_csv(TABLES / "e5d_seed_results.csv").set_index("run")
    runs = {
        json.loads(p.read_text())["run"]: json.loads(p.read_text())
        for p in sorted((OUT / "runs").glob("e5d_*.json"))
    }
    rec = runs[sel]

    def entry(r: dict) -> dict:
        return {
            "lambda": r["lambda"],
            "seed": r["seed"],
            "role": r["role"],
            "checkpoint": r["checkpoint"],
            "normalizer": {k: r["normalizer"][k] for k in ("path", "sha256", "baseMVA")},
            "response_sigma_sha256": r["response_sigma_sha256"],
        }

    evidence_keys = [
        "PBE_mean",
        "P_residual",
        "import_mae_mw",
        "import_sign_accuracy_big",
        "V_error",
        "synthetic_val_PBE_mean",
        "e5_test_ga_PBE_mean",
        "e5b_test_ga_PBE_mean",
        *[f"val_{k}_slope_ratio" for k in ad.TYPES],
        *[f"val_{k}_import_rel_mae" for k in ad.TYPES],
        *[f"test_{k}_slope_ratio" for k in ad.TYPES],
        "n_criteria_passed",
        "eligible",
    ]
    reg = {
        "schema": "cloud2grid E5d checkpoint registry v1",
        "frozen": True,
        "frozen_before_real_state_evaluation": True,
        "selection_rule": SEL["checkpoint_selection"],
        "selected": sel,
        "selected_flagged": res["selected_flagged"],
        "selection_trace": res["selection_trace"],
        "SYN_PV_LEARNED_selected_on_test_pairs": res["SYN_PV_LEARNED_selected_on_test_pairs"],
        "evaluable_on_real": [sel, *[r for r in runs if r != sel]],
        "checkpoints": {
            sel: {
                **entry(rec),
                "normalizer_fitted_on": rec["normalizer_fitted_on"],
                "training_split_sha256": rec["split_sha256"],
                "best_epoch": rec["best_epoch"],
                "epochs_run": rec["epochs_run"],
                "graphkit_config": rec["graphkit_config"],
                "graphkit_config_sha256": _h(rec["graphkit_config"]),
                "mlflow_run": rec["mlflow_run"],
                "response_sigma": rec["response_sigma"]["sigma"],
                "synthetic_evidence": {
                    k: (None if pd.isna(S.at[sel, k]) else _py(S.at[sel, k])) for k in evidence_keys
                },
            }
        },
        "post_freeze_runs": {r: entry(v) for r, v in runs.items() if r != sel},
        "config_sha256": {
            p: _h(p)
            for p in (
                "configs/experiments/e5d_response_training.yaml",
                "configs/experiments/e5d_selection.yaml",
            )
        },
        "pair_manifest_sha256": {
            s: ad.sha256_file(ad.PAIR_ROOT[s] / "pairs.parquet") for s in ad.PAIR_SETS
        },
        "selection_table_sha256": _h("reports/tables/e5d_seed_results.csv"),
        "response_table_sha256": _h("reports/tables/e5d_response_probes.csv"),
        **runner.git_commit(),
    }
    REGISTRY.write_text(yaml.safe_dump(reg, sort_keys=False, allow_unicode=True))
    print(yaml.safe_dump(reg["checkpoints"], sort_keys=False))


def _py(v: Any) -> Any:
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v)
    return v


def frozen() -> dict:
    if not REGISTRY.exists() or not yaml.safe_load(REGISTRY.read_text()).get("frozen"):
        raise SystemExit("E5d registry not frozen: real states stay hidden")
    reg = yaml.safe_load(REGISTRY.read_text())
    c = reg["checkpoints"][reg["selected"]]
    for k in ("checkpoint", "normalizer"):
        if ad.sha256_file(REPO_ROOT / c[k]["path"]) != c[k]["sha256"]:
            raise SystemExit(f"{k} changed after freezing")
    return reg


# ------------------------------------------------------------------ real transfer
def transfer_criteria(c: pd.Series, e5c: pd.Series) -> dict[str, bool]:
    """Pre-registered R1–R7 (e5d_selection.yaml real_transfer)."""

    def err(row: pd.Series, k: str) -> float:
        return abs(row[f"genco_slope_{k}"] / row[f"ac_slope_{k}"] - 1.0)

    return {
        "R1_active": bool(c.P_residual <= 2.885),
        "R2_pbe": bool((c.PBE_mean <= 3.318) and (c.PBE_q95 <= 10.0)),
        "R3_import": bool(
            (c.import_sign_accuracy_big >= 0.99)
            and (c.import_mae_mw <= 5.0)
            and (c.import_corr >= 0.9)
            and (0.75 <= c.import_sd_pred_mw / c.import_sd_ac_mw <= 1.33)
        ),
        "R4_voltage": bool((c.vm_tracking_median_r >= 0.8) and (c.V_error <= 0.01)),
        "R5_pv_response": bool(0.8 <= c.genco_slope_pv / c.ac_slope_pv <= 1.2),
        "R6_battery_no_regression": bool(err(c, "chap31") <= err(e5c, "chap31") + 0.10),
        "R7_load_no_regression": bool(err(c, "load") <= err(e5c, "load") + 0.10),
    }


def verdict(crit: dict[str, bool], flagged: bool, syn_pv_learned: bool) -> str:
    if all(crit.values()) and not flagged:
        return "E5D-A_RESPONSE_AWARE_TRAINING_SOLVES_THE_PV_BLIND_SPOT"
    if not syn_pv_learned:
        return "E5D-C_RESPONSE_AWARE_TRAINING_FAILS_EVEN_SYNTHETICALLY"
    if not crit["R5_pv_response"]:
        return "E5D-B_SYNTHETIC_RESPONSE_LEARNED_BUT_DOES_NOT_TRANSFER"
    return "E5D-D_PARTIAL_OR_OTHER"


def cmd_transfer() -> None:
    reg = frozen()
    sel = reg["selected"]
    feats = ev5b.state_features(E4W / "datasets/S1_WEATHER_ALIGNED")
    e5b_sel = yaml.safe_load((REPO_ROOT / "metadata/e5b_checkpoint_registry.yaml").read_text())[
        "selected"
    ]
    e5c_sel = yaml.safe_load(E5C_REGISTRY.read_text())["selected"]
    ga = ad.E5C_WORK / "datasets/S1_WEATHER_ALIGNED_GENAWARE"
    s1 = E4W / "datasets/S1_WEATHER_ALIGNED"
    models = {
        "zero-shot (E4)": (ev5b.pred_dir("zero_shot", "S1_WEATHER_ALIGNED"), s1),
        "E5": (ev5b.pred_dir(ev5b.e5_selected(), "S1_WEATHER_ALIGNED"), s1),
        "E5b": (ev5b.pred_dir(e5b_sel, "S1_WEATHER_ALIGNED"), s1),
        "E5c": (ad.E5C_WORK / "predictions" / e5c_sel / "S1_WEATHER_ALIGNED_GENAWARE", ga),
        "E5d": (ad.WORK / "predictions" / sel / "S1_WEATHER_ALIGNED_GENAWARE", ga),
    }
    rows, frames, bsl = [], {}, []
    for lab, (pdir_, root) in models.items():
        m, bus, br = ev5c.real_frame(pdir_, root)
        frames[lab] = m
        r = {"model": lab, **ev5b.summarise(m, bus), **ev5b.import_sensitivity(m, feats)}
        big = m.ac_import_mw.abs() >= SIGN_MW
        r["import_sign_accuracy_big"] = float(
            (np.sign(m.ac_import_mw[big]) == np.sign(m.genco_import_mw[big])).mean()
        )
        b = ev5c.branch_pv_slopes(br, feats).assign(model=lab)
        r["branch_pv_slope_median_abs_err"] = float(
            (b.pv_slope_model - b.pv_slope_ac).abs().median()
        )
        r["pv_response_error_mw"] = float(
            abs(r["genco_slope_pv"] - r["ac_slope_pv"])
            * feats.reindex(m.scenario.to_numpy())["pv_injection_mw"].mean()
        )
        bsl.append(b)
        rows.append(r)
    # identical population (same states, same AC targets) for every model
    ids = {k: tuple(sorted(v.scenario_id)) for k, v in frames.items()}
    if len(set(ids.values())) != 1 or len(next(iter(ids.values()))) != 2829:
        raise SystemExit("real population differs between models")
    ac_imp = {
        k: v.set_index("scenario").ac_import_mw.sort_index().to_numpy() for k, v in frames.items()
    }
    for k in ac_imp:
        if not np.allclose(ac_imp[k], ac_imp["E5c"], atol=1e-3):
            raise SystemExit(f"AC targets differ for {k}")
    T = pd.DataFrame(rows)
    T.to_csv(TABLES / "e5d_real_transfer.csv", index=False)
    B = pd.concat(bsl)
    B.to_csv(TABLES / "e5d_branch_pv_slopes.csv", index=False)
    resp = T[
        [
            "model",
            "ac_slope_pv",
            "genco_slope_pv",
            "pv_response_error_mw",
            "branch_pv_slope_median_abs_err",
            "ac_slope_chap31",
            "genco_slope_chap31",
            "ac_slope_load",
            "genco_slope_load",
        ]
    ].copy()
    for k in ("pv", "chap31", "load"):
        resp[f"{k}_slope_ratio"] = resp[f"genco_slope_{k}"] / resp[f"ac_slope_{k}"]
    resp.to_csv(TABLES / "e5d_response_transfer.csv", index=False)
    t = T.set_index("model")
    crit = transfer_criteria(t.loc["E5d"], t.loc["E5c"])
    syn = bool(reg["SYN_PV_LEARNED_selected_on_test_pairs"])
    v = verdict(crit, bool(reg["selected_flagged"]), syn)
    res = {
        "selected": sel,
        "criteria": crit,
        "REAL_TRANSFER_SUCCESS": all(crit.values()),
        "selected_flagged": reg["selected_flagged"],
        "SYN_PV_LEARNED": syn,
        "verdict": v,
        "weather_rule": "RUN" if v.startswith("E5D-A") else "STOP — weather remains unresolved",
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
        "import_bias_mw",
        "import_corr",
        "genco_slope_pv",
        "ac_slope_pv",
    ]
    print(T[cols].round(4).to_string(index=False))
    print(resp.round(4).to_string(index=False))
    print(json.dumps({k: res[k] for k in ("criteria", "verdict", "weather_rule")}, indent=1))


# ------------------------------------------------------------------ post-freeze diagnostics
def bus_pv_slopes(bus: pd.DataFrame, feats: pd.DataFrame) -> pd.DataFrame:
    """Per bus: OLS PV coefficient of Vm and Va (deg) with load and CHAP31, AC vs model."""
    load = feats[[f"Pd {n}" for n in ev5b.LOAD_NODES]].sum(axis=1)
    rows = []
    for b, g in bus.groupby("bus"):
        g = g.set_index("scenario").sort_index()
        xx = feats.reindex(g.index)
        X = np.column_stack(
            [np.ones(len(g)), load.reindex(g.index), xx[f"Pd {ev5b.BATT}"], xx["pv_injection_mw"]]
        )
        ok = np.isfinite(X).all(1)
        row = {"bus": b}
        for q, cp, ct, sc in (
            ("Vm", "Vm_pred", "Vm_target", 1.0),
            ("Va", "Va_pred", "Va_target", 180.0 / np.pi),
        ):
            row[f"{q}_pv_slope_ac"] = np.linalg.lstsq(X[ok], g[ct].to_numpy()[ok] * sc, rcond=None)[
                0
            ][3]
            row[f"{q}_pv_slope_model"] = np.linalg.lstsq(
                X[ok], g[cp].to_numpy()[ok] * sc, rcond=None
            )[0][3]
        rows.append(row)
    return pd.DataFrame(rows)


def cmd_postfreeze() -> None:
    """Report-only, after the transfer verdict: every E5d run on S1 (incl. the λ = 0 control) and
    bus-level Vm / Va PV slopes. Nothing here feeds selection, criteria or the verdict."""
    reg = frozen()
    feats = ev5b.state_features(E4W / "datasets/S1_WEATHER_ALIGNED")
    ga = ad.E5C_WORK / "datasets/S1_WEATHER_ALIGNED_GENAWARE"
    e5c_sel = yaml.safe_load(E5C_REGISTRY.read_text())["selected"]
    runs = {"E5c": ad.E5C_WORK / "predictions" / e5c_sel / "S1_WEATHER_ALIGNED_GENAWARE"}
    runs |= {
        r: ad.WORK / "predictions" / r / "S1_WEATHER_ALIGNED_GENAWARE"
        for r in reg["evaluable_on_real"]
    }
    rows, bus_rows = [], []
    for lab, d in runs.items():
        m, bus, br = ev5c.real_frame(d, ga)
        r = {
            "model": lab,
            "selected": lab == reg["selected"],
            **ev5b.summarise(m, bus),
            **ev5b.import_sensitivity(m, feats),
        }
        b = ev5c.branch_pv_slopes(br, feats)
        r["branch_pv_slope_median_abs_err"] = float(
            (b.pv_slope_model - b.pv_slope_ac).abs().median()
        )
        bs = bus_pv_slopes(bus, feats).assign(model=lab)
        for q in ("Vm", "Va"):
            r[f"bus_{q}_pv_slope_median_abs_err"] = float(
                (bs[f"{q}_pv_slope_model"] - bs[f"{q}_pv_slope_ac"]).abs().median()
            )
            r[f"bus_{q}_pv_slope_ac_median_abs"] = float(bs[f"{q}_pv_slope_ac"].abs().median())
        bus_rows.append(bs)
        rows.append(r)
    T = pd.DataFrame(rows)
    for k in ("pv", "chap31", "load"):
        T[f"{k}_slope_ratio"] = T[f"genco_slope_{k}"] / T[f"ac_slope_{k}"]
    T.to_csv(TABLES / "e5d_postfreeze_runs_real.csv", index=False)
    pd.concat(bus_rows).to_csv(TABLES / "e5d_bus_pv_slopes.csv", index=False)
    cols = [
        "model",
        "PBE_mean",
        "P_residual",
        "V_error",
        "import_mae_mw",
        "import_bias_mw",
        "import_corr",
        "pv_slope_ratio",
        "chap31_slope_ratio",
        "load_slope_ratio",
        "branch_pv_slope_median_abs_err",
        "bus_Vm_pv_slope_median_abs_err",
        "bus_Va_pv_slope_median_abs_err",
        "bus_Vm_pv_slope_ac_median_abs",
        "bus_Va_pv_slope_ac_median_abs",
    ]
    print(T[cols].round(5).to_string(index=False))


# ------------------------------------------------------------------ scale inspection
def cmd_scale(gpu: str = "0") -> None:
    """Report only: L_original, L_response of zero-shot / E5c n10000 on the E5d TRAINING pairs."""
    import os

    os.environ.setdefault("CUDA_VISIBLE_DEVICES", gpu)
    import torch
    from gridfm_graphkit.datasets.normalizers import HeteroDataMVANormalizer
    from gridfm_graphkit.io.param_handler import NestedNamespace
    from torch.utils.data import DataLoader
    from torch_geometric.loader import DataLoader as GDL

    from cloud2grid.genco import response_loss as rl
    from cloud2grid.genco import response_task as rt

    tr = _load("tr5d", "scripts/train_e5d.py")
    conf = tr.graphkit_config(1.0, 0, "scale_inspection", ad.e5c_split_dir(0))
    base = yaml.safe_load(conf.read_text())
    from gridfm_graphkit.io.config_version import resolve_config

    args = NestedNamespace(**resolve_config(base, str(conf), "auto_inline"))
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    out = {}
    for run in ["zero_shot", *E5C_RUNS]:
        w, stats = tr.weights_of(run)
        norm = HeteroDataMVANormalizer(args)
        norm.fit_from_dict(torch.load(stats, map_location="cpu", weights_only=True)[ad.NETWORK])
        task = rt.PowerFlowResponseTask(args, [norm])
        from gridfm_graphkit.cli import _normalize_loaded_state_dict_keys

        task.load_state_dict(_normalize_loaded_state_dict_keys(torch.load(w, map_location="cpu")))
        task.to(dev).eval()
        ds = task._dataset(str(ad.PAIR_ROOT["train"]))
        pairs = rt.read_pairs(str(ad.PAIR_ROOT["train"]))
        pl = DataLoader(
            rt.PairDataset(ds, pairs), batch_size=256, collate_fn=rt.collate, num_workers=4
        )
        acc: dict = {}
        with torch.no_grad():
            for ba, bb, types, x in pl:
                rl.sigma_accumulate(
                    acc, rl.deltas(task._ac_values(ba), task._ac_values(bb)), x.double(), types
                )
            task.sigma = rl.sigma_finalise(acc)
            l_resp, diag = task.response_metrics(pl)
            tot, n = 0.0, 0
            for b in GDL(ds, batch_size=256, num_workers=4):
                b = b.to(dev)
                _, ld = task.shared_step(b)
                tot += float(ld["loss"]) * b.num_graphs
                n += b.num_graphs
        out[run] = {
            "L_original_on_pair_states": tot / n,
            "L_response": l_resp,
            "lambda_kappa_L_response_at_lambda_1": ad.KAPPA * l_resp,
            "ratio_kappa_L_response_to_L_original": ad.KAPPA * l_resp / (tot / n),
            "import_slope_ratios": {k: v for k, v in diag.items() if "slope" in k},
            "sigma": task.sigma,
        }
        print(run, json.dumps({k: v for k, v in out[run].items() if k != "sigma"}, default=str))
    rec = {
        "note": "report only — the pre-registered λ set is not changed by this inspection",
        "kappa": ad.KAPPA,
        "huber_delta": ad.HUBER_DELTA,
        "models": out,
        **runner.git_commit(),
    }
    (OUT / "scale_inspection.json").write_text(json.dumps(rec, indent=2, default=str))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["scale", "synthetic", "freeze", "transfer", "postfreeze"])
    ap.add_argument("--gpu", default="0")
    a = ap.parse_args()
    for d in (TABLES, FIGS, OUT):
        d.mkdir(parents=True, exist_ok=True)
    if a.command == "scale":
        cmd_scale(a.gpu)
    else:
        {
            "synthetic": cmd_synthetic,
            "freeze": cmd_freeze,
            "transfer": cmd_transfer,
            "postfreeze": cmd_postfreeze,
        }[a.command]()
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    sys.exit(main())

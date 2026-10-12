"""E4 evaluation: per-scenario GENCO metrics, family summaries, generalisation gaps, conditioning,
ramp/transition analysis, hero events, runtime, decision, scenario registry.

    uv run python scripts/evaluate_e4.py

Reads only: family gate/metadata tables (reports/experiments/e4/families/), exported AC datasets
and GENCO predictions (data/interim/e4/), pre-registered configs. Applies the pre-registered
rules in configs/experiments/e4_zero_shot.yaml (`statistics`, `decision`); nothing is tuned to
the results. GENCO weights are never touched.

Outputs
    reports/tables/e4_scenario_metrics.parquet, e4_family_summary.csv, e4_generalisation_gaps.csv,
    e4_seed_gaps.csv, e4_conditioning.csv, e4_ramp_conditioned.csv, e4_transitions_by_event.csv,
    e4_runtime.csv
    reports/experiments/e4/evaluation.json, hero/<event>.csv
    reports/figures/e4_family_distributions.png, e4_ramp_conditioned.png, e4_hero_<event>.png
    metadata/scenario_registry.yaml
"""

from __future__ import annotations

import json
import sys
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from cloud2grid.evaluation import genco_metrics as gm  # noqa: E402
from cloud2grid.evaluation import statistics as st  # noqa: E402
from cloud2grid.evaluation import transitions as tr  # noqa: E402
from cloud2grid.genco import runner  # noqa: E402
from cloud2grid.licensing.registry import REPO_ROOT  # noqa: E402
from cloud2grid.scenarios.matched_control import assign_donors  # noqa: E402

ZS = yaml.safe_load((REPO_ROOT / "configs/experiments/e4_zero_shot.yaml").read_text())
MC = yaml.safe_load((REPO_ROOT / "configs/experiments/e4_matched_control.yaml").read_text())
RA = yaml.safe_load((REPO_ROOT / "configs/experiments/e4_ramp_analysis.yaml").read_text())
WORK = REPO_ROOT / "data/interim/e4"
FAMDIR = REPO_ROOT / "reports/experiments/e4/families"
OUT = REPO_ROOT / "reports/experiments/e4"
TABLES = REPO_ROOT / "reports/tables"
FIGS = REPO_ROOT / "reports/figures"
NET = "sundon_33kv"
METRICS = [
    "PBE_mean",
    "PBE_max",
    "P_residual",
    "Q_residual",
    "V_error",
    "angle_error",
    "branch_P_error",
    "branch_Q_error",
    "max_loading_error",
    "dc_P_residual",
]
GAP_METRICS = [
    "PBE_mean",
    "P_residual",
    "Q_residual",
    "V_error",
    "angle_error",
    "branch_P_error",
    "branch_Q_error",
    "max_loading_error",
]
S2_SEEDS = MC["families"]["S2_MATCHED_PV_CONTROL"]["seeds"]
BOOT = ZS["statistics"]["bootstrap"]


def family_metrics(fam: str, pred_tag: str = "", ratings_from: str | None = None) -> pd.DataFrame:
    gates = pd.read_parquet(FAMDIR / f"{fam}_gates.parquet")
    pdir = WORK / "predictions" / f"{fam}{pred_tag}"
    bus = pd.read_parquet(pdir / f"{NET}_predictions.parquet")
    branch = pd.read_parquet(pdir / f"{NET}_branch_predictions.parquet")
    rpath = WORK / "datasets" / (ratings_from or fam) / NET / "branch_ratings.parquet"
    ratings = pd.read_parquet(rpath) if rpath.exists() else None
    if ratings_from is not None and ratings is not None:  # intact-network ratings reused (S0)
        base = ratings[ratings["scenario"] == 0].drop(columns="scenario")
        ratings = base.merge(pd.DataFrame({"scenario": bus["scenario"].unique()}), how="cross")
    m = gm.scenario_metrics(bus, branch, ratings)
    m = m.merge(
        gm.dc_baseline(WORK / "datasets" / fam / NET / "raw").reset_index(),
        on="scenario",
        how="left",
    )
    acc = gates[gates["rejected"].isna()].copy()
    acc["scenario"] = acc["scenario"].astype(int)
    m = m.merge(acc, on="scenario", how="left")
    m["scenario_family"] = fam + pred_tag
    m["scenario_id"] = m["scenario_family"] + ":" + m["scenario"].astype(str)
    if "slot" in m:
        m["block"] = pd.to_datetime(m["slot"], utc=True).dt.strftime("%Y-%m-%d")
    else:
        m["block"] = m["load_block"]
    run = json.loads((OUT / "runs" / f"{fam}{pred_tag}.json").read_text())
    m["genco_runtime_s"] = run["seconds_per_scenario"]
    return m


def event_windows() -> pd.DataFrame:
    ev = pd.read_csv(TABLES / "e3_candidate_events.csv", parse_dates=["start", "end"])
    ev["start"] = pd.to_datetime(ev["start"], utc=True)
    ev["end"] = pd.to_datetime(ev["end"], utc=True)
    return ev


def tag_events(slots: pd.Series, ev: pd.DataFrame) -> pd.Series:
    """E3 event ids whose window contains each slot (';'-joined), else None. Interpretation only."""
    s = pd.to_datetime(slots, utc=True)
    tags: list[list[str]] = [[] for _ in range(len(s))]
    for e in ev.itertuples():
        for i in np.flatnonzero(((s >= e.start) & (s <= e.end)).to_numpy()):
            tags[i].append(e.event_id)
    return pd.Series([";".join(x) if x else None for x in tags], index=slots.index)


def summarise(m: pd.DataFrame, fam: str) -> dict[str, Any]:
    row: dict[str, Any] = {"family": fam, "n": int(len(m)), "blocks": int(m["block"].nunique())}
    for c in METRICS:
        if c in m and m[c].notna().any():
            ci = st.block_mean_ci(
                m[c] if c != "PBE_max" else m[c], m["block"], BOOT["resamples"], BOOT["seed"]
            )
            row[c] = ci["mean"] if c != "PBE_max" else float(m[c].max())
            if c != "PBE_max":
                row[f"{c}_ci"] = [round(ci["ci_low"], 6), round(ci["ci_high"], 6)]
    row["genco_vs_dc_active_ratio"] = row.get("P_residual", np.nan) / row.get(
        "dc_P_residual", np.nan
    )
    for flag in ("overload_ac", "overload_pred", "vlim_ac", "vlim_pred"):
        if flag in m:
            row[f"n_{flag}"] = int(m[flag].fillna(False).sum())
    return row


def overload_detection(m: pd.DataFrame) -> dict[str, int]:
    a, p = m["overload_ac"].fillna(False), m["overload_pred"].fillna(False)
    va, vp = m["vlim_ac"].fillna(False), m["vlim_pred"].fillna(False)
    return {
        "overload_tp": int((a & p).sum()),
        "overload_fn": int((a & ~p).sum()),
        "overload_fp": int((~a & p).sum()),
        "vlim_tp": int((va & vp).sum()),
        "vlim_fn": int((va & ~vp).sum()),
        "vlim_fp": int((~va & vp).sum()),
    }


def main() -> int:
    TABLES.mkdir(exist_ok=True)
    FIGS.mkdir(exist_ok=True)
    ev = event_windows()
    fams = {
        "S0_STANDARD_SYNTHETIC": family_metrics(
            "S0_STANDARD_SYNTHETIC", ratings_from="S1_WEATHER_ALIGNED"
        ),
        "S1_WEATHER_ALIGNED": family_metrics("S1_WEATHER_ALIGNED"),
        "S1_WEATHER_ALIGNED_BASE_LTDS": family_metrics("S1_WEATHER_ALIGNED_BASE_LTDS"),
        "E4D_TIMELINE": family_metrics("E4D_TIMELINE"),
    }
    own = OUT / "runs" / "S1_WEATHER_ALIGNED_ownnorm.json"
    if own.exists():
        fams["S1_WEATHER_ALIGNED_ownnorm"] = family_metrics(
            "S1_WEATHER_ALIGNED", pred_tag="_ownnorm"
        )
    s2 = {s: family_metrics(f"S2_MATCHED_PV_CONTROL_s{s}") for s in S2_SEEDS}
    for s, m in s2.items():
        m["control_seed"] = s
    S2 = pd.concat(s2.values(), ignore_index=True)
    S2["scenario_family"] = "S2_MATCHED_PV_CONTROL"
    S1 = fams["S1_WEATHER_ALIGNED"]

    # ---- per-scenario table (requested schema + extras)
    allm = pd.concat([*fams.values(), S2], ignore_index=True)
    allm["weather_class_if_any"] = tag_events(allm["slot"], ev) if "slot" in allm else None
    rename = {
        "slot": "timestamp",
        "p_hv_injected_mw": "PV_injected_MW",
        "fleet_pv_mw": "PV_MW",
        "fleet_cf": "PV_capacity_factor",
        "abs_hv_ramp_mw": "PV_ramp_MW",
        "ac_converged": "AC_converged",
        "P_residual": "P_residual",
        "V_error": "V_error",
        "genco_runtime_s": "runtime",
    }
    keep = [
        "scenario_id",
        "scenario_family",
        "slot",
        "control_seed",
        "weather_class_if_any",
        "fleet_pv_mw",
        "p_hv_injected_mw",
        "fleet_cf",
        "mean_kc",
        "abs_hv_ramp_mw",
        "ac_converged",
        *METRICS,
        "max_loading_ac",
        "overload_ac",
        "overload_pred",
        "vlim_ac",
        "vlim_pred",
        "genco_runtime_s",
        "pm_runtime_s",
        "pp_runtime_s",
        "block",
        "donor_slot",
        "load_p_mw",
    ]
    table = allm[[c for c in keep if c in allm]].rename(columns=rename)
    table.to_parquet(TABLES / "e4_scenario_metrics.parquet", index=False)

    # ---- family summaries
    rows = [summarise(m, f) for f, m in fams.items()]
    rows.append(summarise(S2, "S2_MATCHED_PV_CONTROL (10 seeds pooled)"))
    rows += [summarise(m, f"S2_MATCHED_PV_CONTROL_s{s}") for s, m in s2.items()]
    summary = pd.DataFrame(rows)
    summary.to_csv(TABLES / "e4_family_summary.csv", index=False)

    # ---- gaps
    gaps, seed_gaps = [], []
    S0 = fams["S0_STANDARD_SYNTHETIC"]
    s2_mean = S2.groupby("slot")[GAP_METRICS].mean().add_suffix("_s2")
    paired = S1.set_index("slot")[GAP_METRICS + ["block"]].join(s2_mean, how="inner").reset_index()
    for c in GAP_METRICS:
        g0 = st.gap_unpaired(
            S1[c], S1["block"], S0[c], S0["block"], BOOT["resamples"], BOOT["seed"]
        )
        gaps.append(
            {
                "metric": c,
                "comparison": "S1 − S0_STANDARD_SYNTHETIC (operating distribution "
                "incl. topology/admittance perturbation)",
                **g0,
                "material": st.material(g0, 0.10),
            }
        )
        g2 = st.gap_paired(paired, c, f"{c}_s2", "block", BOOT["resamples"], BOOT["seed"])
        gaps.append(
            {
                "metric": c,
                "comparison": "S1 − S2_MATCHED_PV_CONTROL (paired; mean over 10 seeds)",
                **g2,
                "material": st.material(g2, 0.10),
            }
        )
        for s, m in s2.items():
            p = (
                S1.set_index("slot")[[c, "block"]]
                .join(m.set_index("slot")[[c]].add_suffix("_s2"), how="inner")
                .reset_index()
            )
            gs = st.gap_paired(p, c, f"{c}_s2", "block", BOOT["resamples"], BOOT["seed"])
            seed_gaps.append({"metric": c, "control_seed": s, **gs})
    gaps = pd.DataFrame(gaps)
    gaps.to_csv(TABLES / "e4_generalisation_gaps.csv", index=False)
    seed_gaps = pd.DataFrame(seed_gaps)
    seed_gaps.to_csv(TABLES / "e4_seed_gaps.csv", index=False)

    # ---- conditioning on pre-registered weather variables (S1)
    cond = []
    for var in MC["conditioning_variables"]:
        if var == "bins" or var not in S1:
            continue
        q = pd.qcut(S1[var], 4, labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop")
        for lab, g in S1.groupby(q, observed=True):
            for c in ["PBE_mean", "P_residual", "V_error", "branch_P_error", "max_loading_error"]:
                ci = st.block_mean_ci(g[c], g["block"], BOOT["resamples"], BOOT["seed"])
                cond.append(
                    {
                        "variable": var,
                        "bin": str(lab),
                        "range": f"{g[var].min():.3f}–{g[var].max():.3f}",
                        "metric": c,
                        **ci,
                    }
                )
    pd.DataFrame(cond).to_csv(TABLES / "e4_conditioning.csv", index=False)

    # ---- E4-D transitions
    T = fams["E4D_TIMELINE"]
    tl_dir = WORK / "predictions" / "E4D_TIMELINE"
    tbus = pd.read_parquet(tl_dir / f"{NET}_predictions.parquet")
    tbr = pd.read_parquet(tl_dir / f"{NET}_branch_predictions.parquet")
    meta = T[["scenario", "slot", "p_hv_injected_mw"]].copy()
    pairs = tr.consecutive_pairs(meta)
    trans = tr.transition_metrics(tbus, tbr, pairs)
    trans["block"] = pd.to_datetime(trans["slot_i"], utc=True).dt.strftime("%Y-%m-%d")
    trans["event"] = tag_events(trans["slot_j"], ev)
    prim = trans[trans["within_halfhour"]].copy()
    prim["ramp_bin"] = tr.ramp_bins(
        prim["abs_dPV_injected_mw"], RA["ramp_bins"]["quantiles"], RA["ramp_bins"]["labels"]
    )
    rc = []
    for lab, g in prim.groupby("ramp_bin", observed=True):
        r = {
            "ramp_bin": str(lab),
            "n": len(g),
            "abs_dPV_range_mw": "{:.3f}–{:.3f}".format(
                g["abs_dPV_injected_mw"].min(), g["abs_dPV_injected_mw"].max()
            ),
        }
        for c in [
            "dP_err_mean_abs",
            "dP_ac_mean_abs",
            "dVm_err_mean_abs",
            "dVm_ac_mean_abs",
            "dVa_err_mean_abs",
            "dVa_ac_mean_abs",
            "dQ_err_mean_abs",
        ]:
            ci = st.block_mean_ci(g[c], g["block"], BOOT["resamples"], BOOT["seed"])
            r[c], r[f"{c}_ci"] = ci["mean"], [round(ci["ci_low"], 6), round(ci["ci_high"], 6)]
        r["dP_tracking_ratio_median"] = float(g["dP_tracking_ratio"].median())
        rc.append(r)
    # steady-state error of the END state by ramp bin (same pairs)
    pe = T.set_index("scenario")
    prim["PBE_mean_j"] = pe.loc[prim["scenario_j"], "PBE_mean"].to_numpy()
    for r in rc:
        g = prim[prim["ramp_bin"].astype(str) == r["ramp_bin"]]
        r["end_state_PBE_mean"] = float(g["PBE_mean_j"].mean())
    rc = pd.DataFrame(rc)
    rc.to_csv(TABLES / "e4_ramp_conditioned.csv", index=False)
    ev_rows = []
    for e in ev.itertuples():
        g = trans[trans["event"].fillna("").str.contains(e.event_id)]
        s = T[
            (pd.to_datetime(T["slot"], utc=True) >= e.start)
            & (pd.to_datetime(T["slot"], utc=True) <= e.end)
        ]
        ev_rows.append(
            {
                "event_id": e.event_id,
                "class": e.event_class,
                "states": len(s),
                "transitions": len(g),
                "max_abs_dPV_mw": float(g["abs_dPV_injected_mw"].max()) if len(g) else np.nan,
                "dP_err_mean_abs": float(g["dP_err_mean_abs"].mean()) if len(g) else np.nan,
                "dVm_err_mean_abs": float(g["dVm_err_mean_abs"].mean()) if len(g) else np.nan,
                "dP_tracking_ratio_median": float(g["dP_tracking_ratio"].median())
                if len(g)
                else np.nan,
                "PBE_mean": float(s["PBE_mean"].mean()) if len(s) else np.nan,
                "V_error": float(s["V_error"].mean()) if len(s) else np.nan,
            }
        )
    pd.DataFrame(ev_rows).to_csv(TABLES / "e4_transitions_by_event.csv", index=False)
    all_trans = {
        "all_pairs": int(len(trans)),
        "within_halfhour": int(len(prim)),
        "dP_err_within": float(prim["dP_err_mean_abs"].mean()),
        "dP_ac_within": float(prim["dP_ac_mean_abs"].mean()),
        "dP_err_crossing": float(trans.loc[~trans["within_halfhour"], "dP_err_mean_abs"].mean()),
        "dP_ac_crossing": float(trans.loc[~trans["within_halfhour"], "dP_ac_mean_abs"].mean()),
        "pairs_with_branch_set_change": int((~trans["same_branch_set"]).sum()),
    }

    # ---- hero events (UI-ready CSV + figure)
    not_evaluable: dict[str, str] = {}
    hero_dir = OUT / "hero"
    hero_dir.mkdir(parents=True, exist_ok=True)
    ref_bus = tbus[tbus["REF"] == 1][["scenario", "Pg_target", "Pg_pred"]].set_index("scenario")
    for eid in RA["events"]["hero"]:
        e = ev[ev["event_id"] == eid]
        if e.empty:
            continue
        e = e.iloc[0]
        s = T[
            (pd.to_datetime(T["slot"], utc=True) >= e.start)
            & (pd.to_datetime(T["slot"], utc=True) <= e.end)
        ].sort_values("slot")
        if s.empty:  # e.g. UKPN base inputs missing in the window: reported, never substituted
            not_evaluable[eid] = "no complete E2 base state in the event window"
            continue
        s = s.join(ref_bus, on="scenario")
        cols = [
            "slot",
            "fleet_pv_mw",
            "p_hv_injected_mw",
            "fleet_cf",
            "mean_kc",
            "Pg_target",
            "Pg_pred",
            "PBE_mean",
            "V_error",
            "angle_error",
            "branch_P_error",
            "max_loading_ac",
            "max_loading_error",
            "dc_P_residual",
        ]
        s[[c for c in cols if c in s]].rename(
            columns={"Pg_target": "ac_import_mw", "Pg_pred": "genco_import_mw"}
        ).to_csv(hero_dir / f"{eid}.csv", index=False)
        fig, ax = plt.subplots(3, 1, figsize=(8, 7.5), sharex=True)
        t = pd.to_datetime(s["slot"], utc=True)
        ax[0].plot(t, s["fleet_pv_mw"], "o-", label="fleet PV (satellite-driven estimate)")
        ax[0].plot(t, s["p_hv_injected_mw"], "s--", label="injected at 33 kV (model)")
        ax[0].set_ylabel("MW")
        ax[0].legend(fontsize=7)
        ax[1].plot(t, s["Pg_target"], "o-", label="AC reference (PowerModels)")
        ax[1].plot(t, s["Pg_pred"], "x--", label="GENCO zero-shot")
        ax[1].set_ylabel("grid import (MW)")
        ax[1].legend(fontsize=7)
        ax[2].plot(t, s["PBE_mean"], "o-", label="GENCO PBE mean (MVA)")
        ax[2].plot(t, s["dc_P_residual"], "x--", label="DC-PF active residual (MW)")
        ax[2].set_ylabel("error")
        ax[2].legend(fontsize=7)
        fig.suptitle(
            f"{eid} ({e['class_name']}) — Sundon 33 kV, satellite-driven states", fontsize=9
        )
        fig.text(
            0.01,
            0.005,
            "PV: EUMETSAT LSA SAF MDSSFTD → pvlib (estimate). Network: UKPN "
            "(CC BY 4.0). GENCO: gridfm/genco-pf-transfer.",
            fontsize=6,
        )
        fig.autofmt_xdate()
        fig.tight_layout(rect=(0, 0.02, 1, 0.97))
        fig.savefig(FIGS / f"e4_hero_{eid}.png", dpi=120)
        plt.close(fig)

    # ---- runtime
    rt = []
    for f, m in {**fams, "S2_MATCHED_PV_CONTROL": S2}.items():
        rt.append(
            {
                "family": f,
                "genco_s_per_scenario_incl_startup": float(m["genco_runtime_s"].mean()),
                "ac_powermodels_s": float(m["pm_runtime_s"].mean())
                if "pm_runtime_s" in m
                else np.nan,
                "ac_pandapower_s": float(m["pp_runtime_s"].mean())
                if "pp_runtime_s" in m
                else np.nan,
            }
        )
    pd.DataFrame(rt).to_csv(TABLES / "e4_runtime.csv", index=False)

    # ---- figures: distributions
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))
    for ax, c, unit in zip(
        axes, ["PBE_mean", "V_error", "branch_P_error"], ["MVA", "pu", "MW"], strict=True
    ):
        data = [S0[c].dropna(), S1[c].dropna(), S2[c].dropna()]
        ax.boxplot(data, tick_labels=["S0 synthetic", "S1 weather", "S2 control"], showfliers=False)
        ax.set_title(f"{c} ({unit})", fontsize=9)
    fig.suptitle("GENCO zero-shot on Sundon: per-scenario error by family", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIGS / "e4_family_distributions.png", dpi=120)
    plt.close(fig)
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.6))
    ax[0].bar(
        rc["ramp_bin"],
        rc["dP_err_mean_abs"],
        yerr=np.abs(
            np.array(rc["dP_err_mean_abs_ci"].tolist()).T - rc["dP_err_mean_abs"].to_numpy()
        ),
        capsize=3,
        label="GENCO ΔP error",
    )
    ax[0].plot(rc["ramp_bin"], rc["dP_ac_mean_abs"], "ko-", label="AC |ΔP| (true change)")
    ax[0].set_ylabel("MW per directed edge")
    ax[0].legend(fontsize=7)
    ax[0].set_title("Branch-P change tracking vs PV ramp (within half-hour)", fontsize=9)
    ax[1].bar(rc["ramp_bin"], rc["dVm_err_mean_abs"], label="GENCO ΔVm error")
    ax[1].plot(rc["ramp_bin"], rc["dVm_ac_mean_abs"], "ko-", label="AC |ΔVm|")
    ax[1].set_ylabel("pu")
    ax[1].legend(fontsize=7)
    ax[1].set_title("Voltage change tracking vs PV ramp", fontsize=9)
    fig.tight_layout()
    fig.savefig(FIGS / "e4_ramp_conditioned.png", dpi=120)
    plt.close(fig)

    # ---- decision (pre-registered)
    s0row = summary[summary.family == "S0_STANDARD_SYNTHETIC"].iloc[0]
    s1row = summary[summary.family == "S1_WEATHER_ALIGNED"].iloc[0]
    topology_poor = bool(s0row["P_residual"] > s0row["dc_P_residual"])
    prim_gap = gaps[(gaps.metric == "PBE_mean") & gaps.comparison.str.startswith("S1 − S2")].iloc[0]
    weather_gap = bool(prim_gap["material"])
    outcomes = []
    if topology_poor:
        outcomes.append("B_TOPOLOGY_SHIFT_DOMINATES")
    if weather_gap:
        outcomes.append("C_WEATHER_SPECIFIC_GAP")
    else:
        outcomes.append("D_NO_MATERIAL_WEATHER_GAP")
    if not topology_poor and not weather_gap:
        outcomes.insert(0, "A_ZERO_SHOT_SUFFICIENT")

    # ---- donors (deterministic regeneration for all seeds) + registry
    from cloud2grid.network.states import StateBuilder  # noqa: PLC0415
    from cloud2grid.scenarios.weather import load_forcing, populations  # noqa: PLC0415

    pvm = yaml.safe_load((REPO_ROOT / MC["forcing"]["pv_model"]).read_text())
    forcing = load_forcing(pvm, REPO_ROOT / MC["forcing"]["pv_series"])
    primary = populations(
        StateBuilder(REPO_ROOT / MC["network"]["interpretation"]),
        forcing,
        MC["primary_population"]["period"],
    )["primary"]
    donors = pd.concat([assign_donors(primary, s) for s in S2_SEEDS], ignore_index=True)
    donors.to_parquet(FAMDIR / "S2_donors.parquet", index=False)
    fam_json = {p.stem: json.loads(p.read_text()) for p in FAMDIR.glob("*.json")}
    env = runner.environment()
    registry = {
        "schema": "cloud2grid scenario registry v1",
        "genco_checkpoint": {
            **ZS["model"],
            "graphkit_revision": ZS["graphkit"]["package_revision"],
        },
        "normalizer": ZS["normalizer"]["policy"] + " (fitted on S0_STANDARD_SYNTHETIC)",
        "slack_limits_mva": ZS["slack_limits_mva"],
        "commit_at_evaluation": env["git_commit"],
        "families": {
            "S0_STANDARD_SYNTHETIC": {
                "definition": "gridfm-datakit official pf_small recipe on the E1 "
                "Sundon case (LTDS planning peak)",
                "config": "configs/experiments/e4_zero_shot.yaml#s0_standard_synthetic",
                "source_data": ZS["s0_standard_synthetic"]["network_file"],
                "seed": ZS["s0_standard_synthetic"]["seeds"],
                "scenario_count": fam_json["S0_STANDARD_SYNTHETIC"]["accepted"],
                "pv_treatment": "none (synthetic load scaling; no PV)",
                "load_treatment": "agg_load_profile × feasible scaling (1.2–2.0 × planning "
                "peak), N-1 + admittance perturbations",
                "commit": fam_json["S0_STANDARD_SYNTHETIC"]["git_commit"],
            },
            "S1_WEATHER_ALIGNED": {
                "definition": MC["families"]["S1_WEATHER_ALIGNED"]["definition"],
                "config": "configs/experiments/e4_matched_control.yaml",
                "source_data": [
                    MC["forcing"]["pv_series"],
                    "UKPN half-hourly operational data (E2)",
                ],
                "seed": None,
                "scenario_count": fam_json["S1_WEATHER_ALIGNED"]["accepted"],
                "pv_treatment": "HV (6 MW) explicit sgen from slot T; "
                "embedded PV inside observed loads",
                "load_treatment": "observed half-hour T (E2 construction, interpretation "
                "sundon_capacity_scaled_with_outages)",
                "commit": fam_json["S1_WEATHER_ALIGNED"]["git_commit"],
            },
            "S1_WEATHER_ALIGNED_BASE_LTDS": {
                "definition": "S1 on the preserved sundon_base_ltds reference",
                "scenario_count": fam_json["S1_WEATHER_ALIGNED_BASE_LTDS"]["accepted"],
                "commit": fam_json["S1_WEATHER_ALIGNED_BASE_LTDS"]["git_commit"],
            },
            "S2_MATCHED_PV_CONTROL": {
                "definition": MC["families"]["S2_MATCHED_PV_CONTROL"]["definition"],
                "name_in_reports": MC["families"]["S2_MATCHED_PV_CONTROL"]["name_in_reports"],
                "config": "configs/experiments/e4_matched_control.yaml",
                "seed": S2_SEEDS,
                "scenario_count": {
                    s: fam_json[f"S2_MATCHED_PV_CONTROL_s{s}"]["accepted"] for s in S2_SEEDS
                },
                "pv_treatment": "donor slot PV (same month × UTC time of day, other "
                "day); HV sgen + embedded transplant",
                "load_treatment": "observed half-hour T (same base states as S1)",
                "commit": fam_json[f"S2_MATCHED_PV_CONTROL_s{S2_SEEDS[0]}"]["git_commit"],
            },
            "E4D_TIMELINE": {
                "definition": RA["timeline"]["states"],
                "scenario_count": fam_json["E4D_TIMELINE"]["accepted"],
                "commit": fam_json["E4D_TIMELINE"]["git_commit"],
            },
        },
        "not_created": {
            "spatial_shuffle": MC["spatial_shuffle"],
            "overcast_control": "No valid overcast control under E3-v1 criteria",
        },
    }
    (REPO_ROOT / "metadata/scenario_registry.yaml").write_text(
        yaml.safe_dump(registry, sort_keys=False, allow_unicode=True)
    )

    result = {
        "families": fam_json,
        "summary_primary": summary.set_index("family")[
            ["n", "PBE_mean", "P_residual", "dc_P_residual", "V_error"]
        ].to_dict("index"),
        "topology_poor": topology_poor,
        "weather_gap_material": weather_gap,
        "decision": outcomes,
        "primary_gap_S1_vs_S2": prim_gap.to_dict(),
        "s0_vs_s1_PBE": gaps[
            (gaps.metric == "PBE_mean") & gaps.comparison.str.startswith("S1 − S0")
        ]
        .iloc[0]
        .to_dict(),
        "detection": {
            f: overload_detection(m)
            for f, m in {**fams, "S2_MATCHED_PV_CONTROL": S2}.items()
            if "overload_ac" in m
        },
        "transitions": all_trans,
        "hero_not_evaluable": not_evaluable,
        "environment": env,
        "s1_vs_s1_base_ltds_PBE": [
            float(s1row["PBE_mean"]),
            float(summary[summary.family == "S1_WEATHER_ALIGNED_BASE_LTDS"].iloc[0]["PBE_mean"]),
        ],
    }
    (OUT / "evaluation.json").write_text(json.dumps(result, indent=2, default=str))
    print(
        json.dumps(
            {k: result[k] for k in ("topology_poor", "weather_gap_material", "decision")}, indent=1
        )
    )
    print(
        summary[
            [
                "family",
                "n",
                "PBE_mean",
                "P_residual",
                "dc_P_residual",
                "V_error",
                "angle_error",
                "branch_P_error",
            ]
        ]
        .round(4)
        .to_string(index=False)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

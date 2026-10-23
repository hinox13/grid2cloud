# ruff: noqa: E501
"""Freeze the research results the React site states beyond the Explorer bundles into data/demo/research.

    .venv/bin/python scripts/web/build_research_bundle.py           # writes data/demo/research/*.json
    .venv/bin/python scripts/web/build_research_bundle.py --check   # exit 1 if the bundle is stale

Three small JSON files, each reshaped (never re-estimated) from frozen research outputs:

- sundon_runs.json        every E5d run and the frozen E5c reference on the 2,829 S1 states
                          (reports/tables/e5d_postfreeze_runs_real.csv, published with E5d);
- economic_qualifiers.json signed composition, coverage and per-half-hour accuracy of the economic study
                          (reports/economic_impact/tables/periods.csv, the released per-half-hour table);
- cancellation.json       the published E6 pair-level error-cancellation diagnostic for the frozen E5d
                          (reports/tables/e6_pair_level_cancellation.csv);
- second_network.json     the Aylesbury East study: feasibility pixel geometry, the failed real-operation
                          validation and the synthetic G2A-S replication (reports/g2, reports/g2a_*,
                          metadata/g2a_checkpoint_registry.yaml). No row of an unpublished experiment is read or written.

Output is deterministic; scripts/web/export_web_data.py reads these files like any other data/demo bundle.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/demo/research"
H = 0.5  # hours per settlement period


def r(x: float, d: int = 6) -> float | None:
    x = float(x)
    return None if not np.isfinite(x) else round(x, d)


def dump(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, allow_nan=False) + "\n"


# ----------------------------------------------------------------------------- Sundon runs
def sundon_runs() -> dict:
    src = "reports/tables/e5d_postfreeze_runs_real.csv"
    t = pd.read_csv(ROOT / src)
    cols = [
        "n",
        "PBE_mean",
        "P_residual",
        "V_error",
        "import_mae_mw",
        "import_bias_mw",
        "import_corr",
        "genco_slope_pv",
        "ac_slope_pv",
        "pv_slope_ratio",
        "load_slope_ratio",
        "chap31_slope_ratio",
        "branch_pv_slope_median_abs_err",
        "bus_Va_pv_slope_median_abs_err",
        "bus_Va_pv_slope_ac_median_abs",
        "bus_Vm_pv_slope_median_abs_err",
        "bus_Vm_pv_slope_ac_median_abs",
    ]
    label = {
        "E5c": ("E5c", None, None, "frozen generator-aware reference (ordinary loss)"),
        "e5d_l1_s0": (
            "E5d",
            1.0,
            0,
            "selected on synthetic data (flagged), frozen before any real state",
        ),
        "e5d_l1_s1": ("E5d", 1.0, 1, "same recipe, seed 1"),
        "e5d_l1_s2": ("E5d", 1.0, 2, "same recipe, seed 2"),
        "e5d_l0.3_s0": (
            "E5d",
            0.3,
            0,
            "weaker response weight; post-freeze diagnostic, never selected",
        ),
        "e5d_l3_s0": ("E5d", 3.0, 0, "stronger response weight; post-freeze diagnostic"),
        "e5d_l0_s0": (
            "E5d",
            0.0,
            0,
            "λ = 0 control: same code, ordinary loss; unstable on real states, slope not interpretable",
        ),
    }
    runs = []
    for row in t.to_dict("records"):
        exp, lam, seed, note = label[row["model"]]
        runs.append(
            {
                "run": row["model"],
                "experiment": exp,
                "lambda": lam,
                "seed": seed,
                "selected": bool(row["selected"]),
                "note": note,
                **{c: r(row[c]) for c in cols},
            }
        )
    return {
        "note": "Every E5d run and the frozen E5c checkpoint on the same 2,829 observation-informed, AC-reconstructed Sundon states (S1). Report-only post-freeze diagnostics: nothing here fed selection or a verdict.",
        "source": src,
        "report": "reports/e5d_real_transfer.md §5",
        "synthetic_lambda0_pv_ratio": 0.001,
        "synthetic_lambda0_source": "reports/e5d_synthetic_response.md (held-out synthetic PV pairs)",
        "runs": runs,
    }


# ----------------------------------------------------------------------------- economic qualifiers
def economic_qualifiers() -> dict:
    src = "reports/economic_impact/tables/periods.csv"
    P = pd.read_csv(ROOT / src, parse_dates=["slot"])
    P["date"] = P.slot.dt.date
    apx = P.apx_gbp_mwh
    cl = P.dcl_AC
    neg = cl < 0
    per_day = P.groupby("date").size()
    m0, m1 = (
        P.slot.min().tz_convert(None).to_period("M"),
        P.slot.max().tz_convert(None).to_period("M"),
    )
    days_span = (
        m1.end_time.normalize() - m0.start_time.normalize()
    ).days + 1  # calendar months covered
    acc: dict[str, dict] = {}
    for q, lab in (("dpv", "pv_attributed"), ("dcl", "cloud_attributed")):
        acc[lab] = {}
        for m in ("accounting", "E5d", "E5c"):
            e = (P[f"{q}_{m}"] - P[f"{q}_AC"]).abs()
            acc[lab][m] = {"period_mae_mw": r(e.mean()), "share_closer_than_E5d": None}
        closer = (P[f"{q}_accounting"] - P[f"{q}_AC"]).abs() < (P[f"{q}_E5d"] - P[f"{q}_AC"]).abs()
        acc[lab]["accounting"]["share_closer_than_E5d"] = r(closer.mean())
        ac_val = (P[f"{q}_AC"] * H * apx).sum()
        for m in ("accounting", "E5d", "E5c"):
            acc[lab][m]["value_error_pct"] = r(
                100 * ((P[f"{q}_{m}"] * H * apx).sum() - ac_val) / ac_val
            )
    return {
        "note": "Qualifiers of the economic case study (one explicit 6 MW plant), recomputed from the released per-half-hour table. Energy = MW × 0.5 h; value = energy × APX price of the same settlement period; signed sums.",
        "source": src,
        "periods": int(len(P)),
        "days_with_periods": int(P.date.nunique()),
        "days_in_months_covered": int(days_span),
        "periods_per_day": {
            "min": int(per_day.min()),
            "median": r(per_day.median(), 1),
            "max": int(per_day.max()),
        },
        "periods_by_month": {
            pd.Timestamp(2024, int(k), 1).strftime("%B"): int(v)
            for k, v in P.groupby(P.slot.dt.month).size().items()
        },
        "utc_first_last": [P.slot.dt.strftime("%H:%M").min(), P.slot.dt.strftime("%H:%M").max()],
        "apx_missing_periods": int(apx.isna().sum()),
        "apx_negative_periods": int((apx < 0).sum()),
        "apx_min_gbp_mwh": r(apx.min(), 2),
        "apx_max_gbp_mwh": r(apx.max(), 2),
        "cloud": {
            "net_mwh": r((cl * H).sum(), 4),
            "net_gbp": r((cl * H * apx).sum(), 2),
            "negative_periods": int(neg.sum()),
            "negative_mwh": r((cl[neg] * H).sum(), 4),
            "negative_gbp": r((cl[neg] * H * apx[neg]).sum(), 2),
            "positive_mwh": r((cl[~neg] * H).sum(), 4),
            "negative_value_contributions": int(((cl * H * apx) < 0).sum()),
            "meaning_of_negative": "the satellite-derived output exceeded the modelled clear-sky estimate: possibly cloud enhancement, possibly a disagreement between the satellite-derived estimate and the clear-sky model; not evidence that clouds raised generation in every such half-hour",
        },
        "plant": {
            "net_mwh": r((P.dpv_AC * H).sum(), 4),
            "net_gbp": r((P.dpv_AC * H * apx).sum(), 2),
            "negative_periods": int((P.dpv_AC < 0).sum()),
            "negative_value_contributions": int(((P.dpv_AC * H * apx) < 0).sum()),
            "negative_value_gbp": r((P.dpv_AC * H * apx).clip(upper=0).sum(), 2),
            "estimated_output_mwh": r((P.pv_mw * H).sum(), 4),
            "import_with_plant_mwh": r((P.I_AC * H).sum(), 4),
            "share_of_no_plant_import": r(
                (P.dpv_AC * H).sum() / ((P.I_AC * H).sum() + (P.dpv_AC * H).sum())
            ),
            "meaning": "AC import with the plant removed minus AC import as reconstructed, over the same half-hours; the share is that difference divided by the no-plant import",
        },
        "accuracy": acc,
    }


# ----------------------------------------------------------------------------- second network
def second_network() -> dict:
    G = ROOT / "reports/g2"
    A = pd.read_csv(G / "s/metrics_absolute.csv")
    Pm = pd.read_csv(G / "s/metrics_pairs.csv")
    hyp = json.loads((G / "s/hypotheses.json").read_text())
    netm = json.loads((G / "s/network.json").read_text())
    struct = json.loads((G / "a/e1_structural_validation.json").read_text())["checks"]
    val = json.loads((G / "a/validation_summary.json").read_text())
    assets = pd.read_csv(G / "a/pv_assets.csv")
    reg = yaml.safe_load((ROOT / "metadata/g2a_checkpoint_registry.yaml").read_text())
    act = assets[assets.activity_search_start == "ACTIVE"]
    by_px = (
        act.groupby("native_pixel_id").active_capacity_search_mw.sum().sort_values(ascending=False)
    )
    arm_name = {
        "A": "zero-shot",
        "B": "ordinary adaptation, generation as negative demand (E5b-like)",
        "C": "ordinary adaptation, explicit generators (E5c-like)",
        "D": "response-aware (E5d recipe)",
    }

    def runs_abs() -> list[dict]:
        out = []
        for row in A[A.arm.isin(["B", "C", "D"])].to_dict("records"):
            pv = Pm[(Pm.run == row["run"]) & (Pm.probe_type == "pv")].iloc[0]
            ld = Pm[(Pm.run == row["run"]) & (Pm.probe_type == "load")].iloc[0]
            out.append(
                {
                    "run": row["run"],
                    "arm": row["arm"],
                    "seed": None if pd.isna(row["seed"]) else int(row["seed"]),
                    "encoding": row["encoding"],
                    "import_mae_mw": r(row["import_mae_mw"]),
                    "import_bias_mw": r(row["import_bias_mw"]),
                    "import_r": r(row["import_r"]),
                    "pbe_mean_mva": r(row["pbe_mean_mva"]),
                    "vm_mae_pu": r(row["vm_mae_pu"]),
                    "export_recall": r(row["export_recall"]),
                    "import_mae_over_ac_std": r(row["import_mae_over_ac_std"]),
                    "pred_vs_ac_slope": r(row["pred_vs_ac_slope"]),
                    "sign_coherence": r(row["sign_coherence"]),
                    "pv_slope_ratio": r(pv.import_slope_ratio),
                    "pv_rel_err": r(pv.import_rel_err),
                    "pv_change_err_mw": r(pv.delta_err_mae_mw),
                    "load_slope_ratio": r(ld.import_slope_ratio),
                }
            )
        return out

    ref = A[A.run == "g2a_D_s2"].iloc[0]
    headline = {v["arm"]: k for k, v in reg["runs"].items() if v.get("headline_for_arm")}
    return {
        "note": "Aylesbury East, a second UKPN 33 kV network. The replication is SYNTHETIC: AC power-flow states sampled from static public metadata, with AC as the reference. The real-operation reconstruction failed its pre-registered validation, so nothing here concerns real 2024 operation, real transfer or weather.",
        "sources": [
            "reports/g2/SECOND_NETWORK_REPORT.md",
            "reports/g2a_aylesbury_validation.md",
            "reports/g2/s/metrics_absolute.csv",
            "reports/g2/s/metrics_pairs.csv",
            "reports/g2/s/hypotheses.json",
            "reports/g2/s/network.json",
            "reports/g2/a/e1_structural_validation.json",
            "reports/g2/a/validation_summary.json",
            "reports/g2/a/pv_assets.csv",
            "metadata/g2a_checkpoint_registry.yaml",
        ],
        "network": {
            "name": "Aylesbury East Grid 33 kV",
            "buses_built": struct["unique_scoped_bus_ids"]["detail"]["n_buses"],
            "buses_genco_graph": netm["n_bus_datakit"],
            "lines": struct["line_endpoints_valid"]["detail"]["n_lines"],
            "transformers": struct["trafo_endpoints_valid"]["detail"]["n_trafos"],
            "synthetic_generation_mw": {k: r(v, 3) for k, v in netm["hv_capacity_mw"].items()},
            "synthetic_generation_total_mw": r(sum(netm["hv_capacity_mw"].values()), 3),
            "battery": False,
            "sundon_buses_built": 38,
            "sundon_buses_genco_graph": 37,
            "sundon_note": "Sundon: 38 buses as built, 37 in the GENCO graph (the 132 kV coupler fuses); the same E1 code built both networks.",
        },
        "satellite_pv": {
            "active_assets": int(len(act)),
            "active_mw": r(act.active_capacity_search_mw.sum(), 4),
            "native_pixels_with_active_pv": int((by_px > 0).sum()),
            "largest_pixel": by_px.index[0],
            "largest_pixel_mw": r(by_px.iloc[0], 4),
            "largest_pixel_share": r(by_px.iloc[0] / by_px.sum(), 4),
            "feasibility_F5": "fail (pre-registered: at least 3 native pixels carrying the solar)",
        },
        "real_validation": {
            "level": val["level"],
            "decision": val["decision"],
            "import_nmae": r(val["criteria"]["import_nmae"], 4),
            "import_nmae_max": 0.25,
            "core_circuit_share": r(val["criteria"]["core_fit_share_B"], 4),
            "core_circuit_share_min": 0.60,
            "direction_min": r(val["criteria"]["direction_min"], 4),
            "direction_min_required": 0.90,
            "residual_vs_pv_r": r(val["criteria"]["residual_vs_pv_r"], 4),
            "residual_vs_pv_r_max": 0.50,
            "real_states": val["real_evaluation_states"],
            "posthoc_observed_pv_slope": -0.51,
            "posthoc_note": "post-hoc regression in reports/g2a_aylesbury_validation.md (1,837 daylight half-hours): the measured import falls about 0.51 MW per MW of satellite PV, against about 1.0 in the model",
        },
        "replication": {
            "classification": hyp["classification"],
            "hypotheses": {
                k: bool(hyp[k]["holds"]) if "holds" in hyp[k] else bool(hyp[k].get("stable"))
                for k in ("H1", "H2", "H3", "H4", "H5", "H6", "H7")
            },
            "hypothesis_text": {
                "H1": "zero-shot active residual at least 10 × DC power flow",
                "H2": "ordinary adaptation cuts power-balance error to at most 0.1 × zero-shot",
                "H3": "ordinary adaptation stays largely PV-insensitive (slope ratio ≤ 0.25 in ≥ 2 of 3 seeds)",
                "H4": "response-aware training recovers the AC PV response (ratio 0.8–1.2, rel. error ≤ 0.25) in ≥ 2 of 3 seeds",
                "H5": "the response-aware model keeps a substantial absolute import error (MAE > 5 MW)",
                "H6": "its nodal mismatches are sign-coherent (≥ 0.5)",
                "H7": "the response is recovered in all three seeds (stability)",
            },
            "test_states": int(ref.n),
            "export_states": int(ref.n_export_states),
            "ac_import_std_mw": r(ref.ac_import_std_mw, 3),
            "pairs_per_type": int(
                Pm[(Pm.run == "g2a_D_s2") & (Pm.probe_type == "pv")].n_pairs.iloc[0]
            ),
            "arms": arm_name,
            "headline_runs": headline,
            "runs": runs_abs(),
            "zero_shot": {
                r_["encoding"]: {
                    "import_mae_mw": r(r_["import_mae_mw"]),
                    "pbe_mean_mva": r(r_["pbe_mean_mva"]),
                    "import_mae_over_ac_std": r(r_["import_mae_over_ac_std"]),
                }
                for r_ in A[A.arm == "A"].to_dict("records")
            },
            "decoder_note": "Arms C and D use GraphKit's corrected generator decoder; Sundon's E5c/E5d used the original one, so the cross-network numbers are only roughly comparable.",
            "training": "independent network-specific fine-tuning from the same pretrained GENCO checkpoint (n_train 10,000; 3 seeds per arm; selected on synthetic validation; frozen before the test). Not zero-shot transfer of the Sundon model.",
        },
    }


# ----------------------------------------------------------------------------- error cancellation (E6 diagnostic)
def cancellation() -> dict:
    src = "reports/tables/e6_pair_level_cancellation.csv"
    t = pd.read_csv(ROOT / src)
    r_ = t[(t.model == "E5d λ1 s0 (frozen)") & (t.probe_type == "pv")].iloc[0]
    return {
        "note": "Published post-hoc diagnostic (reports/e6_feasibility_diagnostic.md), not pre-registered: on 500 held-out synthetic pairs differing only in PV, the frozen E5d model's absolute import errors in the two states of a pair, and the error of the predicted PV-induced change. A measured observation, not an isolated causal mechanism.",
        "source": src,
        "model": "E5d λ1 s0 (frozen)",
        "population": "held-out synthetic PV pairs",
        "n_pairs": int(r_.n_pairs),
        "corr_err_A_err_B": r(r_.corr_err_A_err_B),
        "level_mae_member_A_mw": r(r_.level_mae_member_A_mw),
        "delta_err_mae_mw": r(r_.delta_err_mae_mw),
        "mean_abs_delta_ac_mw": r(r_.mean_abs_delta_ac_mw),
    }


FILES = {
    "sundon_runs.json": sundon_runs,
    "cancellation.json": cancellation,
    "economic_qualifiers.json": economic_qualifiers,
    "second_network.json": second_network,
}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    stale = []
    for name, fn in FILES.items():
        text = dump(fn())
        p = OUT / name
        if a.check:
            if not p.exists() or p.read_text() != text:
                stale.append(name)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
    if a.check:
        if stale:
            print("STALE:", *stale)
            return 1
        print("research bundle up to date")
    else:
        print(f"wrote {len(FILES)} files to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

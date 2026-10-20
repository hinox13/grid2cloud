# ruff: noqa: E501  (claims table: one quoted sentence and its source expression per line)
"""Check every number quoted in the Cloud2Grid write-up against the frozen sources.

    python submission/check_post.py        # exits non-zero on any mismatch

Each claim pairs the exact text used in the post with a value recomputed here from a frozen
table, report JSON or verification record (paths relative to the repository root). A claim
passes when (1) the recomputed value, formatted as in the post, equals the quoted text and
(2) that text occurs in every rendered variant. Nothing is re-fitted or re-simulated.

The approved constructive text (Cloud2Grid_submission_final.md, and the README rendered from it by
render_readme.py) words a few items differently. For those variants the alternative wording in
REPHRASE / TABLE_LABEL is required instead, and it is recomputed from the same source; claims kept
in a collapsible block elsewhere must be replaced there by a link to their report. Every claim must
be checked in at least one variant.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "submission"
T = ROOT / "reports/tables"
TITLE = "Cloud2Grid: from real clouds to electric grid intelligence"
# rendered variants present in this checkout (development: all three; publication: README files only)
VARIANTS = [p for p in (HERE / "README.md", HERE / "Cloud2Grid_HuggingFace_READY.md", HERE / "promotion/README.md",
                        HERE / "Cloud2Grid_submission_final.md", ROOT / "README.md") if p.exists() and TITLE in p.read_text()]
CONSTRUCTIVE = {str(p.relative_to(ROOT)) for p in (HERE / "Cloud2Grid_submission_final.md", ROOT / "README.md")}


def j(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text())


rt = pd.read_csv(T / "e5d_real_transfer.csv").set_index("model")
ZS, E5, E5B, E5C, E5D = "zero-shot (E4)", "E5", "E5b", "E5c", "E5d"
e4 = pd.read_csv(T / "e4_family_summary.csv").set_index("family").loc["S0_STANDARD_SYNTHETIC"]
e5s = pd.read_csv(T / "e5_synthetic_summary.csv").set_index("run")
pr = pd.read_csv(T / "e5d_response_probes.csv")
pv_ratio = pr[(pr.probe_type == "pv") & (pr.magnitude_class == "all") & (pr.family == "import")]
pv_ratio = pv_ratio[pv_ratio.target == "pairs_test"].set_index("run").slope_ratio
e6c = pd.read_csv(T / "e6_model_comparison.csv")
e6 = e6c[(e6c.population == "E5c held-out synthetic test") & (e6c.model == "E5d λ1 s0 (frozen)")].iloc[0]
pl = pd.read_csv(T / "e6_pair_level_cancellation.csv")
pl = pl[(pl.model == "E5d λ1 s0 (frozen)") & (pl.probe_type == "pv")].iloc[0]
pb = pd.read_csv(T / "e6_physical_baselines.csv").set_index("estimate")
e1 = j("reports/experiments/e1_network/summary.json")
e2 = j("reports/experiments/e2_validation/summary.json")
e3 = j("reports/experiments/e3_satellite/pv_timeseries.json")
cpu = j("reports/model_release_v1/cleanroom_cpu/verification_results.json")
gpu = j("reports/model_release_v1/cleanroom_gpu/verification_results.json")
N_REPRO = {k: sum(bool(c["independently_reproduced"]) for c in d["claims"]) for k, d in (("cpu", cpu), ("gpu", gpu))}
# the fresh E5d PV ratio is recorded in the clean-room report's key-metric table only
_row = next(r for r in (ROOT / "reports/model_release_v1/cleanroom_cpu/verification_report.md").read_text().splitlines()
            if r.startswith("| pv.import.slope_ratio |"))
CPU_RATIO = float(_row.strip("|").split("|")[4])  # columns: E5c published, E5c fresh, E5d published, E5d fresh


def fmt(v: float, spec: str) -> str:
    return format(v, spec).replace("-", "−")


CLAIMS: list[tuple[str, str, str]] = [
    # (what, quoted text, recomputed text)
    ("real states n", "2,829", f"{int(rt.loc[E5D, 'n']):,}"),
    ("zero-shot predicted export", "exports about 211 MW", f"exports about {-rt.loc[ZS, 'genco_import_mean_mw']:.0f} MW"),
    ("AC mean import", "imports about 49 MW", f"imports about {rt.loc[ZS, 'ac_import_mean_mw']:.0f} MW"),
    ("zero-shot wrong direction", "99.9 % of states", f"{(1 - rt.loc[ZS, 'import_sign_accuracy']) * 100:.1f} % of states"),
    ("E5d PV slope vs AC", "−1.07 MW per MW of PV, against −1.02 in AC",
     f"{fmt(rt.loc[E5D, 'genco_slope_pv'], '.2f')} MW per MW of PV, against {fmt(rt.loc[E5D, 'ac_slope_pv'], '.2f')} in AC"),
    ("E5c PV slope", "(−0.04 without it)", f"({fmt(rt.loc[E5C, 'genco_slope_pv'], '.2f')} without it)"),
    ("E5d bias", "13.1 MW too high", f"{rt.loc[E5D, 'import_bias_mw']:.1f} MW too high"),
    ("E5d bias signed", "+13.1 MW", f"+{rt.loc[E5D, 'import_bias_mw']:.1f} MW"),
    ("E5b bias", "+4.4", f"+{rt.loc[E5B, 'import_bias_mw']:.1f}"),
    ("zero-shot bias", "| −260 |", f"| {fmt(rt.loc[ZS, 'import_bias_mw'], '.0f')} |"),
    ("−99 % E5→E5b", "−99.0 % real-state error", f"−{(1 - rt.loc[E5B, 'PBE_mean'] / rt.loc[E5, 'PBE_mean']) * 100:.1f} % real-state error"),
    ("E4 S0 residual", "33.7 MW, against 0.225 MW for a simple DC power flow (149×)",
     f"{e4.P_residual:.1f} MW, against {e4.dc_P_residual:.3f} MW for a simple DC power flow ({e4.genco_vs_dc_active_ratio:.0f}×)"),
    ("E5 synthetic", "from 44.8 to 0.47 MVA", f"from {e5s.loc['zero_shot', 'PBE_mean']:.1f} to {e5s.loc['ft_n50000_s0', 'PBE_mean']:.2f} MVA"),
    ("E5 real", "real states stay at 33.2 MVA", f"real states stay at {rt.loc[E5, 'PBE_mean']:.1f} MVA"),
    ("E5b real PBE", "real-state error to 0.338 MVA", f"real-state error to {rt.loc[E5B, 'PBE_mean']:.3f} MVA"),
    ("E5c import r", "import correlation reaches 0.96", f"import correlation reaches {rt.loc[E5C, 'import_corr']:.2f}"),
    ("E5c battery", "battery response 0.94 (AC 1.00)",
     f"battery response {rt.loc[E5C, 'genco_slope_chap31']:.2f} (AC {rt.loc[E5C, 'ac_slope_chap31']:.2f})"),
    ("E5 dispersion", "17.7× too dispersed", f"{rt.loc[E5, 'import_sd_pred_mw'] / rt.loc[E5, 'import_sd_ac_mw']:.1f}× too dispersed"),
    ("DC residual real", "DC power-flow active residual: 0.098 MW", f"DC power-flow active residual: {rt.loc[E5D, 'dc_P_residual']:.3f} MW"),
    ("E5c synthetic ratio", "0.014 (E5c)", f"{pv_ratio['e5c_ft_n10000_s2']:.3f} (E5c)"),
    ("E5d synthetic ratio", "0.997 published", f"{pv_ratio['e5d_l1_s0']:.3f} published"),
    ("control ratio", "stays PV-blind (0.001)", f"stays PV-blind ({pv_ratio['e5d_l0_s0']:.3f})"),
    ("PV-attributed error", "from 2.77 to **0.14 MW**",
     f"from {rt.loc[E5C, 'pv_response_error_mw']:.2f} to **{rt.loc[E5D, 'pv_response_error_mw']:.2f} MW**"),
    ("load slope", "the load response is **0.93**, matching AC's 0.93",
     f"the load response is **{rt.loc[E5D, 'genco_slope_load']:.2f}**, matching AC's {rt.loc[E5D, 'ac_slope_load']:.2f}"),
    ("E5d MAE", "(MAE 13.2 MW)", f"(MAE {rt.loc[E5D, 'import_mae_mw']:.1f} MW)"),
    ("E5d Vm", "(**0.0109 pu**)", f"(**{rt.loc[E5D, 'V_error']:.4f} pu**)"),
    ("E5d battery", "(**1.17** MW per MW, against 1.00)",
     f"(**{rt.loc[E5D, 'genco_slope_chap31']:.2f}** MW per MW, against {rt.loc[E5D, 'ac_slope_chap31']:.2f})"),
    # E6 diagnostic (E5d λ1 s0, E5c held-out synthetic test)
    ("E6 identity", "within 0.06 MW in every state", f"within {e6.identity_max_abs_dev_mw:.2f} MW in every state"),
    ("E6 fit", "21.1 + 0.62 × true import", f"{e6.pred_vs_ac_intercept_mw:.1f} + {e6.pred_vs_ac_slope:.2f} × true import"),
    ("E6 MAE", "a 14.2 MW mean error", f"a {e6.import_mae_mw:.1f} MW mean error"),
    ("E6 MAE 2dp [details]", "import MAE 14.21 MW", f"import MAE {e6.import_mae_mw:.2f} MW"),
    ("E6 n", "2,804 held-out", f"{int(e6.n):,} held-out"),
    ("E6 pairs r", "(r = 0.999 for PV pairs)", f"(r = {pl.corr_err_A_err_B:.3f} for PV pairs)"),
    ("E6 cancellation", "11.7 MW error in each state, 0.05 MW in the PV-induced change",
     f"{pl.level_mae_member_A_mw:.1f} MW error in each state, {pl.delta_err_mae_mw:.2f} MW in the PV-induced change"),
    ("E6 injection sum", "within 0.6 MW", f"within {pb.loc['E1 injections, lossless (DC-type balance)', 'mae_mw']:.1f} MW"),
    # grid, validation, satellite PV
    ("E1 nodes", "38 nodes, 44 branches",
     f"{e1['network']['buses']} nodes, {e1['network']['lines'] + e1['network']['transformers']} branches"),
    ("E2 timestamps", "(200 timestamps over 18 months)",
     f"({e2['selection']['selected']} timestamps over {e2['selection']['months_covered']} months)"),
    ("E2 import NMAE", "total grid-import NMAE **0.084**", f"total grid-import NMAE **{e2['verdict']['import_nmae']:.3f}**"),
    ("E2 convergence", "100 % AC convergence", f"{e2['verdict']['pf_convergence_rate'] * 100:.0f} % AC convergence"),
    ("E3 2024 PV", "only **8.945 MW**", f"only **{e3['inventory']['active_mw_search_period']:.3f} MW**"),
    ("E3 today", "(against 43.9 MW today)", f"(against {e3['inventory']['connected_mw_today']:.1f} MW today)"),
    ("E3 slots", "9,040 slots, of which 8,308 are usable",
     f"{e3['satellite_series']['slots']:,} slots, of which {e3['satellite_series']['validation']['slots_usable']:,} are usable"),
    # release verification (fresh clean-room clones)
    ("fresh CPU ratio", "0.999 in our fresh-clone CPU re-run",
     f"{CPU_RATIO:.3f} in our fresh-clone CPU re-run"),
    ("44/44", "**44/44 scored metrics**",
     "**{}/{} scored metrics**".format(*(lambda c: (c["n_within"], c["n_scored"]))(cpu["checks"]["C_fresh_metrics_within_tolerance"]))),
    ("five claims", "all **five synthetic claims** reproduced",
     f"all **{['zero', 'one', 'two', 'three', 'four', 'five'][min(N_REPRO['cpu'], N_REPRO['gpu'])]} synthetic claims** reproduced"),
    ("both devices pass", "passed on CPU and GPU", "passed on CPU and GPU" if cpu["all_checks_pass"] and gpu["all_checks_pass"] else "FAILED"),
]

# constructive wording: what → (quoted text, recomputed text), required in CONSTRUCTIVE variants instead
REPHRASE = {
    "control ratio": ("remains insensitive to PV (0.001)", f"remains insensitive to PV ({pv_ratio['e5d_l0_s0']:.3f})"),
}
# "[details]" claims: CONSTRUCTIVE variants link the report that holds them instead of embedding them
DETAILS_LINK = {"E6 MAE 2dp [details]": "reports/e6_feasibility_diagnostic.md"}

# results table rows: PBE · active residual · import MAE · import r · PV slope
TABLE = {ZS: "| E4 Original GENCO | 49.0 | 28.9 | 260 | 0.05 | −0.06 |",
         E5: "| E5 Grid-tuned | 33.2 | 28.8 | 70.7 | 0.11 | −0.66¹ |",
         E5B: "| E5b Envelope-tuned | **0.338** | **0.270** | **7.30** | 0.87 | −0.06 |",
         E5C: "| E5c Generator-aware | 0.442 | 0.342 | 7.74 | 0.96 | −0.04 |",
         E5D: "| E5d Response-aware | 0.676 | 0.567 | 13.2 | **0.994** | **−1.07** |"}  # fmt: skip
TABLE_LABEL = {ZS: ("| E4 Original GENCO |", "| E4 Pretrained, zero-shot |")}  # constructive row label; same cells


def sig(v: float) -> str:
    """Three significant figures, as in the table (49.0, 0.338, 260, 7.30, 13.2)."""
    return f"{v:.3g}" if abs(v) >= 100 else f"{float(f'{v:.3g}'):#.3g}".rstrip(".")


def table_row(m: str) -> list[str]:
    r = rt.loc[m]
    return [sig(r.PBE_mean), sig(r.P_residual), sig(r.import_mae_mw),
            f"{r.import_corr:.3f}" if m == E5D else f"{r.import_corr:.2f}", fmt(r.genco_slope_pv, ".2f")]  # fmt: skip


def main() -> int:
    texts = {str(p.relative_to(ROOT)): p.read_text() for p in VARIANTS}
    assert texts, "no rendered write-up found"
    bad = 0
    for what, quoted, recomputed in CLAIMS:
        alt = REPHRASE.get(what)
        ok_val = quoted == recomputed and (alt is None or alt[0] == alt[1])
        missing, checked = [], 0
        for n, t in texts.items():
            if what.endswith("[details]") and "HuggingFace" in n:
                continue  # a collapsible block, which the Hugging Face post links instead
            if what.endswith("[details]") and n in CONSTRUCTIVE:
                if DETAILS_LINK[what] not in t:
                    missing.append(f"{n} (link to {DETAILS_LINK[what]})")
                continue
            checked += 1
            if (alt[0] if alt and n in CONSTRUCTIVE else quoted) not in t:
                missing.append(n)
        if not ok_val or missing or not checked:
            bad += 1
            print(f"FAIL {what}: quoted {quoted!r} | source {recomputed!r} | rephrase {alt!r} | missing in {missing} | checked in {checked} variants")
    for m, row in TABLE.items():
        cells = [c.strip().strip("*").rstrip("¹") for c in row.strip("|").split("|")[1:]]
        want = table_row(m)
        rows = {n: row.replace(*TABLE_LABEL[m]) if m in TABLE_LABEL and n in CONSTRUCTIVE else row for n in texts}
        if cells != want or any(rows[n] not in t for n, t in texts.items()):
            bad += 1
            print(f"FAIL table {m}: post {cells} | source {want}")
    n = len(CLAIMS) + len(TABLE)
    print(f"{n - bad}/{n} checks pass ({len(CLAIMS)} quoted claims, {len(TABLE)} table rows, {len(texts)} variants)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

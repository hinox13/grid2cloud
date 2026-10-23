# ruff: noqa: E501
"""The site's research claims (E5b/E5d trade-off, E5d seeds, economic qualifiers, second network) against
the frozen research tables, re-derived here independently of scripts/web/export_web_data.py and of
scripts/web/build_research_bundle.py. The headline figures of the audit are also asserted literally.

The second-network tables (reports/g2) exist in the development repository only; those tests skip elsewhere.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web/public/data"
G2 = ROOT / "reports/g2"
pytestmark = pytest.mark.skipif(not (WEB / "claims.json").exists(), reason="web data not exported")


@pytest.fixture(scope="module")
def C() -> dict[str, dict]:
    return {c["id"]: c for c in json.loads((WEB / "claims.json").read_text())}


def test_research_bundle_is_reproducible() -> None:
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts/web/build_research_bundle.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stdout + out.stderr


# ------------------------------------------------------------------ Sundon: two models, two strengths
def test_e5b_e5d_headline_figures_literal(C: dict) -> None:
    lit = {
        "bias_E5b": "+4.4", "pbe_E5b": "0.338", "slope_E5b": "−0.06",
        "slope_E5c": "−0.04",
        "bias_E5d": "+13.1", "pbe_E5d": "0.676", "slope_E5d": "−1.07", "slope_AC": "−1.02",
        "n_states": "2,829",
    }  # fmt: skip
    for k, v in lit.items():
        assert C[k]["display"] == v, k


def test_tradeoff_is_metric_by_metric(C: dict) -> None:
    """E5b closer on the absolute state's bias and PBE; E5d closer on the solar response, Vm and import r."""
    t = pd.read_csv(ROOT / "reports/tables/e5d_real_transfer.csv").set_index("model")
    b, d = t.loc["E5b"], t.loc["E5d"]
    assert (
        abs(b.import_bias_mw) < abs(d.import_bias_mw)
        and b.PBE_mean < d.PBE_mean
        and b.P_residual < d.P_residual
    )
    assert abs(d.genco_slope_pv - d.ac_slope_pv) < abs(b.genco_slope_pv - b.ac_slope_pv)
    assert (
        d.V_error < b.V_error and d.import_corr > b.import_corr
    )  # the qualification the site states
    assert (
        C["vm_mae_E5d"]["display"] == f"{d.V_error:.4f}"
        and C["vm_mae_E5b"]["display"] == f"{b.V_error:.4f}"
    )
    assert C["ratio_pv_E5d"]["display"] == f"{100 * d.genco_slope_pv / d.ac_slope_pv:.0f}"


def test_e5d_seed_and_lambda_claims() -> None:
    claims = {c["id"]: c for c in json.loads((WEB / "claims.json").read_text())}
    t = pd.read_csv(ROOT / "reports/tables/e5d_postfreeze_runs_real.csv").set_index("model")
    for run, cid in (("e5d_l1_s1", "e5d_s1"), ("e5d_l1_s2", "e5d_s2"), ("e5d_l0.3_s0", "e5d_l03")):
        assert claims[f"{cid}_bias"]["display"] == f"{t.at[run, 'import_bias_mw']:+.1f}".replace(
            "-", "−"
        )
        assert (
            claims[f"{cid}_ratio"]["display"]
            == f"{t.at[run, 'genco_slope_pv'] / t.at[run, 'ac_slope_pv']:.2f}"
        )
    assert t.at["e5d_l1_s0", "selected"] and not t.at["e5d_l1_s1", "selected"]
    # the λ = 0 control's real-state slope has the wrong sign: never present it as "blind on real states"
    assert t.at["e5d_l0_s0", "genco_slope_pv"] > 0
    assert claims["l0_syn_ratio"]["display"] == "0.001"


# ------------------------------------------------------------------ economics: two counterfactuals, signed
@pytest.fixture(scope="module")
def P() -> pd.DataFrame:
    return pd.read_csv(ROOT / "reports/economic_impact/tables/periods.csv", parse_dates=["slot"])


def test_two_counterfactual_totals(C: dict, P: pd.DataFrame) -> None:
    v = lambda col: float((P[col] * 0.5 * P.apx_gbp_mwh).sum())  # noqa: E731
    assert C["season_cloud_attributed_gbp"]["display"] == f"£{v('dcl_AC'):,.0f}" == "£93,286"
    assert C["season_pv_attributed_gbp"]["display"] == f"£{v('dpv_AC'):,.0f}" == "£234,226"
    assert C["season_cloud_attributed_mwh"]["display"] == "1,428.37"
    d = P[P.slot.dt.strftime("%Y-%m-%d") == "2024-06-15"]
    assert (
        C["day_cloud_gbp"]["display"]
        == f"£{float((d.dcl_AC * 0.5 * d.apx_gbp_mwh).sum()):,.0f}"
        == "£1,661"
    )
    assert (
        C["day_pv_attr_gbp"]["display"] == f"£{float((d.dpv_AC * 0.5 * d.apx_gbp_mwh).sum()):,.0f}"
    )


def test_cloud_model_accuracy_and_per_half_hour(C: dict, P: pd.DataFrame) -> None:
    ac = float((P.dcl_AC * 0.5 * P.apx_gbp_mwh).sum())
    for m in ("E5d", "accounting", "E5c"):
        err = 100 * (float((P[f"dcl_{m}"] * 0.5 * P.apx_gbp_mwh).sum()) - ac) / ac
        assert C[f"season_cloud_err_{m}"]["value"] == pytest.approx(err, abs=1e-4)
    e_acc, e_d = (P.dcl_accounting - P.dcl_AC).abs(), (P.dcl_E5d - P.dcl_AC).abs()
    assert e_acc.mean() < e_d.mean()  # per half-hour, accounting wins
    assert C["cloud_acc_closer"]["display"] == f"{100 * (e_acc < e_d).mean():.0f}" == "77"
    assert C["season_cloud_err_E5d"]["display"] == "+0.06"


def test_signed_composition_and_coverage(C: dict, P: pd.DataFrame) -> None:
    assert C["cloud_neg_periods"]["value"] == int((P.dcl_AC < 0).sum()) == 927
    assert C["apx_neg_periods"]["value"] == int((P.apx_gbp_mwh < 0).sum()) == 180
    assert C["season_days"]["value"] == P.slot.dt.date.nunique() == 136
    assert C["season_days_span"]["value"] == 183  # 1 April – 30 September
    per = P.groupby(P.slot.dt.date).size()
    assert (C["periods_day_min"]["value"], C["periods_day_max"]["value"]) == (per.min(), per.max())


# ------------------------------------------------------------------ second network (dev tables)
g2 = pytest.mark.skipif(
    not (G2 / "s/metrics_absolute.csv").exists(), reason="second-network tables are dev-only"
)


@g2
def test_second_network_ranges_from_frozen_tables(C: dict) -> None:
    A = pd.read_csv(G2 / "s/metrics_absolute.csv")
    Pm = pd.read_csv(G2 / "s/metrics_pairs.csv")
    pv = Pm[Pm.probe_type == "pv"].set_index("run").import_slope_ratio
    rng = lambda s, f: f"{format(s.min(), f)}–{format(s.max(), f)}"  # noqa: E731
    C_runs = [f"g2a_C_s{i}" for i in range(3)]
    D_runs = [f"g2a_D_s{i}" for i in range(3)]
    ok = [r for r in D_runs if 0.8 <= pv[r] <= 1.2]
    assert len(ok) == 2 and C["g2_D_ok_seeds"]["display"] == "2 of 3"
    assert C["g2_C_pv_slope_ratio"]["display"] == rng(pv[C_runs], ".2f") == "0.16–0.32"
    assert C["g2_D_pv_slope_ratio_ok"]["display"] == rng(pv[ok], ".2f") == "0.99–1.01"
    mae = A.set_index("run").import_mae_mw
    assert C["g2_D_import_mae_mw_ok"]["display"] == rng(mae[ok], ".1f") == "10.2–10.9"
    assert C["g2_C_import_mae_mw"]["display"] == rng(mae[C_runs], ".1f")
    # the trade-off does not recur in the Sundon form: successful D seeds beat C and B on import MAE
    assert mae[ok].max() < mae[C_runs].min() < mae[[f"g2a_B_s{i}" for i in range(3)]].min()
    h = json.loads((G2 / "s/hypotheses.json").read_text())
    assert h["classification"] == "REPRODUCED" and h["H7"]["stable"] is False
    assert all(h[k]["holds"] for k in ("H1", "H2", "H3", "H4", "H5", "H6"))


@g2
def test_second_network_size_solar_and_validation(C: dict) -> None:
    net = json.loads((G2 / "s/network.json").read_text())
    assert net["hv_capacity_mw"] == {"Solar": 39.5, "Wind": 3.0}
    assert C["g2_buses"]["value"] == 56 and C["g2_gen_mw"]["display"] == "42.5"
    a = pd.read_csv(G2 / "a/pv_assets.csv")
    act = a[a.activity_search_start == "ACTIVE"]
    px = act.groupby("native_pixel_id").active_capacity_search_mw.sum()
    assert C["g2_active_pv_mw"]["display"] == f"{act.active_capacity_search_mw.sum():.1f}" == "41.2"
    assert C["g2_pixel_share"]["display"] == f"{100 * px.max() / px.sum():.0f}" == "96"
    v = json.loads((G2 / "a/validation_summary.json").read_text())
    assert v["level"] == "FAIL" and v["decision"] == "STOP" and not v["B_usable"]
    assert (
        v["criteria"]["import_nmae"] <= 0.25
        and v["criteria"]["direction_min"] < 0.9
        and abs(v["criteria"]["residual_vs_pv_r"]) > 0.5
    )


def test_research_json_carries_no_unpublished_arms() -> None:
    """Only the published/approved experiments appear: no E6, E7, ODL or nowcasting rows."""
    blob = (WEB / "research.json").read_text()
    # the only E6 material allowed is the published feasibility diagnostic (reports/e6_feasibility_diagnostic.md)
    for bad in ("E6 Arm", "e6_A_", "e6_B_", "e7_", "E7", "odl", "nowcast"):
        assert bad not in blob, bad
    assert np.isfinite(json.loads(blob)["second_network"]["replication"]["ac_import_std_mw"])


def test_economic_per_half_hour_and_signed_claims(C: dict, P: pd.DataFrame) -> None:
    for q, k in (("dpv", "pv"), ("dcl", "cloud")):
        for m in ("accounting", "E5d", "E5c"):
            assert C[f"{k}_hh_mae_{m}"]["value"] == pytest.approx(
                float((P[f"{q}_{m}"] - P[f"{q}_AC"]).abs().mean()), abs=1e-6
            )
    ac = float((P.dpv_AC * 0.5 * P.apx_gbp_mwh).sum())
    for m in ("accounting", "E5d", "E5c"):
        err = 100 * (float((P[f"dpv_{m}"] * 0.5 * P.apx_gbp_mwh).sum()) - ac) / ac
        assert C[f"season_pv_err_{m}"]["value"] == pytest.approx(err, abs=1e-4)
    assert C["cloud_neg_mwh"]["value"] == pytest.approx(
        float((P.dcl_AC.clip(upper=0) * 0.5).sum()), abs=1e-3
    )
    assert C["cloud_pos_mwh"]["value"] == pytest.approx(
        float((P.dcl_AC.clip(lower=0) * 0.5).sum()), abs=1e-3
    )
    assert (
        C["apx_season_min"]["value"] == pytest.approx(float(P.apx_gbp_mwh.min()))
        and C["apx_season_min"]["display"] == "−£61"
    )
    d = P[P.slot.dt.strftime("%Y-%m-%d") == "2024-06-15"]
    assert C["day_pv_attr_mwh"]["value"] == pytest.approx(float((d.dpv_AC * 0.5).sum()), abs=1e-4)


@g2
def test_second_network_remaining_claims(C: dict) -> None:
    A = pd.read_csv(G2 / "s/metrics_absolute.csv").set_index("run")
    Pm = pd.read_csv(G2 / "s/metrics_pairs.csv")
    pv = Pm[Pm.probe_type == "pv"].set_index("run")
    B = [f"g2a_B_s{i}" for i in range(3)]
    assert (
        C["g2_B_pv_slope_ratio"]["display"]
        == f"{pv.loc[B].import_slope_ratio.min():.2f}–{pv.loc[B].import_slope_ratio.max():.2f}"
    )
    assert (
        C["g2_B_import_mae_mw"]["display"]
        == f"{A.loc[B].import_mae_mw.min():.1f}–{A.loc[B].import_mae_mw.max():.1f}"
    )
    assert (
        C["g2_D_bad_ratio"]["display"] == f"{pv.at['g2a_D_s1', 'import_slope_ratio']:.2f}" == "0.38"
    )
    assert C["g2_D_bad_mae"]["display"] == f"{A.at['g2a_D_s1', 'import_mae_mw']:.1f}"
    assert C["g2_test_states"]["value"] == A.at["g2a_D_s2", "n"] == 2838
    assert C["g2_export_states"]["value"] == A.at["g2a_D_s2", "n_export_states"] == 374
    assert C["g2_pairs"]["value"] == pv.at["g2a_D_s2", "n_pairs"] == 500
    assert C["g2_ac_std"]["display"] == f"{A.at['g2a_D_s2', 'ac_import_std_mw']:.1f}"
    s = json.loads((G2 / "a/e1_structural_validation.json").read_text())["checks"]
    assert (
        (C["g2_lines"]["value"], C["g2_trafos"]["value"])
        == (
            s["line_endpoints_valid"]["detail"]["n_lines"],
            s["trafo_endpoints_valid"]["detail"]["n_trafos"],
        )
        == (53, 16)
    )
    v = json.loads((G2 / "a/validation_summary.json").read_text())["criteria"]
    assert C["g2_val_nmae"]["value"] == pytest.approx(v["import_nmae"], abs=1e-4)
    assert C["g2_val_core"]["display"] == f"{100 * v['core_fit_share_B']:.0f}" == "17"
    assert C["g2_val_direction"]["value"] == v["direction_min"] == 0.0
    assert C["g2_val_resid_r"]["value"] == pytest.approx(v["residual_vs_pv_r"], abs=1e-4)
    assert (
        C["g2_obs_pv_slope"]["display"] == "−0.51"
    )  # report value (reports/g2a_aylesbury_validation.md), not recomputed
    assert "−0.51 MW per MW" in (ROOT / "reports/g2a_aylesbury_validation.md").read_text()
    assert C["g2_classification"]["display"] == "Reproduced"


def test_network_wide_response_and_cancellation(C: dict) -> None:
    t = pd.read_csv(ROOT / "reports/tables/e5d_postfreeze_runs_real.csv").set_index("model")
    rt = pd.read_csv(ROOT / "reports/tables/e5d_real_transfer.csv").set_index("model")
    for run, m in (("E5c", "E5c"), ("e5d_l1_s0", "E5d")):
        # the branch error is the one published with the real-transfer verdict; the post-freeze table agrees
        assert C[f"branch_resp_{m}"]["value"] == pytest.approx(
            rt.at[m, "branch_pv_slope_median_abs_err"], abs=1e-6
        )
        assert t.at[run, "branch_pv_slope_median_abs_err"] == pytest.approx(
            rt.at[m, "branch_pv_slope_median_abs_err"], abs=1e-9
        )
        assert C[f"va_resp_{m}"]["value"] == pytest.approx(
            t.at[run, "bus_Va_pv_slope_median_abs_err"], abs=1e-6
        )
    lit = {
        "branch_resp_E5c": "0.074",
        "branch_resp_E5d": "0.014",
        "va_resp_E5c": "0.050",
        "va_resp_E5d": "0.0009",
        "va_resp_AC": "0.053",
    }
    for k, v in lit.items():
        assert C[k]["display"] == v, k
    pl = pd.read_csv(ROOT / "reports/tables/e6_pair_level_cancellation.csv")
    pl = pl[(pl.model == "E5d λ1 s0 (frozen)") & (pl.probe_type == "pv")].iloc[0]
    assert (
        (C["cancel_r"]["display"], C["cancel_level"]["display"], C["cancel_delta"]["display"])
        == (
            f"{pl.corr_err_A_err_B:.3f}",
            f"{pl.level_mae_member_A_mw:.1f}",
            f"{pl.delta_err_mae_mw:.2f}",
        )
        == ("0.999", "11.7", "0.05")
    )


def test_homepage_impact_figures(C: dict, P: pd.DataFrame) -> None:
    """The homepage's impact numbers: the two counterfactuals of one plant, rounded from the same sums."""
    pv, cl = float((P.dpv_AC * 0.5).sum()), float((P.dcl_AC * 0.5).sum())
    assert C["impact_pv_mwh"]["display"] == f"{pv:,.0f}" == "4,038"
    assert C["impact_cloud_mwh"]["display"] == f"{cl:,.0f}" == "1,428"
    assert C["impact_pv_mwh"]["value"] == pytest.approx(C["season_pv_attributed_mwh"]["value"], abs=1e-3)
    assert C["impact_cloud_mwh"]["value"] == pytest.approx(C["season_cloud_attributed_mwh"]["value"], abs=1e-3)
    no_plant = float((P.I_AC * 0.5).sum()) + pv
    assert C["impact_pv_share"]["value"] == pytest.approx(100 * pv / no_plant, abs=1e-3)
    assert C["impact_pv_share"]["display"] == "5.6"
    v = P.dpv_AC * 0.5 * P.apx_gbp_mwh
    assert C["impact_pv_neg_value_periods"]["value"] == int((v < 0).sum()) == 180
    assert int((P.dpv_AC < 0).sum()) == 0  # the plant never raises the import; only prices make terms negative

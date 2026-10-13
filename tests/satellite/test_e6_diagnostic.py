"""E6 feasibility diagnostic (post-hoc, synthetic only; no model trained): the published tables
carry the numbers the report, README and submission quote, the per-state / per-pair extracts
reproduce the aggregate tables (and therefore figure 06), and the script stays read-only.
Runs from a clean checkout: it reads only the published tables, not the local predictions.
"""

import json

import numpy as np
import pandas as pd
import pytest

from cloud2grid.licensing.registry import REPO_ROOT

TAB = REPO_ROOT / "reports/tables"
SEL = "E5d λ1 s0 (frozen)"
TABLES = (
    "e6_model_comparison",
    "e6_import_residual_drivers",
    "e6_import_by_stratum",
    "e6_residual_by_bus",
    "e6_physical_baselines",
    "e6_ref_branch_sensitivity",
    "e6_trace_examples",
    "e6_exploratory_real_s1",
    "e6_pair_level_cancellation",
    "e6_pv_pairs_e5d",
    "e6_import_states_e5d",
)


def t(name: str) -> pd.DataFrame:
    return pd.read_csv(TAB / f"{name}.csv")


def test_all_outputs_published() -> None:
    for n in TABLES:
        assert (TAB / f"{n}.csv").is_file(), n
    for f in ("import_residuals", "mismatch_identity", "pair_cancellation", "regimes"):
        assert (REPO_ROOT / f"reports/figures/e6_{f}.png").is_file()
    assert (REPO_ROOT / "reports/e6_feasibility_diagnostic.md").is_file()


def test_headline_import_numbers() -> None:
    c = t("e6_model_comparison")
    r = c[(c.population == "E5c held-out synthetic test") & (c.model == SEL)].iloc[0]
    assert r.n == 2804
    assert r.import_mae_mw == pytest.approx(14.21, abs=0.005)
    assert r.pred_vs_ac_slope == pytest.approx(0.623, abs=0.0005)
    assert r.pred_vs_ac_intercept_mw == pytest.approx(21.1, abs=0.05)
    assert r.export_recall == pytest.approx(0.216, abs=0.001)
    # the frozen E5d synthetic report: import MAE 14.2, Va MAE 1.15°, PBE 0.795
    assert r.va_mae_deg == pytest.approx(1.15, abs=0.005)
    assert r.pbe_mean == pytest.approx(0.795, abs=0.0005)


def test_identity_holds_for_every_model() -> None:
    c = t("e6_model_comparison")
    assert (c.identity_max_abs_dev_mw < 0.08).all()
    assert (c.identity_r2 > 0.9999).all()


def test_state_extract_reproduces_fit() -> None:
    s = t("e6_import_states_e5d")
    assert len(s) == 2804
    b, a = np.polyfit(s.ac_import, s.pred_import, 1)
    assert (b, a) == (pytest.approx(0.623, abs=0.0005), pytest.approx(21.1, abs=0.05))
    assert (s.pred_import - s.ac_import).abs().mean() == pytest.approx(14.21, abs=0.005)


def test_pair_cancellation_numbers_and_extract() -> None:
    pc = t("e6_pair_level_cancellation")
    r = pc[(pc.model == SEL) & (pc.probe_type == "pv")].iloc[0]
    assert r.n_pairs == 500
    assert r.level_mae_member_A_mw == pytest.approx(11.68, abs=0.005)
    assert r.delta_err_mae_mw == pytest.approx(0.046, abs=0.0005)
    assert r.corr_err_A_err_B == pytest.approx(0.999, abs=0.0005)
    p = t("e6_pv_pairs_e5d")
    assert len(p) == 500
    assert p.err_A.abs().mean() == pytest.approx(r.level_mae_member_A_mw, abs=1e-4)
    assert (p.delta_pred - p.delta_ac).abs().mean() == pytest.approx(r.delta_err_mae_mw, abs=1e-4)
    assert np.corrcoef(p.err_A, p.err_B)[0, 1] == pytest.approx(r.corr_err_A_err_B, abs=1e-6)


def test_accounting_baselines() -> None:
    b = t("e6_physical_baselines").set_index("estimate").mae_mw
    assert b.filter(like="B  GENCO").iloc[0] == pytest.approx(14.21, abs=0.005)
    assert b.filter(like="E1 ").iloc[0] == pytest.approx(0.58, abs=0.005)
    assert b.filter(like="D  ").iloc[0] == pytest.approx(0.20, abs=0.005)


def test_exploratory_real_section_is_labelled() -> None:
    text = (REPO_ROOT / "reports/e6_feasibility_diagnostic.md").read_text()
    assert "exploratory" in text.lower() and "post-hoc diagnostic" in text.lower()
    assert "No E6 checkpoint exists" in text or "no E6 checkpoint exists" in text


def test_script_is_read_only_and_guards_its_source() -> None:
    src = (REPO_ROOT / "scripts/diagnose_e6_feasibility.py").read_text()
    assert "to_parquet" not in src and "torch.save" not in src
    assert "not this checkout" in src  # refuses a cloud2grid import from another checkout
    run = json.loads((REPO_ROOT / "reports/experiments/e6_feasibility/diagnostic.json").read_text())
    assert "/home/" not in json.dumps(run)


def test_demo_has_no_e6_model() -> None:
    models = json.loads((REPO_ROOT / "data/demo/models.json").read_text())
    assert not any(
        "E6" in json.dumps(m) for m in (models if isinstance(models, list) else [models])
    )

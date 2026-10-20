# ruff: noqa: E501
"""Cloud Impact economic numbers: bundle and released-table checks (always) and the full re-derivation
(only where the local study outputs exist; skipped in a public clone)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("verify_economic", ROOT / "scripts/economic_impact/verify_economic.py")
V = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(V)

HAVE_BUNDLE = (V.BUNDLE / "periods_2024-06-15.parquet").exists()
HAVE_STUDY = (V.WORK / "imports.parquet").exists()


@pytest.mark.parametrize(
    ("utc", "date", "period"),
    [
        ("2024-06-14T23:00Z", "2024-06-15", 1),  # BST: settlement period 1 starts 23:00 UTC the day before
        ("2024-06-15T05:00Z", "2024-06-15", 13),
        ("2024-06-15T11:00Z", "2024-06-15", 25),
        ("2024-06-15T22:30Z", "2024-06-15", 48),
        ("2024-04-13T07:00Z", "2024-04-13", 17),  # the documented APX source gap
    ],
)
def test_bst_settlement_numbering(utc: str, date: str, period: int) -> None:
    d, p = V.bst_settlement(pd.Series(pd.to_datetime([utc], utc=True)))
    assert d.iloc[0] == date and int(p.iloc[0]) == period


def test_mw_to_mwh_and_negative_prices() -> None:
    # 2 MW held for one settlement period is 1 MWh; at a negative price its value is negative
    assert 2.0 * V.H == 1.0
    assert 2.0 * V.H * -10.0 == -10.0


@pytest.mark.skipif(not HAVE_BUNDLE, reason="Cloud Impact bundle not built")
@pytest.mark.parametrize("check", V.bundle_checks() if HAVE_BUNDLE else [], ids=lambda c: c[0])
def test_bundle(check: tuple) -> None:
    name, ok, detail = check
    assert ok, f"{name}: {detail}"


HAVE_TABLE = V.TABLE.exists() and HAVE_BUNDLE


@pytest.mark.skipif(not HAVE_TABLE, reason="released per-half-hour table absent")
@pytest.mark.parametrize("check", V.released_checks() if HAVE_TABLE else [], ids=lambda c: c[0])
def test_released_tables(check: tuple) -> None:
    name, ok, detail = check
    assert ok, f"{name}: {detail}"


@pytest.mark.skipif(not HAVE_STUDY, reason="frozen economic-impact study artefacts are local research data")
@pytest.mark.parametrize("check", V.full_checks() if HAVE_STUDY else [], ids=lambda c: c[0])
def test_full_rederivation(check: tuple) -> None:
    name, ok, detail = check
    assert ok, f"{name}: {detail}"


@pytest.mark.skipif(not HAVE_BUNDLE, reason="Cloud Impact bundle not built")
def test_bundle_carries_attribution_and_no_secrets() -> None:
    import json

    prov = json.loads((V.BUNDLE / "provenance.json").read_text())
    assert any("© Elexon Limited" in s.get("attribution", "") for s in prov["sources"])
    blob = "".join(p.read_text(errors="ignore") for p in V.BUNDLE.glob("*.json")).lower()
    for word in ("password", "token", "secret", "api_key", "apikey", "authorization"):
        assert word not in blob


@pytest.mark.parametrize("source_id", ["elexon_bmrs_market_index", "elexon_bmrs_system_prices"])
def test_price_sources_pass_the_licence_gate(source_id: str) -> None:
    from cloud2grid.licensing import gate
    from cloud2grid.licensing.registry import Registry, Use

    reg = Registry.load()
    assert gate.check(source_id, Use.REDISTRIBUTE_DERIVED, reg).allowed
    assert not gate.check(source_id, Use.REDISTRIBUTE_RAW, reg).allowed  # raw API dumps stay out of Git
    assert "Contains BMRS data © Elexon Limited" in reg.sources[source_id].attribution


@pytest.mark.skipif(not HAVE_BUNDLE, reason="Cloud Impact bundle not built")
def test_bundle_records_licence_gate_decisions() -> None:
    import json

    prov = json.loads((V.BUNDLE / "provenance.json").read_text())
    ids = {d["source_id"] for d in prov["gate_decisions"] if d["allowed"] and d["use"] == "redistribute_derived"}
    assert {"elexon_bmrs_market_index", "elexon_bmrs_system_prices", "ukpn_33kv_operational_half_hourly_epn"} <= ids

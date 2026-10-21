# ruff: noqa: E501
"""The React site's data (web/public/data) against its frozen Python sources (data/demo).

Checks are written independently of scripts/web/export_web_data.py: every claim the Experience states
is re-derived here from the parquet/JSON bundles, the headline figures of the brief are asserted
literally, timestamps and settlement periods are aligned across bundles, unit conversions (MW × 0.5 h,
MWh × £/MWh) are recomputed, model labels are tied to their columns, the observed imagery is
byte-identical to the bundle, and the export is reproducible (rebuilt and compared byte for byte).
All inputs are committed, so these tests also run in a public clone.
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
DEMO = ROOT / "data/demo"
WEB = ROOT / "web/public/data"
EV = DEMO / "events/jun15_cloud_clearing"
pytestmark = pytest.mark.skipif(not (WEB / "claims.json").exists(), reason="web data not exported")


def load(name: str) -> object:
    return json.loads((WEB / name).read_text())


@pytest.fixture(scope="module")
def claims() -> dict[str, dict]:
    return {c["id"]: c for c in load("claims.json")}


def utc(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz="UTC")


# ------------------------------------------------------------------ reproducibility
def test_export_is_reproducible() -> None:
    pytest.importorskip("streamlit", reason="the exporter reads the Explorer's labels (demo/c2g/theme.py)")
    out = subprocess.run([sys.executable, str(ROOT / "scripts/web/export_web_data.py"), "--check"], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


def test_manifest_hashes_and_inputs() -> None:
    import hashlib

    man = load("manifest.json")
    for rel, h in man["outputs"].items():
        assert hashlib.sha256((WEB / rel).read_bytes()).hexdigest() == h, rel
    for rel, h in man["inputs"].items():
        assert rel.startswith("data/demo/"), f"input outside the published bundles: {rel}"
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == h, rel


def test_only_public_bundle_content() -> None:
    files = [p for p in WEB.rglob("*") if p.is_file()]
    assert {p.suffix for p in files} <= {".json", ".webp"}
    import re

    text = " ".join(str(p.relative_to(WEB)).lower() for p in files)
    assert not re.search(r"odl|nowcast|\bg2|aylesbury|interim|raw/", text)
    for p in files:
        if p.suffix == ".json":
            body = p.read_text()
            assert "NaN" not in body and "Infinity" not in body, p
            assert "data/interim" not in body or p.name == "event.json" or p.name == "models.json", p


def test_frames_are_the_observed_files() -> None:
    for ev in load("events/index.json"):
        e = load(f"events/{ev['event_id']}/event.json")
        src = pd.read_parquet(DEMO / "events" / ev["event_id"] / "satellite/frames.parquet")
        assert len(e["frames"]) == len(src) == ev["n_frames"]
        for f, s in zip(e["frames"], src.itertuples(), strict=True):
            assert (WEB / f["file"]).read_bytes() == (DEMO / "events" / ev["event_id"] / s.image_file).read_bytes()
            assert utc(f["t"]) == s.timestamp_utc


# ------------------------------------------------------------------ the brief's figures, literally
BRIEF = {
    "fleet_pv_1100": "2.38",
    "fleet_pv_1130": "8.86",
    "fleet_pv_delta": "+6.49",
    "fleet_capacity": "8.945",
    "n_buses": "38",
    "n_branches": "44",
    "import_ac_1100": "54.4",
    "import_ac_1130": "34.0",
    "cf_E5c_1100": "−0.04",
    "cf_E5d_1100": "−4.56",
    "cf_AC_1100": "−4.57",
    "slope_E5c": "−0.04",
    "slope_E5d": "−1.07",
    "slope_AC": "−1.02",
    "bias_E5d": "+13.1",
    "day_cloud_mwh": "16.94",
    "day_cloud_gbp": "£1,661",
    "day_periods": "24",
    "day_first": "05:00",
    "day_last": "16:30",
    "one_cloud_gbp": "£221",
    "one_cloud_mw": "4.565",
    "one_cloud_mwh": "2.283",
    "one_apx": "£96.76",
    "plant_pv_obs_1100": "1.46",
    "plant_pv_clear_1100": "5.97",
    "plant_pv_cf_delta": "+4.51",
    "season_days": "136",
    "plant_capacity": "6",
    "other_pv_capacity": "2.9",
    "states_span": "April–September 2024",
    "season_pv_attributed_mwh": "4,038.08",
    "season_pv_attributed_gbp": "£234,226",
    "season_cloud_attributed_mwh": "1,428.37",
    "season_cloud_attributed_gbp": "£93,286",
    "season_periods": "2,820",
    "n_states": "2,829",
    # the model journey (aggregate evaluation over all real states, not the 11:00 event)
    "import_mean_zero_shot": "\u2212211.4",
    "import_mean_AC": "48.6",
    "bias_zero_shot": "\u2212260.0",
    "zero_shot_wrong_sign": "99.9",
    "pbe_zero_shot": "49.0",
    "pbe_E5b": "0.338",
    "bias_E5b": "+4.4",
    "import_mean_E5b": "53.0",
}


@pytest.mark.parametrize(("cid", "display"), BRIEF.items())
def test_brief_figures(claims: dict, cid: str, display: str) -> None:
    assert claims[cid]["display"] == display


# ------------------------------------------------------------------ independent re-derivation
def test_solar_claims(claims: dict) -> None:
    f = pd.read_parquet(EV / "fleet_pv.parquet").set_index("timestamp_utc").fleet_pv_mw
    a, b = f[utc("2024-06-15 11:00")], f[utc("2024-06-15 11:30")]
    assert claims["fleet_pv_1100"]["value"] == pytest.approx(a, abs=1e-6)
    assert claims["fleet_pv_1130"]["value"] == pytest.approx(b, abs=1e-6)
    assert claims["fleet_pv_delta"]["value"] == pytest.approx(b - a, abs=1e-6)  # unrounded difference
    assert round(b - a, 2) == 6.49 and round(b, 2) - round(a, 2) == pytest.approx(6.48)  # why the unrounded values matter
    g = pd.read_parquet(EV / "pv_generation.parquet")
    cap = g.groupby("asset_id").capacity_mw.max()
    assert claims["n_pv_plants"]["value"] == (cap > 0).sum() == 10
    assert claims["fleet_capacity"]["value"] == pytest.approx(cap.sum(), abs=1e-6)
    # fleet PV is the sum of the per-asset estimates at every 15-minute step
    s = g.groupby("timestamp_utc").p_mw.sum()
    assert np.allclose(s.reindex(f.index), f, atol=1e-6)
    # the 6 MW plant is not the fleet: its counterfactual capacity is 6 MW
    assert cap["ECR:955"] == 6.0 and claims["fleet_capacity"]["value"] > 8.9


def test_network_counts(claims: dict) -> None:
    n = pd.read_parquet(DEMO / "network_nodes.parquet")
    e = pd.read_parquet(DEMO / "network_edges.parquet")
    assert n.members.str.split(";").str.len().sum() == 38 and len(n) == 37
    assert e.elements.str.split(";").str.len().sum() == 44 and len(e) == 42
    net = load("network.json")
    assert len(net["nodes"]) == 37 and len(net["edges"]) == 42


def test_grid_claims(claims: dict) -> None:
    s = pd.read_parquet(EV / "summary.parquet")
    ac = s[s.model == "AC"].set_index("timestamp_utc").import_mw
    a, b = ac[utc("2024-06-15 11:00")], ac[utc("2024-06-15 11:30")]
    assert claims["import_ac_1100"]["value"] == pytest.approx(a, abs=1e-6)
    assert claims["import_ac_hist_delta"]["value"] == pytest.approx(b - a, abs=1e-6)
    co = json.loads((DEMO / "catalog.json").read_text())["ols_coefficients_s1"]["AC"]
    r = pd.read_parquet(DEMO / "pv_response_s1.parquet").set_index("timestamp_utc")
    ra, rb = r.loc[utc("2024-06-15 11:00")], r.loc[utc("2024-06-15 11:30")]
    assert ra.import_AC == pytest.approx(a) and rb.import_AC == pytest.approx(b)  # same frozen states
    terms = {k: co[c] * (rb[col] - ra[col]) for k, c, col in (("load", "load", "load_mw"), ("battery", "chap31", "chap31_mw"), ("pv", "pv", "pv_injection_mw"))}
    for k, v in terms.items():
        assert claims[f"hist_{k}_term"]["value"] == pytest.approx(v, abs=1e-6)
    assert sum(terms.values()) + claims["hist_remainder"]["value"] == pytest.approx(b - a, abs=1e-6)
    # the battery is a load node: its sign flips from drawing to supplying
    assert ra.chap31_mw > 0 > rb.chap31_mw


def test_counterfactual_claims(claims: dict) -> None:
    p = pd.read_parquet(DEMO / "cloud_impact/periods_2024-06-15.parquet").set_index("slot_utc")
    q = p.loc[utc("2024-06-15 11:00")]
    for m in ("AC", "E5c", "E5d"):
        assert claims[f"cf_{m}_1100"]["value"] == pytest.approx(q[f"import_{m}_clear_sky_mw"] - q[f"import_{m}_observed_mw"], abs=1e-5)
    assert claims["cf_AC_1100"]["provenance"] == "simulated"
    assert claims["cf_E5c_1100"]["provenance"] == claims["cf_E5d_1100"]["provenance"] == "predicted"
    assert claims["plant_pv_clear_1100"]["provenance"] == "hypothetical"
    # the counterfactual starts from the same historical AC state the grid scene shows
    assert q.import_AC_observed_mw == pytest.approx(claims["import_ac_1100"]["value"], abs=1e-5)
    # counterfactual responses (MW) and fitted sensitivities (MW/MW) are distinct claims with distinct units
    assert claims["cf_E5d_1100"]["unit"] == "MW" and claims["slope_E5d"]["unit"] == "MW/MW"


def test_sensitivity_claims(claims: dict) -> None:
    evo = pd.read_csv(DEMO / "model_evolution.csv").set_index("model")
    co = json.loads((DEMO / "catalog.json").read_text())["ols_coefficients_s1"]
    for m in ("zero_shot", "E5", "E5b", "E5c", "E5d"):
        assert claims[f"slope_{m}"]["value"] == pytest.approx(evo.at[m, "genco_slope_pv"], abs=1e-6)
        assert claims[f"slope_{m}"]["value"] == pytest.approx(co[m]["pv"], abs=1e-6)
        assert claims[f"bias_{m}"]["value"] == pytest.approx(evo.at[m, "genco_import_mean_mw"] - evo.at[m, "ac_import_mean_mw"], abs=1e-4)
    assert claims["slope_AC"]["value"] == pytest.approx(co["AC"]["pv"], abs=1e-6)
    assert claims["n_states"]["value"] == evo.at["E5d", "n"] == len(pd.read_parquet(DEMO / "pv_response_s1.parquet"))


def test_value_claims(claims: dict) -> None:
    p = pd.read_parquet(DEMO / "cloud_impact/periods_2024-06-15.parquet")
    season = json.loads((DEMO / "cloud_impact/season.json").read_text())
    d = p.import_AC_observed_mw - p.import_AC_clear_sky_mw
    mwh = d * 0.5  # MW held for one 30-minute settlement period
    assert claims["day_cloud_mwh"]["value"] == pytest.approx(mwh.sum(), abs=1e-5)
    assert claims["day_cloud_gbp"]["value"] == pytest.approx((mwh * p.apx_gbp_per_mwh).sum(), abs=1e-3)
    ev = season["event_2024-06-15"]
    assert mwh.sum() == pytest.approx(ev["AC"]["cloud_energy_mwh"], abs=1e-4)
    assert (mwh * p.apx_gbp_per_mwh).sum() == pytest.approx(ev["AC"]["cloud_value_apx_gbp"], abs=1e-2)
    q = p.set_index(p.slot_utc.dt.strftime("%H:%M")).loc["11:00"]
    one = (q.import_AC_observed_mw - q.import_AC_clear_sky_mw) * 0.5 * q.apx_gbp_per_mwh
    assert claims["one_cloud_gbp"]["value"] == pytest.approx(one, abs=1e-3)
    assert claims["one_cloud_gbp"]["value"] < claims["day_cloud_gbp"]["value"] / 5  # one half-hour is not the day
    for k in ("pv_attributed", "cloud_attributed"):
        assert claims[f"season_{k}_gbp"]["value"] == pytest.approx(season[k]["AC"]["value_apx_gbp"], abs=1e-3)
    assert claims["season_periods"]["value"] == season["periods_valued"] == 2820
    # the season spans 136 days; 15 June is a high-value day, not a typical one
    dc = season["daily_context"]
    assert claims["season_days"]["value"] == dc["days"] == len(load("cloud_impact.json")["season_dates"]) == 136
    assert claims["day_cloud_gbp"]["value"] > 2 * claims["season_day_median_gbp"]["value"]
    assert claims["one_cloud_mwh"]["value"] == pytest.approx(claims["one_cloud_mw"]["value"] * 0.5, abs=1e-6)
    ci = load("cloud_impact.json")
    assert ci["apx_gap"]["slot_utc"] == "2024-04-13T07:00:00Z" and ci["apx_gap"]["settlement_period"] == 17


# ------------------------------------------------------------------ time alignment
def test_time_alignment() -> None:
    e = load("events/jun15_cloud_clearing/event.json")
    ft = pd.to_datetime([f["t"] for f in e["frames"]])
    assert (np.diff(ft.asi8) == 15 * 60 * 10**9).all()  # observed imagery is 15-minute
    gs = pd.to_datetime(e["grid_slots"])
    assert (np.diff(gs.asi8) == 30 * 60 * 10**9).all()  # grid states are half-hourly
    assert set(gs) <= set(ft)
    for m in e["models"]:
        assert list(e["flows"][m]) == e["grid_slots"]
        assert all(len(e["flows"][m][s]["p_ab_mw"]) == len(e["edge_ids"]) for s in e["grid_slots"])
    ci = load("cloud_impact.json")["periods"]
    slots = pd.to_datetime(ci["slot"])
    assert len(slots) == 24 and (np.diff(slots.asi8) == 30 * 60 * 10**9).all()
    local = slots.tz_convert("Europe/London")
    sp = ((local - local.normalize()).total_seconds() // 1800 + 1).astype(int)
    assert list(sp) == ci["settlement_period"]  # BST settlement periods (11:00 UTC = SP 25)
    # the economic bundle and the event bundle describe the same half-hours identically
    i = list(slots).index(pd.Timestamp("2024-06-15T11:00Z"))
    j = e["grid_slots"].index("2024-06-15T11:00:00Z")
    assert ci["import_AC_observed_mw"][i] == pytest.approx(e["summary"]["AC"]["import_mw"][j], abs=1e-4)
    assert ci["plant_pv_mw"][i] == pytest.approx(e["grid_inputs"]["hv_pv_mw"][j], abs=1e-4)
    k = [f["t"] for f in e["frames"]].index("2024-06-15T11:00:00Z")
    assert ci["fleet_pv_mw"][i] == pytest.approx(e["fleet_pv_mw"][k], abs=1e-4)


def test_model_labels() -> None:
    m = load("models.json")
    ids = [x["id"] for x in m["models"]]
    assert ids == ["zero_shot", "E5", "E5b", "E5c", "E5d"]
    names = {x["id"]: (x["name"], x["exp"]) for x in m["models"]}
    assert names["E5c"] == ("Generator-aware", "E5c") and names["E5d"] == ("Response-aware", "E5d")
    sha = {x["id"]: x.get("checkpoint_sha256") for x in m["models"]}
    assert sha["E5d"].startswith("45ab8252") and sha["E5c"].startswith("31b82424")
    evo = {r["model"]: r for r in m["evolution"]}
    assert evo["E5d"]["genco_slope_pv"] == pytest.approx(-1.0701026, abs=1e-6)
    r = load("pv_response.json")
    src = pd.read_parquet(DEMO / "pv_response_s1.parquet").sort_values("scenario")
    for c in ("import_AC", "import_E5c", "import_E5d", "partial_E5d", "pv_injection_mw"):
        assert np.allclose(r[c], src[c], atol=6e-5), c


def test_journey_is_not_a_universal_improvement(claims: dict) -> None:
    """E5d learns the response but is not better on every metric than E5b; the site must not imply it."""
    v = {k: c["value"] for k, c in claims.items()}
    assert v["pbe_E5d"] > v["pbe_E5b"] and abs(v["bias_E5d"]) > abs(v["bias_E5b"])  # state accuracy: E5b better
    assert abs(v["slope_E5d"] - v["slope_AC"]) < abs(v["slope_E5b"] - v["slope_AC"])  # response: E5d better
    assert v["import_mean_zero_shot"] < 0 < v["import_mean_AC"]  # the original model predicts export
    evo = pd.read_csv(DEMO / "model_evolution.csv").set_index("model")
    for m in ("zero_shot", "E5", "E5b", "E5c", "E5d"):
        assert claims[f"pbe_{m}"]["value"] == pytest.approx(evo.at[m, "PBE_mean"], abs=1e-6)
        assert claims[f"corr_{m}"]["value"] == pytest.approx(evo.at[m, "import_corr"], abs=1e-6)
        assert claims[f"slope_battery_{m}"]["value"] == pytest.approx(evo.at[m, "genco_slope_chap31"], abs=1e-6)

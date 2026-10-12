import numpy as np
import pandas as pd
import pytest

from cloud2grid.satellite import geometry as geo
from cloud2grid.scenarios import events
from cloud2grid.solar import aggregate, capacity, forcing, irradiance, pv

from .fixtures import CLOUD_OK, FAIL, product

PV_CFG = {
    "irradiance": {
        "clearsky_tolerance": 1.1,
        "zenith_clearsky_limit_deg": 80,
        "zenith_zero_dni_deg": 88,
    },
    "pv": {
        "tilt_deg": 30,
        "azimuth_deg": 180,
        "albedo": 0.2,
        "sky_diffuse_model": "haydavies",
        "iam_ashrae_b": 0.05,
        "temp_air_c": 15.0,
        "wind_speed_ms": 3.0,
        "gamma_pdc": -0.0035,
        "dc_ac_ratio": 1.25,
        "inverter_eta_nom": 0.98,
        "losses_pct": {
            "soiling": 2,
            "shading": 0,
            "snow": 0,
            "mismatch": 2,
            "wiring": 2,
            "connections": 0.5,
            "lid": 1.5,
            "nameplate_rating": 1,
            "age": 0,
            "availability": 0,
        },
    },
}
SUNDON = (51.925, -0.611)


def _assets() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "asset_id": ["old6", "new15", "undated20", "small2", "accepted"],
            "status": ["Connected", "Connected", "Connected", "Connected", "Accepted to Connect"],
            "capacity_mw": [6.0, 15.0, 20.0, 2.0, 50.0],
            "date_connected": ["2015-03-30", "2026-02-25", None, "2023-12-01", None],
        }
    )


# ------------------------------------------------------------------------ historical capacity


def test_ltds_reconciliation_dates_undated_asset():
    a = _assets().iloc[:3]
    r = capacity.reconcile_with_ltds(a, 21.0, "2026-05-29", "Sundon 33kV PV")
    assert r["verdict"] == "undated_not_connected_at_snapshot" and r["undated_assets"] == [
        "undated20"
    ]
    r2 = capacity.reconcile_with_ltds(a, 41.0, "2026-05-29", "g")
    assert r2["verdict"] == "undated_connected_at_snapshot"
    r3 = capacity.reconcile_with_ltds(a, 30.0, "2026-05-29", "g")
    assert r3["verdict"] == "inconclusive" and r3["not_connected_before"] is None


def test_active_capacity_respects_commissioning_and_evidence():
    a = _assets()
    ev = {"undated20": capacity.reconcile_with_ltds(a.iloc[:3], 21.0, "2026-05-29", "g")}
    t2024 = pd.Timestamp("2024-06-15T12:00Z")
    ac = capacity.active_capacity(a, t2024, ev).set_index("asset_id")
    assert (
        ac.loc["new15", "activity"] == "NOT_YET_CONNECTED"
        and ac.loc["new15", "active_capacity_mw"] == 0
    )
    assert ac.loc["undated20", "activity"] == "EXCLUDED_BY_EVIDENCE"
    assert ac.loc["accepted", "activity"] == "NOT_CONNECTED"
    assert ac["active_capacity_mw"].sum() == pytest.approx(8.0)
    # with no evidence, undated stays UNDATED and is excluded unless the policy includes it
    ac2 = capacity.active_capacity(a, t2024, {}).set_index("asset_id")
    assert (
        ac2.loc["undated20", "activity"] == "UNDATED"
        and ac2.loc["undated20", "active_capacity_mw"] == 0
    )
    assert capacity.active_capacity(a, t2024, {}, include_undated=True)[
        "active_capacity_mw"
    ].sum() == pytest.approx(28.0)
    # after the snapshot the evidence no longer excludes it
    late = capacity.active_capacity(a, pd.Timestamp("2026-09-01T12:00Z"), ev).set_index("asset_id")
    assert late.loc["undated20", "activity"] == "UNDATED"


# ---------------------------------------------------------------------------------- PV model


def _cf(times: list[str], ghi: list[float], fd: list[float]) -> pd.Series:
    t = pd.DatetimeIndex(pd.to_datetime(times, utc=True))
    comp = irradiance.components(t, np.array(ghi), np.array(fd), *SUNDON, PV_CFG["irradiance"])
    return pv.capacity_factor(comp, PV_CFG["pv"])


def test_pv_night_is_zero_and_bounded():
    cf = _cf(
        ["2024-06-15T00:00Z", "2024-06-15T12:00Z", "2024-06-15T12:00Z", "2024-06-15T12:00Z"],
        [0, 850, 1400, 250],
        [np.nan, 0.15, 0.1, 1.0],
    )
    assert cf.iloc[0] == 0.0
    assert ((cf >= 0) & (cf <= 1)).all()
    assert cf.iloc[1] > 0.8 and cf.iloc[3] < cf.iloc[1]


def test_pv_invalid_input_gives_nan_not_zero():
    cf = _cf(["2024-06-15T12:00Z"], [np.nan], [np.nan])
    assert np.isnan(cf.iloc[0])


def test_irradiance_closure_and_physical_limits():
    t = pd.DatetimeIndex(pd.to_datetime(["2024-06-15T12:00Z", "2024-06-15T20:30Z"], utc=True))
    c = irradiance.components(
        t, np.array([800.0, 30.0]), np.array([0.25, 0.3]), *SUNDON, PV_CFG["irradiance"]
    )
    assert c["dhi"].iloc[0] == pytest.approx(200.0, rel=1e-6)
    beam_h = c["dni"] * np.cos(np.radians(c["zenith"]))
    assert (beam_h + c["dhi"]).iloc[0] == pytest.approx(800.0, rel=1e-6)
    assert c["dni"].iloc[1] == 0.0 and c["dhi"].iloc[1] == pytest.approx(
        30.0
    )  # sun below horizon-ish


# ---------------------------------------------------------------------------- aggregation


def test_pv_to_bus_split_conservation_and_missing():
    shares = aggregate.node_shares({"a": ["B1", "B2", "B3"], "b": ["B4"], "c": ["B4"]})
    pvdf = pd.DataFrame(
        {
            "timestamp": ["t0"] * 3 + ["t1"] * 3,
            "asset_id": ["a", "b", "c"] * 2,
            "active_capacity_mw": [6.0, 2.0, 0.0] * 2,
            "estimated_pv_mw": [3.0, 1.0, np.nan, 3.0, np.nan, np.nan],
            "quality": ["GOOD", "GOOD", "MISSING", "GOOD", "MISSING", "MISSING"],
        }
    )
    bus = aggregate.to_bus(pvdf, shares).set_index(["timestamp", "bus_id"])
    assert bus.loc[("t0", "B1"), "estimated_pv_mw"] == pytest.approx(1.0)
    assert bus.xs("t0")["estimated_pv_mw"].sum() == pytest.approx(4.0)  # conserved
    assert bus.xs("t0")["active_solar_capacity_mw"].sum() == pytest.approx(8.0)
    assert bus.loc[("t0", "B4"), "quality"] == "GOOD"  # inactive asset c ignored
    assert (
        np.isnan(bus.loc[("t1", "B4"), "estimated_pv_mw"])
        and bus.loc[("t1", "B4"), "quality"] == "MISSING"
    )


def test_bus_rules_use_e0_site_link_and_voltage():
    inv = pd.DataFrame(
        {
            "asset_id": ["hv", "lv"],
            "connection_voltage_kv": [33.0, np.nan],
            "attributed_nodes": [["L31", "L32"], ["L31", "L32"]],
            "site_floc": ["F1", "F1"],
        }
    )
    r = aggregate.bus_rules(inv, {"F1": ["L51"]}, {"hv_threshold_kv": 33})
    assert r == {"hv": ["L31", "L32"], "lv": ["L51"]}


# ---------------------------------------------------------------- end-to-end on fixture


def test_forcing_end_to_end_on_product_shaped_data():
    times = ["2024-06-15T00:00Z", "2024-06-15T12:00Z", "2024-06-15T12:15Z"]
    ds = product(times)
    ds["DSSF_TOT"][0] = 0.0
    ds["quality_flag"][0] = 165  # night
    ds["DSSF_TOT"][2] = 250.0
    ds["FRACTION_DIFFUSE"][2] = 1.0
    ds["quality_flag"][2] = CLOUD_OK
    assets = pd.DataFrame(
        {
            "asset_id": ["old6", "small2", "new15"],
            "capacity_mw": [6.0, 2.0, 15.0],
            "lat": [51.9248, 51.9513, 51.9188],
            "lon": [-0.6113, -0.6214, -0.5639],
            "status": ["Connected"] * 3,
            "date_connected": ["2015-03-30", "2023-12-01", "2026-02-25"],
        }
    )
    mapped = geo.map_assets(assets[["asset_id", "capacity_mw", "lat", "lon"]], geo.RegularGrid())
    names = {"total": "DSSF_TOT", "diffuse_fraction": "FRACTION_DIFFUSE", "quality": "quality_flag"}
    s = forcing.sample_assets(ds, mapped, names)
    out = forcing.asset_pv(s, mapped, assets, {}, PV_CFG, allow_low_quality=False)
    assert (out["estimated_pv_mw"] <= out["active_capacity_mw"] + 1e-9).all()
    night = out[out["slot"] == pd.Timestamp("2024-06-15T00:00Z")]
    assert (night["estimated_pv_mw"] == 0).all() and (night["status"] == "NIGHT").all()
    new = out[out["asset_id"] == "new15"]
    assert (new["active_capacity_mw"] == 0).all()  # connected 2026: never in a 2024 scenario
    noon = out[out["slot"] == pd.Timestamp("2024-06-15T12:00Z")].set_index("asset_id")
    cloud = out[out["slot"] == pd.Timestamp("2024-06-15T12:15Z")].set_index("asset_id")
    assert cloud.loc["old6", "capacity_factor"] < noon.loc["old6", "capacity_factor"]
    # assets in nearly the same place get nearly the same forcing
    assert abs(noon.loc["old6", "capacity_factor"] - noon.loc["small2", "capacity_factor"]) < 0.02


def test_invalid_pixel_propagates_as_missing():
    ds = product(["2024-06-15T12:00Z"], flag=np.full((1, 11, 13), FAIL, dtype=np.uint8))
    assets = pd.DataFrame(
        {
            "asset_id": ["x"],
            "capacity_mw": [6.0],
            "lat": [51.9248],
            "lon": [-0.6113],
            "status": ["Connected"],
            "date_connected": ["2015-03-30"],
        }
    )
    mapped = geo.map_assets(assets[["asset_id", "capacity_mw", "lat", "lon"]], geo.RegularGrid())
    names = {"total": "DSSF_TOT", "diffuse_fraction": "FRACTION_DIFFUSE", "quality": "quality_flag"}
    out = forcing.asset_pv(
        forcing.sample_assets(ds, mapped, names), mapped, assets, {}, PV_CFG, False
    )
    assert out["status"].iloc[0] == "INVALID" and np.isnan(out["estimated_pv_mw"].iloc[0])


# --------------------------------------------------------------------------------- events

THR = {
    "min_field_valid": 0.9,
    "min_elevation_deg": 20,
    "asset_ramp_affected": 0.2,
    "significant_ramp": 0.15,
    "recovery_tolerance": 0.05,
    "kc_clear": 0.8,
    "kc_cloudy": 0.4,
}
CLASSES = {
    "A": {
        "min_mean_kc": 0.85,
        "max_std_kc_time": 0.05,
        "max_field_std_kc": 0.06,
        "max_abs_ramp": 0.05,
    },
    "B": {"min_one_step_ramp": 0.4, "min_two_step_ramp": 0.5},
    "C": {"min_sign_changes": 3, "min_significant_ramps": 4, "kc_min": 0.3, "kc_max": 0.85},
    "D": {
        "min_frac_start": 0.7,
        "min_frac_end": 0.7,
        "min_abs_trend_rho": 0.8,
        "min_field_grad": 0.0,
    },
    "E": {"max_mean_kc": 0.3, "max_std_kc_time": 0.05, "max_field_std_kc": 0.06},
}


def _day(
    date: str, cf: list[float], kc: list[float], field_kc: list[float]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    slots = pd.date_range(f"{date}T10:00Z", periods=len(cf), freq="15min")
    a = pd.DataFrame(
        {
            "slot": slots,
            "asset_id": "x",
            "cf": cf,
            "active_capacity_mw": 6.0,
            "kc": kc,
            "usable": True,
        }
    )
    f = pd.DataFrame(
        {
            "slot": slots,
            "field_mean_kc": field_kc,
            "field_std_kc": 0.02,
            "field_grad_kc_per_km": 0.05,
            "field_frac_clear": [1.0 if k >= 0.8 else 0.0 for k in field_kc],
            "field_frac_cloudy": [1.0 if k <= 0.4 else 0.0 for k in field_kc],
            "field_frac_valid": 1.0,
            "elevation": 50.0,
        }
    )
    return a, f


def _synthetic() -> tuple[pd.DataFrame, pd.DataFrame]:
    days = [
        _day("2024-06-01", [0.9] * 12, [0.95] * 12, [0.95] * 12),  # clear
        _day(
            "2024-06-02",
            [0.9] * 5 + [0.3] * 7,
            [0.95] * 5 + [0.3] * 7,
            [0.95] * 4 + [0.6] + [0.3] * 7,
        ),  # ramp/transition
        _day(
            "2024-06-03",
            [0.8, 0.3, 0.8, 0.3, 0.8, 0.3, 0.8, 0.3, 0.8, 0.3, 0.8, 0.3],
            [0.6] * 12,
            [0.6] * 12,
        ),  # broken
        _day("2024-06-04", [0.15] * 12, [0.2] * 12, [0.2] * 12),  # overcast
    ]
    return pd.concat([d[0] for d in days]), pd.concat([d[1] for d in days])


def _run(a: pd.DataFrame, f: pd.DataFrame) -> pd.DataFrame:
    sf = events.slot_features(a, f, 15, THR)
    wf = events.window_features(sf, 12, 15, THR)
    return events.select(events.classify(wf, CLASSES), per_class=2, min_separation_h=24)


def test_event_classes_found_on_synthetic_days():
    sel = _run(*_synthetic())
    by = {
        k: set(sel.loc[sel.event_class == k, "start"].dt.strftime("%m-%d")) for k in events.CLASSES
    }
    assert by["A"] == {"06-01"}
    assert "06-02" in by["B"] and "06-03" in by["C"] and by["E"] == {"06-04"}
    assert "06-02" in by["D"]


def test_event_selection_is_deterministic_and_order_independent():
    a, f = _synthetic()
    s1 = _run(a, f)
    s2 = _run(a.sample(frac=1, random_state=1), f.sample(frac=1, random_state=2))
    pd.testing.assert_frame_equal(s1.reset_index(drop=True), s2.reset_index(drop=True))
    assert events.params_hash({"a": 1, "b": 2}) == events.params_hash({"b": 2, "a": 1})


def test_event_windows_with_invalid_slots_are_skipped():
    a, f = _day("2024-06-01", [0.9] * 12, [0.95] * 12, [0.95] * 12)
    f.loc[f.index[5], "field_frac_valid"] = 0.5
    sf = events.slot_features(a, f, 15, THR)
    assert events.window_features(sf, 12, 15, THR).empty


def test_event_module_cannot_reach_grid_or_genco_outputs():
    import inspect

    mods = {v.__name__ for v in vars(events).values() if inspect.ismodule(v)}
    assert not any(
        m.startswith(("cloud2grid.network", "cloud2grid.genco", "pandapower", "torch"))
        for m in mods
    )

"""Topology-sensitivity scenarios and satellite-suitability spatial metrics."""

import math

import numpy as np
import pandas as pd
import pytest
import yaml

from cloud2grid.evaluation import spatial as sp
from cloud2grid.network import scenarios as scn


def test_load_config_extends_without_touching_baseline(tmp_path):
    base = {
        "scenario": {"name": "base", "changes": []},
        "network": {"slack_vm_pu": 1.0, "x": 1},
        "loads": [{"node": "N", "circuits": [{"line": "L", "positive_into_node": True}]}],
    }
    (tmp_path / "base.yaml").write_text(yaml.safe_dump(base))
    var = {
        "extends": "base.yaml",
        "network": {"x": 2},
        "scenario": {"name": "v", "changes": [{"type": "observed_outages"}]},
    }
    (tmp_path / "v.yaml").write_text(yaml.safe_dump(var))
    cfg = scn.load_config(tmp_path / "v.yaml")
    assert cfg["network"] == {"slack_vm_pu": 1.0, "x": 2}
    assert cfg["scenario"]["name"] == "v" and "extends" not in cfg
    assert yaml.safe_load((tmp_path / "base.yaml").read_text()) == base
    scaled = scn.apply_scales(cfg, {"L": {"factor": 0.8}})
    assert scaled["loads"][0]["circuits"][0]["scale"] == 0.8
    assert "scale" not in cfg["loads"][0]["circuits"][0]  # apply_scales copies


def test_symmetric_ceiling_uses_published_months_only():
    m = pd.DataFrame(
        {
            "ltds_line_name": ["L"] * 4,
            "redacted": ["True", "False", "False", "False"],
            "active_power_month_min_mw": [-99.0, -63.0, -60.0, -50.0],
            "active_power_month_max_mw": [99.0, 62.0, 64.0, 40.0],
        }
    )
    c = scn.symmetric_ceiling(m, "L")
    assert c["n_months"] == 3 and c["median_monthly_max_abs_mw"] == 63.0


def test_detect_outages_rule():
    sim = {"A": 3.5, "B": 0.5, "C": 4.0}
    obs = {"A": 0.0, "B": 0.0, "C": 3.9, "D": 0.0}
    rule = {"max_abs_observed_mw": 0.05, "min_abs_model_mw": 1.0}
    assert scn.detect_outages(sim, obs, rule) == ["A"]


def test_concentration_metrics():
    h = sp.hhi(np.array([20.0, 15.0, 6.0, 2.0]))
    assert h["hhi"] == pytest.approx(sum((c / 43) ** 2 for c in (20, 15, 6, 2)))
    assert 0 <= h["normalised_hhi"] <= 1
    assert sp.hhi(np.ones(5))["normalised_hhi"] == pytest.approx(0.0)
    assert sp.assets_for_share(np.array([20.0, 15.0, 6.0, 2.0]), 0.5) == 2
    assert sp.assets_for_share(np.array([20.0, 15.0, 6.0, 2.0]), 0.95) == 3  # 41/43 >= 95%
    assert sp.assets_for_share(np.array([20.0, 15.0, 6.0, 2.0, 0.9]), 0.95) == 4


def test_pairwise_and_extent():
    lat = np.array([52.0, 52.0])
    lon = np.array([0.0, 0.1])
    d = sp.pairwise_km(lat, lon)
    assert d[0, 1] == pytest.approx(
        0.1 * math.pi / 180 * 6371 * math.cos(math.radians(52)), rel=1e-3
    )
    assert sp.weighted_mean_pairwise_km(np.array([1.0, 3.0]), d) == pytest.approx(d[0, 1])
    assert sp.effective_extent_km(lat, lon, np.array([1.0, 1.0])) == pytest.approx(
        d[0, 1], rel=1e-3
    )


def test_pixel_footprint_is_stretched_at_uk_latitude():
    fp = sp.pixel_footprint(52.0, -0.5)
    assert 3.0 < fp["dx_km"] < 3.5 and 5.5 < fp["dy_km"] < 7.0
    assert 55 < fp["viewing_zenith_deg"] < 65
    nadir = sp.pixel_footprint(0.0, 0.0)
    assert nadir["dx_km"] == pytest.approx(3.0, rel=0.01)


def test_pixel_occupancy_coincident_vs_separated():
    one = sp.pixel_occupancy(
        np.array([52.0, 52.0]),
        np.array([0.0, 0.0]),
        np.array([1.0, 1.0]),
        3.2,
        6.3,
        draws=50,
        seed=1,
    )
    assert one["distinct_pixels_mean"] == 1 and one["effective_independent_pixels"] == 1
    far = sp.pixel_occupancy(
        np.array([52.0, 52.0]),
        np.array([0.0, 0.5]),
        np.array([1.0, 1.0]),
        3.2,
        6.3,
        draws=50,
        seed=1,
    )
    assert far["distinct_pixels_mean"] == 2 and far["effective_independent_pixels"] == 2


def test_classify_h2_levels():
    crit = {
        "STRONG": {
            "effective_independent_pixels_min": 4,
            "weighted_mean_pairwise_km_min": 10,
            "major_ew_span_km_min": 9,
            "normalised_hhi_max": 0.15,
            "p_capable_circuits_min": 3,
        },
        "PLAUSIBLE": {
            "effective_independent_pixels_min": 2,
            "weighted_mean_pairwise_km_min": 5,
            "major_ew_span_km_min": 4.5,
            "normalised_hhi_max": 0.35,
            "p_capable_circuits_min": 1,
        },
    }
    base = {
        "effective_independent_pixels": 3.0,
        "weighted_mean_pairwise_km": 9.4,
        "major_ew_span_km": 11.0,
        "normalised_hhi": 0.24,
        "p_capable_circuits": 3,
    }
    assert sp.classify_h2(base, crit)[0] == "PLAUSIBLE"
    assert sp.classify_h2({**base, "weighted_mean_pairwise_km": 3.3}, crit)[0] == "WEAK"
    strong = {
        **base,
        "effective_independent_pixels": 5,
        "weighted_mean_pairwise_km": 12,
        "normalised_hhi": 0.1,
    }
    assert sp.classify_h2(strong, crit)[0] == "STRONG"

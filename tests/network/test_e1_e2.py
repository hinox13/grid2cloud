"""E1/E2: parameter parsing, pandapower construction, geography, meter mapping, signs, metrics.

Synthetic LTDS-shaped fixture (no UKPN data): a 132 kV slack busbar, one 132/33 kV grid
transformer, a 33 kV hub feeding a primary through two parallel circuits onto one 11 kV
busbar, a tee junction without coordinates, and a composite metered circuit.
"""

import math

import numpy as np
import pandapower as pp
import pandas as pd
import pytest

from cloud2grid.evaluation.metrics import flow_metrics
from cloud2grid.network import measurements as ms
from cloud2grid.network import model
from cloud2grid.network import study_region as sr

EPN = "Eastern Power Networks (EPN)"


def _node(key, kv, role="e0_region", lat=51.9, lon=-0.5, status="resolved"):
    return {
        "node_key": key,
        "role": role,
        "kv": kv,
        "substation_names": key,
        "site_flocs": None,
        "lat": lat if status == "resolved" else None,
        "lon": lon if status == "resolved" else None,
        "geolocation_status": status,
    }


@pytest.fixture
def fixture():
    circuits = pd.DataFrame(
        [
            {
                "id": 1,
                "positive_sequence_impedance_r_percent": 0.01,
                "positive_sequence_impedance_x_percent": 0.02,
                "susceptance_b_percent": 0.2,
                "rating_amps_summer": "678",
                "rating_amps_winter": "765",
                "circuit_length": "0.3",
            },
            {
                "id": 2,
                "positive_sequence_impedance_r_percent": 4.38,
                "positive_sequence_impedance_x_percent": 4.37,
                "susceptance_b_percent": 0.80,
                "rating_amps_summer": "395",
                "rating_amps_winter": "455",
                "circuit_length": "5.2",
            },
            {
                "id": 3,
                "positive_sequence_impedance_r_percent": 5.62,
                "positive_sequence_impedance_x_percent": 5.07,
                "susceptance_b_percent": 1.02,
                "rating_amps_summer": "395",
                "rating_amps_winter": "455",
                "circuit_length": "6.2",
            },
            {
                "id": 4,
                "positive_sequence_impedance_r_percent": 1.0,
                "positive_sequence_impedance_x_percent": 2.0,
                "susceptance_b_percent": 0.0,
                "rating_amps_summer": "400",
                "rating_amps_winter": "450",
                "circuit_length": "2.0",
            },
            {
                "id": 5,
                "positive_sequence_impedance_r_percent": 0.5,
                "positive_sequence_impedance_x_percent": 0.8,
                "susceptance_b_percent": 0.0,
                "rating_amps_summer": "400",
                "rating_amps_winter": "450",
                "circuit_length": None,
            },
        ]
    )
    t2 = pd.DataFrame(
        [
            {
                "id": 10,
                "voltage_hv": 132.0,
                "voltage_lv": 33.0,
                "positive_sequence_impedance_r_percent": 0.4471,
                "positive_sequence_impedance_x_percent": 25.7183,
                "transformer_rating_mva_summer": 90.0,
                "transformer_rating_mva_winter": 120.0,
                "tap_range_min_percent": 79,
                "tap_range_max_percent": 110,
                "vector_group": "YNd1",
                "hv_substation": "G 132kV",
                "lv_substation": "G 33kV",
            },
            {
                "id": 11,
                "voltage_hv": 33.0,
                "voltage_lv": 11.5,
                "positive_sequence_impedance_r_percent": 2.0,
                "positive_sequence_impedance_x_percent": 94.351,
                "transformer_rating_mva_summer": 18.0,
                "transformer_rating_mva_winter": 23.4,
                "tap_range_min_percent": 85,
                "tap_range_max_percent": 105,
                "vector_group": "Dyn11",
                "hv_substation": "P 33kV",
                "lv_substation": "P 11kV",
            },
            {
                "id": 12,
                "voltage_hv": 33.0,
                "voltage_lv": 11.0,
                "positive_sequence_impedance_r_percent": 2.0,
                "positive_sequence_impedance_x_percent": 108.08,
                "transformer_rating_mva_summer": 18.0,
                "transformer_rating_mva_winter": 23.4,
                "tap_range_min_percent": 90,
                "tap_range_max_percent": 110,
                "vector_group": "Dyn11",
                "hv_substation": "P 33kV",
                "lv_substation": "P 11kV",
            },
        ]
    )
    region = {
        "region_id": "BSP:EPN:Test",
        "nodes": [
            _node("EPN:GSP11", 132.0, "boundary_busbar"),
            _node("EPN:G1A", 132.0),
            _node("EPN:G31", 33.0),
            _node("EPN:P31", 33.0),
            _node("EPN:P32", 33.0),
            _node("EPN:TEE31", 33.0, status="unresolved"),
            _node("EPN:C31", 33.0, status="unresolved"),
            _node("EPN:P51", 11.0, "primary_lv_busbar"),
        ],
        "branches": [
            {
                "branch_id": "T1:1",
                "ltds_table": "T1",
                "ltds_id": 1,
                "from": "EPN:G1A",
                "to": "EPN:GSP11",
                "ltds_line_name": "GIS_1",
            },
            {
                "branch_id": "T1:2",
                "ltds_table": "T1",
                "ltds_id": 2,
                "from": "EPN:G31",
                "to": "EPN:P31",
                "ltds_line_name": "G_P_1",
            },
            {
                "branch_id": "T1:3",
                "ltds_table": "T1",
                "ltds_id": 3,
                "from": "EPN:P32",
                "to": "EPN:G31",
                "ltds_line_name": "G_P_2",
            },
            {
                "branch_id": "T1:4",
                "ltds_table": "T1",
                "ltds_id": 4,
                "from": "EPN:G31",
                "to": "EPN:TEE31",
                "ltds_line_name": "G_C_1_(5)",
            },
            {
                "branch_id": "T1:5",
                "ltds_table": "T1",
                "ltds_id": 5,
                "from": "EPN:TEE31",
                "to": "EPN:C31",
                "ltds_line_name": "G_C_1_(6)",
            },
            {
                "branch_id": "T2a:10",
                "ltds_table": "T2a",
                "ltds_id": 10,
                "from": "EPN:G1A",
                "to": "EPN:G31",
                "ltds_line_name": None,
            },
            {
                "branch_id": "T2a:11",
                "ltds_table": "T2a",
                "ltds_id": 11,
                "from": "EPN:P31",
                "to": "EPN:P51",
                "ltds_line_name": None,
            },
            {
                "branch_id": "T2a:12",
                "ltds_table": "T2a",
                "ltds_id": 12,
                "from": "EPN:P32",
                "to": "EPN:P51",
                "ltds_line_name": None,
            },
        ],
        "measurements": {
            "circuits": [
                {
                    "ltds_line_name": "G_P_1",
                    "from_node": "EPN:G31",
                    "to_node": "EPN:P31",
                    "node_match": True,
                },
                {
                    "ltds_line_name": "G_P_2",
                    "from_node": "EPN:G31",
                    "to_node": "EPN:P32",
                    "node_match": True,
                },
                {
                    "ltds_line_name": "G_C_1_(1)",
                    "from_node": "EPN:G31",
                    "to_node": "EPN:C31",
                    "node_match": True,
                },
                {
                    "ltds_line_name": "GIS_1",
                    "from_node": "EPN:G1A",
                    "to_node": "EPN:GSP99",
                    "node_match": False,
                },
            ]
        },
    }
    return circuits, t2, region


# ------------------------------------------------------------------- parameter parsing


def test_circuit_params_percent_on_100mva_base():
    p = model.circuit_params(
        {
            "positive_sequence_impedance_r_percent": 4.38,
            "positive_sequence_impedance_x_percent": 4.37,
            "susceptance_b_percent": 0.80,
            "rating_amps_summer": "395",
            "rating_amps_winter": "455",
            "circuit_length": "5.2",
        },
        33.0,
    )
    zb = 33.0**2 / 100
    assert p["r_ohm_per_km"] == pytest.approx(0.0438 * zb / 5.2)
    assert p["c_nf_per_km"] == pytest.approx(0.008 / zb / (2 * math.pi * 50) * 1e9 / 5.2)
    assert p["max_i_ka"] == pytest.approx(0.395)
    assert 0.08 < p["r_ohm_per_km"] < 0.1  # physically plausible 33 kV cable


def test_circuit_params_missing_values_stay_missing():
    p = model.circuit_params(
        {
            "positive_sequence_impedance_r_percent": None,
            "positive_sequence_impedance_x_percent": 1.0,
            "susceptance_b_percent": 0.1,
            "rating_amps_summer": "x",
            "circuit_length": None,
        },
        33.0,
    )
    assert p["r_ohm_per_km"] is None and p["max_i_ka"] is None
    assert p["length_published"] is None and p["length_km"] == 1.0


def test_transformer_params_rescaled_to_own_rating():
    p = model.transformer_params(
        {
            "transformer_rating_mva_summer": 18.0,
            "positive_sequence_impedance_r_percent": 2.0,
            "positive_sequence_impedance_x_percent": 94.351,
            "voltage_hv": 33.0,
            "voltage_lv": 11.5,
        }
    )
    assert p["vk_percent"] == pytest.approx(math.hypot(2.0, 94.351) * 0.18)
    assert 15 < p["vk_percent"] < 20 and p["vkr_percent"] == pytest.approx(0.36)


# ------------------------------------------------------------- network construction


def test_build_network_scoped_buses_and_provenance(fixture):
    circuits, t2, region = fixture
    net, prov = model.build_network(region, circuits, t2, slack_node="EPN:GSP11")
    assert net.bus["name"].str.match(r"^EPN:").all() and net.bus["name"].is_unique
    assert len(net.line) == 5 and len(net.trafo) == 3 and len(net.ext_grid) == 1
    assert net.bus.set_index("name").at["EPN:P51", "vn_kv"] == 11.0  # primary LV busbar nominal
    classes = set(prov["class"])
    assert {"PUBLISHED", "DERIVED", "ASSUMED", "MISSING"} <= classes
    missing = prov[prov["class"] == "MISSING"]
    assert set(missing["element_id"]) >= {"EPN:TEE31", "EPN:C31"}  # unresolved geography
    assert (
        prov[(prov.element_id == "T1:5") & (prov.parameter == "length_km")]["class"] == "MISSING"
    ).all()


def test_missing_coordinates_are_not_invented(fixture):
    circuits, t2, region = fixture
    net, _ = model.build_network(region, circuits, t2, slack_node="EPN:GSP11")
    b = net.bus.set_index("name")
    assert np.isnan(b.at["EPN:TEE31", "geo_lat"]) and np.isnan(b.at["EPN:TEE31", "geo_lon"])
    assert b.at["EPN:TEE31", "geolocation_status"] == "unresolved"
    assert b.at["EPN:G31", "geo_lat"] == pytest.approx(51.9)


def test_branch_with_missing_impedance_is_not_built(fixture):
    circuits, t2, region = fixture
    circuits = circuits.copy()
    circuits.loc[circuits.id == 4, "positive_sequence_impedance_r_percent"] = None
    net, prov = model.build_network(region, circuits, t2, slack_node="EPN:GSP11")
    assert "G_C_1_(5)" not in set(net.line.name)
    checks = model.structural_checks(net, region)
    assert not checks["checks"]["all_region_branches_built"]["ok"]
    assert not checks["ok"]


def test_structural_checks_and_ac_power_flow(fixture):
    circuits, t2, region = fixture
    net, _ = model.build_network(region, circuits, t2, slack_node="EPN:GSP11")
    checks = model.structural_checks(net, region)
    assert checks["ok"], {k: v for k, v in checks["checks"].items() if not v["ok"]}
    p51 = net.bus.index[net.bus.name == "EPN:P51"][0]
    pp.create_load(net, p51, p_mw=10.0, q_mvar=3.0)
    pp.runpp(net)
    assert net.converged
    losses = net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum()
    assert net.res_ext_grid.p_mw.sum() == pytest.approx(10.0 + losses, abs=1e-6)
    # the two parallel circuits share the primary load according to their impedances
    p1 = net.res_line.p_from_mw[net.line.name == "G_P_1"].iat[0]
    p2 = net.res_line.p_to_mw[net.line.name == "G_P_2"].iat[0]
    assert p1 > 0 and p2 > 0 and abs(p1 + p2 - 10.0) < 0.5


# ------------------------------------------------------- meter mapping and sign rules


def test_map_meters_exact_composite_and_mismatch(fixture):
    circuits, t2, region = fixture
    net, _ = model.build_network(region, circuits, t2, slack_node="EPN:GSP11")
    m = ms.map_meters(region, net, ["G_P_1", "G_P_2", "G_C_1_(1)", "GIS_1"])
    assert m["G_P_1"].mapping == "exact" and m["G_P_1"].end == "from"
    assert m["G_P_2"].mapping == "exact" and m["G_P_2"].end == "to"  # LTDS orientation reversed
    assert m["G_C_1_(1)"].mapping == "node_path"
    assert net.line.at[m["G_C_1_(1)"].index, "name"] == "G_C_1_(5)"
    assert m["GIS_1"].mapping == "name_node_mismatch"


def test_model_flow_active_power_and_current(fixture):
    circuits, t2, region = fixture
    net, _ = model.build_network(region, circuits, t2, slack_node="EPN:GSP11")
    pp.create_load(net, net.bus.index[net.bus.name == "EPN:P51"][0], p_mw=10.0, q_mvar=3.0)
    pp.runpp(net)
    m = ms.map_meters(region, net, ["G_P_1", "G_P_2"])
    p1, i1 = ms.model_flow(net, m["G_P_1"])
    p2, i2 = ms.model_flow(net, m["G_P_2"])
    assert p1 > 0 and p2 > 0  # monthly orientation G31 -> P3x: positive towards the load
    assert i1 > 0 and i2 > 0
    assert i1 == pytest.approx(
        math.sqrt(p1**2 + net.res_line.q_from_mvar.iat[m["G_P_1"].index] ** 2)
        / (math.sqrt(3) * 33.0 * net.res_bus.vm_pu.loc[net.line.from_bus.iat[m["G_P_1"].index]])
        * 1000,
        rel=1e-3,
    )


def _series(tx_p, circuit_p):
    n = len(next(iter(tx_p.values())))
    idx = pd.date_range("2024-01-01", periods=n, freq="30min", tz="UTC")
    return ms.Series(
        circuit_p=pd.DataFrame(circuit_p, index=idx),
        circuit_i=pd.DataFrame(index=idx),
        tx_p=pd.DataFrame(tx_p, index=idx),
        tx_i=pd.DataFrame(index=idx),
    )


def test_transformer_sign_check_accepts_and_rejects():
    rng = np.random.default_rng(0)
    demand = 5 + rng.random(200)
    s = _series({"t": -demand}, {"c": demand})  # tx reports LV->HV positive; circuit into tx
    good = {
        "transformer_series": {
            "t": {
                "positive": "lv_to_hv",
                "evidence": {"circuit": "c", "circuit_positive_into_transformer": True},
            }
        }
    }
    bad = {
        "transformer_series": {
            "t": {
                "positive": "hv_to_lv",
                "evidence": {"circuit": "c", "circuit_positive_into_transformer": True},
            }
        }
    }
    assert ms.check_transformer_signs(good, s)["ok"].all()
    assert not ms.check_transformer_signs(bad, s)["ok"].any()
    assert (ms.transformer_demand(s, "t", "lv_to_hv") > 0).all()


def test_nodal_demand_methods():
    idx = pd.date_range("2024-01-01", periods=3, freq="30min", tz="UTC")
    s = ms.Series(
        circuit_p=pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [0.5, 0.5, np.nan]}, index=idx),
        circuit_i=pd.DataFrame(index=idx),
        tx_p=pd.DataFrame({"tp": [-4.0, -5.0, -6.0]}, index=idx),
        tx_i=pd.DataFrame({"ti": [100.0, 200.0, 300.0]}, index=idx),
    )
    d3 = pd.DataFrame(
        {
            "functional_location": ["F"] * 2,
            "season": ["Winter", "Summer"],
            "maximum_demand_24_25_pf": [0.96, 0.92],
        }
    )
    cfg = {
        "transformer_series": {"tp": {"positive": "lv_to_hv"}},
        "loads": [
            {
                "node": "N1",
                "method": "transformer_active_power",
                "series": ["tp"],
                "pf_site_floc": "F",
            },
            {
                "node": "N2",
                "method": "transformer_current",
                "series": ["ti"],
                "current_kv": 11.0,
                "pf_site_floc": "F",
            },
            {
                "node": "N3",
                "method": "circuit_active_power",
                "pf_site_floc": "F",
                "circuits": [
                    {"line": "a", "positive_into_node": True},
                    {"line": "b", "positive_into_node": False},
                ],
            },
        ],
    }
    d = ms.nodal_demand(cfg, s, d3)
    assert d["N1"]["p_mw"].tolist() == [4.0, 5.0, 6.0] and (d["N1"]["class"] == "OBSERVED").all()
    assert d["N2"]["p_mw"].iat[0] == pytest.approx(
        math.sqrt(3) * 11 * 0.1 * 0.96
    )  # January = Winter
    assert d["N3"]["p_mw"].iat[0] == pytest.approx(0.5) and np.isnan(d["N3"]["p_mw"].iat[2])
    assert d["N1"]["q_mvar"].iat[0] == pytest.approx(4.0 * math.tan(math.acos(0.96)))


# ------------------------------------------------------------ study region / assets


def test_attached_assets_identifier_mapping_only():
    attr = pd.DataFrame(
        {
            "register": [">=1MW", ">=1MW"],
            "energy_source_1": ["Solar", "Solar"],
            "is_solar": [True, True],
            "connection_status": ["Connected", "Connected"],
            "capacity_mw": [20.0, 5.0],
            "energy_source_energy_conversion_technology_1_registered_capacity_mw": [20.0, 5.0],
            "point_of_connection_poc_voltage_kv": [33.0, 33.0],
            "date_connected": [None, None],
            "floc": ["EPN-S1", None],
            "route": ["floc", None],
            "nodes": [frozenset({"EPN:P31"}), frozenset()],
            "latitude": [51.9, 51.95],
            "longitude": [-0.6, -0.4],
        }
    )
    out = sr.attached_assets(attr, {"EPN:P31", "EPN:G31"})
    assert len(out) == 1  # the unattributed asset is NOT placed by proximity
    a = out[0]
    assert a["attributed_nodes"] == ["EPN:P31"] and a["capacity_mw_connected"] == 20.0
    assert a["lat"] == 51.9 and a["connection_voltage_kv"] == 33.0 and a["status"] == "Connected"
    assert "customer_name" not in a


def test_model_branches_extension_rules():
    from cloud2grid.network.ukpn_regions import Region

    branches_all = pd.DataFrame(
        [
            {
                "branch_id": "T1:1",
                "kind": "circuit",
                "from_key": "EPN:G31",
                "to_key": "EPN:P31",
                "from_kv": 33.0,
                "to_kv": 33.0,
            },
            {
                "branch_id": "T2a:10",
                "kind": "transformer",
                "from_key": "EPN:G1A",
                "to_key": "EPN:G31",
                "from_kv": 132.0,
                "to_kv": 33.0,
            },
            {
                "branch_id": "T1:9",
                "kind": "circuit",
                "from_key": "EPN:G1A",
                "to_key": "EPN:GSP11",
                "from_kv": 132.0,
                "to_kv": 132.0,
            },
            {
                "branch_id": "T1:8",
                "kind": "circuit",
                "from_key": "EPN:X11",
                "to_key": "EPN:Y11",
                "from_kv": 132.0,
                "to_kv": 132.0,
            },
        ]
    )
    region = Region(
        "BSP:EPN:Test",
        "bsp_subtree",
        "EPN",
        ("G",),
        frozenset({"EPN:G1A", "EPN:G31", "EPN:P31"}),
        frozenset({"T1:1", "T2a:10"}),
    )
    t2 = pd.DataFrame(
        [
            {
                "id": 11,
                "licencearea": EPN,
                "hv_node": "P31",
                "lv_node": "P51",
                "voltage_hv": 33.0,
                "voltage_lv": 11.0,
                "hv_substation": "P 33kV",
                "lv_substation": "P 11kV",
                "gridsupplypoint": "G",
                "positive_sequence_impedance_r_percent": 2.0,
                "positive_sequence_impedance_x_percent": 90.0,
                "transformer_rating_mva_summer": 18.0,
            }
        ]
    )
    mb = sr.model_branches(region, branches_all, t2).set_index("branch_id")
    assert mb.at["T1:9", "role"] == "boundary_132kv"
    assert "T1:8" not in mb.index  # unrelated 132 kV circuit not pulled in
    assert (
        mb.at["T2a:11", "role"] == "primary_transformer" and mb.at["T2a:11", "to_key"] == "EPN:P51"
    )


# ------------------------------------------------------------------------- metrics


def test_flow_metrics_direction_threshold():
    obs = pd.Series([10.0, -5.0, 0.1, 2.0])
    sim = pd.Series([9.0, -4.0, -0.2, -1.0])
    m = flow_metrics(sim, obs, direction_threshold=0.5)
    assert m["n"] == 4 and m["bias"] == pytest.approx((-1 + 1 - 0.3 - 3) / 4)
    assert m["direction_n"] == 3 and m["direction_agreement"] == pytest.approx(2 / 3)

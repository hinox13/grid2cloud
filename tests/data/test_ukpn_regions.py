"""Region building, geography, solar attribution and scoring on a synthetic LTDS network.

The fixture reuses the node code GRDA31 in EPN and SPN (as LTDS really does, e.g. BROG31) to
check that licence-area scoping keeps unrelated networks apart.
"""

import struct

import pandas as pd
import pytest

from cloud2grid.network import ukpn_audit as ua
from cloud2grid.network import ukpn_regions as ur

EPN, SPN = "Eastern Power Networks (EPN)", "South Eastern Power Networks (SPN)"


def wkb(lon: float, lat: float) -> bytes:
    return b"\x01" + struct.pack("<Idd", 1, lon, lat)


def circuit(i, area, gsp, f, fsub, t, tsub, kv, name, floc=None, r=0.1):
    return {
        "id": i,
        "licencearea": area,
        "gridsupplypoint": gsp,
        "fromnode": f,
        "fromsubstation": fsub,
        "tonode": t,
        "tosubstation": tsub,
        "operating_voltage": kv,
        "linename": name,
        "positive_sequence_impedance_r_percent": r,
        "positive_sequence_impedance_x_percent": 1.0,
        "rating_amps_summer": "400",
        "fromsubstation_sitefunctionallocation": floc,
    }


def tx(i, area, gsp, hv, hvsub, vhv, lv, lvsub, vlv, floc):
    return {
        "id": i,
        "licencearea": area,
        "gridsupplypoint": gsp,
        "hv_node": hv,
        "hv_substation": hvsub,
        "voltage_hv": vhv,
        "lv_node": lv,
        "lv_substation": lvsub,
        "voltage_lv": vlv,
        "positive_sequence_impedance_r_percent": 0.5,
        "positive_sequence_impedance_x_percent": 20.0,
        "transformer_rating_mva_summer": 60.0,
        "sitefunctionallocation": floc,
    }


@pytest.fixture
def net():
    circuits = pd.DataFrame(
        [
            circuit(
                1,
                EPN,
                "Alpha",
                "GSPA11",
                "Alpha 132kV",
                "GRDA11",
                "Grid A 132kV",
                "132",
                "GSPA_GRDA_1",
                "EPN-S0000000C0001",
            ),
            circuit(
                2,
                EPN,
                "Alpha",
                "GRDA31",
                "Grid A 33kV",
                "PRIA31",
                "Pri A 33kV",
                "33",
                "GRDA_PRIA_1",
                "EPN-S0000000D0002",
            ),
            circuit(
                3, EPN, "Alpha", "PRIA31", "Pri A 33kV", "TEE131", "EPN 0001", "33", "PRIA_TEE_1"
            ),
            circuit(
                4,
                EPN,
                "Alpha",
                "TEE131",
                "EPN 0001",
                "PRIB31",
                "Pri B 33kV",
                "33",
                "TEE_PRIB_1",
                r=None,
            ),
            circuit(
                5, EPN, "Alpha", "PRIA51", "Pri A 11kV", "X51", "Somewhere 11kV", "11", "ELEVEN_1"
            ),
            circuit(6, EPN, "Alpha", "LOOP31", "Loop 33kV", "LOOP31", "Loop 33kV", "33", "SELF"),
            circuit(
                7, EPN, "Alpha", "ISL131", "Island 33kV", "ISL231", "Island2 33kV", "33", "ISLAND_1"
            ),
            # SPN reuses GRDA31 — must NOT join the EPN network.
            circuit(
                8,
                SPN,
                "Sigma",
                "GRDA31",
                "Grid S 33kV",
                "ZZZZ31",
                "Pri Z 33kV",
                "33",
                "GRDA_ZZZZ_1",
                "SPN-S000000000008",
            ),
            circuit(
                9, SPN, "Sigma", "ZZZZ31", "Pri Z 33kV", "ZZYY31", "Pri Y 33kV", "33", "GRDA_PRIA_1"
            ),  # same line name as an EPN line → HH area ambiguity
        ]
    )
    t2 = pd.DataFrame(
        [
            tx(
                1,
                EPN,
                "Alpha",
                "GRDA11",
                "Grid A 132kV",
                132.0,
                "GRDA31",
                "Grid A 33kV",
                33.0,
                "EPN-S0000000D0002",
            ),
            tx(
                2,
                EPN,
                "Alpha",
                "PRIA31",
                "Pri A 33kV",
                33.0,
                "PRIA51",
                "Pri A 11kV",
                11.0,
                "EPN-S0000000H0003",
            ),
            tx(
                3,
                EPN,
                "Alpha",
                "PRIB31",
                "Pri B 33kV",
                33.0,
                "PRIB51",
                "Pri B 11kV",
                11.0,
                "EPN-S0000000H0004",
            ),
            tx(
                4,
                SPN,
                "Sigma",
                "SGRD11",
                "Grid S 132kV",
                132.0,
                "GRDA31",
                "Grid S 33kV",
                33.0,
                "SPN-S000000000008",
            ),
        ]
    )
    sites = pd.DataFrame(
        {
            "sitefunctionallocation": [
                "EPN-S0000000C0001",
                "EPN-S0000000D0002",
                "EPN-S0000000H0003",
                "EPN-S0000000H0004",
                "SPN-S000000000008",
            ],
            "licencearea": [EPN, EPN, EPN, EPN, SPN],
            "sitename": [
                "ALPHA 132kV",
                "GRID A 132/33kV",
                "PRI A 33/11kV",
                "PRI B 33/11kV",
                "GRID S 132/33kV",
            ],
            "spatial_coordinates": [
                wkb(0.10, 52.0),
                wkb(0.11, 52.01),
                wkb(0.12, 52.02),
                wkb(0.13, 52.03),
                wkb(1.0, 51.2),
            ],
        }
    )
    sites = ua.add_lat_lon(sites, "spatial_coordinates")
    branches, counters = ur.build_branches(circuits, t2, None)
    return circuits, t2, sites, branches, counters


def test_build_branches_filters_and_scopes(net):
    _, _, _, branches, counters = net
    assert counters["self_loops_skipped"] == 1
    assert "T1:5" not in set(branches["branch_id"])  # 11 kV circuit excluded
    assert set(branches.loc[branches.kind == "transformer", "branch_id"]) == {"T2a:1", "T2a:4"}
    keys = set(branches["from_key"]) | set(branches["to_key"])
    assert {"EPN:GRDA31", "SPN:GRDA31"} <= keys
    assert not branches.loc[branches.branch_id == "T1:4", "params_complete"].iloc[0]


def test_bsp_subtrees_do_not_merge_across_areas(net):
    _, _, _, branches, _ = net
    regions, counters = ur.bsp_subtrees(branches)
    by_area = {r.area: r for r in regions}
    assert set(by_area) == {"EPN", "SPN"}
    assert by_area["EPN"].node_keys == frozenset(
        {"EPN:GRDA11", "EPN:GRDA31", "EPN:PRIA31", "EPN:TEE131", "EPN:PRIB31"}
    )
    assert "SPN:ZZZZ31" not in by_area["EPN"].node_keys
    assert counters == {"unfed_33kv_components": 1, "unfed_33kv_nodes": 2}  # the island


def test_node_table_geography(net):
    circuits, t2, sites, branches, _ = net
    index = ur.substation_floc_index(circuits, t2, None, sites)
    nodes = ur.node_table(branches, index, sites)
    assert nodes.loc["EPN:PRIA31", "coord_status"] == "resolved"
    assert nodes.loc["EPN:PRIA31", "lat"] == pytest.approx(52.02)
    assert nodes.loc["EPN:TEE131", "coord_status"] == "unresolved"  # generic tee point
    assert nodes.loc["EPN:TEE131", "n_specific_names"] == 0
    # Same raw code, different areas → different coordinates.
    assert nodes.loc["SPN:GRDA31", "lat"] == pytest.approx(51.2)


def _solar():
    ecr = pd.DataFrame(
        {
            "primary_resource_type_group": ["Solar PV"] * 4,
            "energy_source_1": ["Solar"] * 4,
            "connection_status": ["Connected"] * 4,
            "already_connected_registered_capacity_mw": [10.0, 2.0, 30.0, 1.0],
            "licence_area": [EPN] * 4,
            "grid_supply_point": ["Alpha"] * 4,
            "bulk_supply_point": ["Grid A 33kV"] * 4,
            "primary": ["-", "Pri B 11kV", "-", "-"],
            "sitefunctionallocation": ["EPN-S0000000H0003", None, "EPN-S0000000D0002", None],
            "point_of_connection_poc_voltage_kv": [33.0, 11.0, 132.0, 11.0],
        }
    )
    return ua.solar_assets(ecr)


def test_attribute_solar_routes_and_voltage(net):
    circuits, t2, sites, branches, _ = net
    nodes = ur.node_table(branches, ur.substation_floc_index(circuits, t2, None, sites), sites)
    idx = ur.site_node_index(circuits, t2, nodes.index)
    attr = ur.attribute_solar(_solar(), nodes["kv"].to_dict(), *idx)
    assert attr["route"].tolist() == ["floc", "primary_name", "floc", "bsp_name"]
    assert attr["nodes"].iloc[0] == frozenset({"EPN:PRIA31"})
    assert attr["nodes"].iloc[1] == frozenset({"EPN:PRIB31"})
    assert attr["nodes"].iloc[2] == frozenset({"EPN:GRDA11"})  # POC 132 kV at a grid site
    assert attr["nodes"].iloc[3] == frozenset({"EPN:GRDA31"})


def _line_status(net, cfg):
    circuits, _, _, branches, _ = net
    monthly = pd.DataFrame(
        {
            "timestamp": ["2023-01-01"] * 4,
            "licence_area": ["EPN", "EPN", "EPN", "SPN"],
            "ltds_line_name": ["GRDA_PRIA_1", "PRIA_TEE_1", "GSPA_GRDA_1", "GRDA_ZZZZ_1"],
            "from_ltds_node": ["GRDA31", "PRIA31", "GSPA11", "GRDA31"],
            "to_ltds_node": ["PRIA31", "TEE131", "GRDA11", "ZZZZ31"],
            "redacted": ["False"] * 4,
            "nominal_voltage": [33, 33, 132, 33],
            "grid_supply_point": ["x"] * 4,
        }
    )
    pub = ua.circuit_publication_status(monthly, cfg.min_public_fraction)
    hh33 = pd.DataFrame(
        {
            "ltds_line_name": ["GRDA_PRIA_1", "PRIA_TEE_1"],
            "n_rows": [100, 100],
            "n_active_power": [100, 0],
            "n_current": [0, 95],
            "first_timestamp": ["2023-01-01"] * 2,
            "last_timestamp": ["2026-08-31"] * 2,
        }
    )
    hh132 = hh33.assign(ltds_line_name=["GSPA_GRDA_1", "unused"])
    coverages = [
        ur.HalfHourlyCoverage("hh33_epn", frozenset({"EPN"}), 33.0, hh33),
        ur.HalfHourlyCoverage("hh132", frozenset({"EPN", "SPN", "LPN"}), 132.0, hh132),
        ur.HalfHourlyCoverage("hh33_multi", frozenset({"SPN", "LPN"}), 33.0, hh33),
    ]
    return ur.build_line_status(branches, circuits, pub, coverages, cfg).set_index(
        ["area", "line_name"]
    )


def test_line_status_current_or_power(net):
    cfg = ur.RankingConfig()
    st = _line_status(net, cfg)
    assert st.loc[("EPN", "GRDA_PRIA_1"), "usable_active_power"]
    assert st.loc[("EPN", "PRIA_TEE_1"), "usable"]  # current only
    assert not st.loc[("EPN", "PRIA_TEE_1"), "usable_active_power"]
    assert st.loc[("EPN", "GSPA_GRDA_1"), "usable_active_power"]
    assert not st.loc[("EPN", "TEE_PRIB_1"), "in_monthly_index"]
    # GRDA_PRIA_1 also exists in SPN → a multi-area HH dataset cannot attribute it.
    assert st.loc[("SPN", "GRDA_PRIA_1"), "hh_status"] == "ambiguous_line_name_across_areas"
    assert st.loc[("SPN", "GRDA_ZZZZ_1"), "hh_status"] == "absent_from_half_hourly"
    assert st.loc[("EPN", "GRDA_PRIA_1"), "node_pair_consistent"]


def test_score_eligibility_and_sensitivity(net):
    circuits, t2, sites, branches, _ = net
    cfg = ur.RankingConfig(min_nodes=1, max_nodes=10, solar_mw_target=50.0)
    st = _line_status(net, cfg).reset_index()
    nodes = ur.node_table(branches, ur.substation_floc_index(circuits, t2, None, sites), sites)
    attr = ur.attribute_solar(
        _solar(), nodes["kv"].to_dict(), *ur.site_node_index(circuits, t2, nodes.index)
    )
    regions, _ = ur.bsp_subtrees(branches)
    ranked = ur.score_regions(regions, branches, nodes, st, attr, cfg).set_index("candidate_region")
    epn = ranked.loc[[i for i in ranked.index if i.startswith("BSP:EPN")][0]]
    assert epn["n_circuits"] == 3 and epn["n_usable_measured_circuits"] == 2
    assert epn["n_usable_active_power_circuits"] == 1
    assert epn["measurement_score"] == pytest.approx((2 / 3 + 1 / 3) / 2)
    assert epn["solar_mw"] == pytest.approx(43.0)  # all four assets attach inside
    assert epn["coordinate_score"] == pytest.approx(4 / 5)  # tee point unresolved

    sel = {
        "require_size_in_band": True,
        "min_usable_measured_circuits": 1,
        "min_usable_active_power_circuits": 1,
        "min_connected_solar_mw": 10.0,
        "min_coordinate_score": 0.6,
    }
    elig = ur.eligibility(ranked.reset_index(), sel)
    assert elig.set_index("candidate_region").loc[epn.name, "eligible"]
    spn = elig[elig.candidate_region.str.startswith("BSP:SPN")].iloc[0]
    assert not spn["eligible"] and "no_active_power_circuit" in spn["ineligible_reasons"]

    sens = ur.weight_sensitivity(elig, cfg, n_draws=200, seed=1)
    assert sens.iloc[0]["candidate_region"] == epn.name
    assert sens.iloc[0]["p_top1"] == 1.0  # only eligible region
    again = ur.weight_sensitivity(elig, cfg, n_draws=200, seed=1)
    pd.testing.assert_frame_equal(sens, again)  # seeded → deterministic

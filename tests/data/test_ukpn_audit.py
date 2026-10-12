"""Parsers and summaries, using the encodings observed in the real UKPN exports (2 Oct 2026)."""

import struct

import pandas as pd
import pytest

from cloud2grid.network import ukpn_audit as ua


def wkb_point(lon: float, lat: float, little: bool = True) -> bytes:
    order = "<" if little else ">"
    return bytes([1 if little else 0]) + struct.pack(order + "Idd", 1, lon, lat)


def test_normalise_name_and_placeholders():
    assert ua.normalise_name("  Ilmer Grid 33kV ") == "ILMER GRID 33KV"
    for placeholder in ["-", "Data not available", " ", None, float("nan")]:
        assert ua.normalise_name(placeholder) is None
    assert ua.is_placeholder("-") and ua.is_placeholder("Data not available")
    assert not ua.is_placeholder(None) and not ua.is_placeholder("Sundon")
    assert ua.normalise_name("Direct") == "DIRECT"  # meaningful value, handled by callers


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("132", 132.0), ("33", 33.0), ("6.6", 6.6), (132, 132.0), ("n/a", None), (None, None)],
)
def test_parse_voltage(raw, expected):
    assert ua.parse_voltage_kv(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"), [("True", True), ("False", False), (True, True), ("maybe", None)]
)
def test_parse_flag_real_encoding(raw, expected):
    assert ua.parse_flag(raw) is expected


def test_parse_point_wkb():
    assert ua.parse_point(wkb_point(1.062809, 52.07025)) == (52.07025, 1.062809)
    assert ua.parse_point(wkb_point(-0.64, 51.88, little=False)) == (51.88, -0.64)
    linestring = b"\x01" + struct.pack("<I", 2) + b"\x00" * 16
    assert ua.parse_point(linestring) == (None, None)
    assert ua.parse_point(wkb_point(0.0, 0.0)) == (None, None)  # outside GB
    assert ua.parse_point({"lat": 51.5, "lon": -0.1}) == (51.5, -0.1)
    assert ua.parse_point(None) == (None, None)


def test_area_node_and_floc_helpers():
    assert ua.licence_area_code("Eastern Power Networks (EPN)") == "EPN"
    assert ua.licence_area_code("SPN") == "SPN"
    assert ua.licence_area_code("Somewhere") is None
    # Same raw node code in two licence areas must give two different keys.
    assert ua.node_key("EPN", "BROG31") != ua.node_key("SPN", "BROG31")
    assert ua.node_key("EPN", None) is None
    assert ua.site_code_from_label("SALL GRID (0D5023)") == "0D5023"
    assert ua.site_code_from_label("Barking 132 kV GIS") is None
    assert ua.floc_from_code("EPN", "0C6047") == "EPN-S0000000C6047"
    assert ua.floc_from_code("SPN", "008462") == "SPN-S000000008462"


def test_missingness_handles_bytes_and_placeholders():
    df = pd.DataFrame(
        {
            "geo": [wkb_point(0.1, 51.0), None, b""],
            "bsp": ["Ilmer Grid 33kV", "-", "Data not available"],
            "n": [1.0, None, 3.0],
        }
    )
    out = ua.missingness(df).set_index("column")
    assert out.loc["geo", "n_null"] == 1 and out.loc["geo", "n_blank"] == 1
    assert out.loc["bsp", "n_placeholder"] == 2 and out.loc["bsp", "n_missing"] == 2
    assert out.loc["n", "n_null"] == 1


def _monthly():
    return pd.DataFrame(
        {
            "timestamp": ["2023-01-01", "2023-02-01", "2023-02-01", "2023-01-01", "2023-01-01"],
            "licence_area": ["EPN", "EPN", "EPN", "SPN", "SPN"],
            "ltds_line_name": ["A_B_1", "A_B_1", "A_B_1", "C_D_1", None],
            "from_ltds_node": ["AAAA31", "AAAA31", "AAAA31", "CCCC31", "X"],
            "to_ltds_node": ["BBBB31", "BBBB31", "BBBB31", "DDDD31", "Y"],
            "redacted": ["False", "False", "True", "True", "False"],
            "nominal_voltage": [33, 33, 33, 33, 33],
            "grid_supply_point": ["SALL GRID (0D5023)"] * 5,
        }
    )


def test_publication_status_duplicate_month_is_not_public():
    status = ua.circuit_publication_status(_monthly(), 0.9).set_index(["area", "line_name"])
    ab = status.loc[("EPN", "A_B_1")]
    # Feb has two rows, one redacted → Feb not public; Jan public.
    assert ab["n_months"] == 2 and ab["n_public_months"] == 1
    assert ab["n_dup_month_rows"] == 1 and not ab["usable_monthly"]
    assert ab["from_node_key"] == "EPN:AAAA31" and ab["n_node_pairs"] == 1
    assert status.loc[("SPN", "C_D_1"), "public_fraction"] == 0.0


def test_publication_counters_count_null_line_names():
    counters = ua.publication_counters(_monthly())
    assert counters["rows_null_line_name"] == 1
    assert counters["rows_unparsed_redacted"] == 0
    assert counters["rows_redacted_true"] == 2


def test_solar_assets_connected_capacity_and_placeholders():
    ecr = pd.DataFrame(
        {
            "primary_resource_type_group": ["Solar PV", "Solar PV", "Fossil fuel", "Storage"],
            "energy_source_1": ["Solar", "Solar", "Fossil - Gas", "Stored Energy"],
            "energy_conversion_technology_2": ["-", "-", "-", "PHOTOVOLTAICS"],
            "connection_status": ["Connected", "Accepted to Connect", "Connected", "Connected"],
            "already_connected_registered_capacity_mw": [20.0, 0.0, 5.0, 1.0],
            "licence_area": ["Eastern Power Networks (EPN)"] * 4,
            "grid_supply_point": ["Sundon"] * 4,
            "bulk_supply_point": ["Sundon 33kV", "-", "Direct", "x"],
            "primary": ["-", "Lewsey Primary 11kV", "-", "-"],
            "sitefunctionallocation": ["EPN-S0000000D8086", None, "x", "y"],
        }
    )
    solar = ua.solar_assets(ecr)
    assert len(solar) == 2
    assert solar["capacity_mw"].tolist()[0] == 20.0
    assert pd.isna(solar["capacity_mw"].tolist()[1])  # not built → no capacity counted
    assert solar["bsp_key"].iloc[0] == "SUNDON 33KV" and pd.isna(solar["bsp_key"].iloc[1])
    counters = ua.solar_counters(ecr, solar)
    assert counters["solar_connected"] == 1 and counters["solar_connected_mw"] == 20.0
    assert counters["solar_only_as_secondary_technology_excluded"] == 1

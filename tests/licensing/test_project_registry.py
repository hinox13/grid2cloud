"""Checks on the real metadata/ registry committed to the repository."""

import pytest

from cloud2grid.licensing import UNVERIFIED, Reason, Registry, Use, check

REQUIRED_SOURCES = {
    "genco_paper",
    "genco_challenge",
    "gridfm_datakit",
    "gridfm_graphkit",
    "eumetsat_eview",
    "eumetsat_ncl_enh",
    "lsa_saf_mdssftd",
    "ukpn_grid_and_primary_sites",
    "ukpn_ltds_table_1_circuit_data",
    "ukpn_ecr_1mw_and_above",
    "ukpn_ecr_under_1mw",
    "ukpn_132kv_operational_half_hourly",
    "ukpn_33kv_operational_half_hourly_spn",
    "pvlib",
    "pandapower",
}


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load()


def test_registry_contains_required_sources(registry):
    assert set(registry.sources) >= REQUIRED_SOURCES


def test_no_raw_data_committed(registry):
    assert all(s.raw_data_committed is False for s in registry.sources.values())


def test_unverified_entries_are_consistent(registry):
    for source_id, source in registry.sources.items():
        if source.licence == UNVERIFIED:
            assert source.licence_verified is None, source_id
        else:
            assert source.licence_verified is not None, source_id
            assert source.licence in registry.licences, source_id


@pytest.mark.parametrize("source_id", ["ukpn_ltds_cim", "genco_challenge"])
def test_unverified_sources_are_blocked(registry, source_id):
    assert check(source_id, Use.DOWNLOAD, registry).reason is Reason.UNVERIFIED_LICENCE


@pytest.mark.parametrize(
    "source_id", ["lsa_saf_mdssftd", "lsa_saf_msg_static", "eumetsat_eview", "eumetsat_ncl_enh"]
)
def test_satellite_products_cleared_for_public_derived_use(registry, source_id):
    for use in (Use.DOWNLOAD, Use.DERIVE, Use.REDISTRIBUTE_DERIVED):
        decision = check(source_id, use, registry)
        assert decision.allowed, (source_id, use)
    assert "EUMETSAT" in registry.sources[source_id].attribution


def test_phase0_sources_pass_gate_for_download(registry):
    for source_id in [
        "genco_pf_datakit_checkpoints",
        "opengridfm_pf_small_case14_ieee",
        "ukpn_grid_and_primary_sites",
        "ukpn_ltds_table_1_circuit_data",
        "ukpn_132kv_operational_monthly",
    ]:
        assert check(source_id, Use.DOWNLOAD, registry).allowed, source_id

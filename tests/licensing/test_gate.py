from pathlib import Path

import pytest
import yaml

from cloud2grid.licensing import (
    LicenceGateError,
    Reason,
    Registry,
    Use,
    attribution_block,
    check,
    require,
)

MANIFEST = {
    "licences": {
        "CC-BY-4.0": {
            "name": "Creative Commons Attribution 4.0 International",
            "url": "https://creativecommons.org/licenses/by/4.0/",
            "permits": [
                "download",
                "process",
                "derive",
                "redistribute_derived",
                "redistribute_raw",
            ],
        },
        "NoDerivs": {
            "name": "Download-and-process only",
            "url": "https://example.org/nd",
            "permits": ["download", "process"],
        },
    }
}


def _source(**overrides):
    record = {
        "kind": "dataset",
        "provider": "Example",
        "name": "Example dataset",
        "identifier": "example",
        "source_url": "https://example.org/data",
        "licence": "CC-BY-4.0",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
        "licence_evidence": "test fixture",
        "redistribution_allowed": True,
        "derivatives_allowed": True,
        "attribution_required": True,
        "attribution": "Contains Example data, CC BY 4.0.",
        "raw_data_committed": False,
        "licence_verified": "2026-10-02",
    }
    record.update(overrides)
    return record


@pytest.fixture
def registry(tmp_path: Path) -> Registry:
    sources = {
        "sources": {
            "verified": _source(),
            "unverified": _source(licence="UNVERIFIED", licence_verified=None),
            "verified_flag_missing_date": _source(licence_verified=None),
            "unknown_licence": _source(licence="Some-Bespoke-Licence"),
            "no_derivs": _source(licence="NoDerivs"),
            "derivs_unknown": _source(derivatives_allowed=None),
            "no_attribution": _source(attribution=None),
        }
    }
    sources_path = tmp_path / "sources.yaml"
    manifest_path = tmp_path / "manifest.yaml"
    sources_path.write_text(yaml.safe_dump(sources))
    manifest_path.write_text(yaml.safe_dump(MANIFEST))
    return Registry.load(sources_path, manifest_path)


def test_unknown_source_fails(registry):
    decision = check("not_registered", Use.DOWNLOAD, registry)
    assert not decision.allowed
    assert decision.reason is Reason.UNKNOWN_SOURCE


def test_unverified_licence_fails(registry):
    decision = check("unverified", Use.DOWNLOAD, registry)
    assert not decision.allowed
    assert decision.reason is Reason.UNVERIFIED_LICENCE


def test_licence_without_verification_date_fails(registry):
    assert check("verified_flag_missing_date", Use.DOWNLOAD, registry).reason is (
        Reason.UNVERIFIED_LICENCE
    )


def test_verified_allowed_source_succeeds(registry):
    decision = require("verified", Use.DOWNLOAD, registry)
    assert decision.allowed
    assert decision.reason is Reason.OK
    assert decision.attribution == "Contains Example data, CC BY 4.0."


def test_require_raises_on_rejection(registry):
    with pytest.raises(LicenceGateError) as excinfo:
        require("unverified", "download", registry)
    assert excinfo.value.decision.reason is Reason.UNVERIFIED_LICENCE


def test_licence_missing_from_manifest_fails(registry):
    assert check("unknown_licence", Use.DOWNLOAD, registry).reason is Reason.UNKNOWN_LICENCE


def test_use_not_permitted_by_licence_fails(registry):
    assert check("no_derivs", Use.PROCESS, registry).allowed
    assert check("no_derivs", Use.DERIVE, registry).reason is Reason.USE_NOT_PERMITTED


def test_unknown_source_flag_restricts_use(registry):
    assert check("derivs_unknown", Use.DOWNLOAD, registry).allowed
    assert check("derivs_unknown", Use.DERIVE, registry).reason is Reason.USE_NOT_PERMITTED
    assert check("derivs_unknown", Use.REDISTRIBUTE_DERIVED, registry).reason is (
        Reason.USE_NOT_PERMITTED
    )


def test_unknown_use_fails(registry):
    assert check("verified", "sell", registry).reason is Reason.UNKNOWN_USE


def test_missing_attribution_fails(registry):
    assert check("no_attribution", Use.DOWNLOAD, registry).reason is Reason.MISSING_ATTRIBUTION


def test_attribution_block_deduplicates(registry):
    block = attribution_block(["verified", "verified", "no_attribution"], registry)
    assert block.splitlines() == [
        "Contains Example data, CC BY 4.0. Licence: https://creativecommons.org/licenses/by/4.0/"
    ]


def test_manifest_must_not_whitelist_unverified(tmp_path):
    (tmp_path / "s.yaml").write_text(yaml.safe_dump({"sources": {}}))
    bad = {"licences": {"UNVERIFIED": {"name": "x", "url": "x", "permits": ["download"]}}}
    (tmp_path / "m.yaml").write_text(yaml.safe_dump(bad))
    with pytest.raises(ValueError, match="UNVERIFIED"):
        Registry.load(tmp_path / "s.yaml", tmp_path / "m.yaml")

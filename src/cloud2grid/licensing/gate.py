"""Fail-closed licence gate (README §39).

source requested
      ↓
source registered?            no → reject
      ↓
licence verified & known?     no → reject
      ↓
intended use allowed?         no → reject
      ↓
attribution stored?           no → reject
      ↓
continue
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from cloud2grid.licensing.registry import Registry, SourceRecord, Use


class Reason(StrEnum):
    OK = "ok"
    UNKNOWN_SOURCE = "unknown_source"
    UNVERIFIED_LICENCE = "unverified_licence"
    UNKNOWN_LICENCE = "licence_not_in_manifest"
    UNKNOWN_USE = "unknown_use"
    USE_NOT_PERMITTED = "use_not_permitted"
    MISSING_ATTRIBUTION = "missing_attribution"


@dataclass(frozen=True)
class LicenceDecision:
    source_id: str
    use: str
    allowed: bool
    reason: Reason
    detail: str
    attribution: str | None = None


class LicenceGateError(PermissionError):
    """Raised by `require` when the gate rejects a request."""

    def __init__(self, decision: LicenceDecision) -> None:
        super().__init__(
            f"Licence gate rejected {decision.use!r} for {decision.source_id!r}: "
            f"{decision.reason.value} — {decision.detail}"
        )
        self.decision = decision


def _source_flags_allow(source: SourceRecord, use: Use) -> bool:
    """Per-source flags can only restrict the licence; `None` (unknown) counts as False."""
    if use is Use.DERIVE:
        return source.derivatives_allowed is True
    if use is Use.REDISTRIBUTE_DERIVED:
        return source.derivatives_allowed is True and source.redistribution_allowed is True
    if use is Use.REDISTRIBUTE_RAW:
        return source.redistribution_allowed is True
    return True


def check(source_id: str, use: Use | str, registry: Registry) -> LicenceDecision:
    """Evaluate the gate without raising. Anything not positively allowed is rejected."""

    def reject(reason: Reason, detail: str) -> LicenceDecision:
        return LicenceDecision(source_id, str(use), False, reason, detail)

    source = registry.sources.get(source_id)
    if source is None:
        return reject(Reason.UNKNOWN_SOURCE, "source is not in metadata/data_sources.yaml")

    if not source.is_verified:
        return reject(
            Reason.UNVERIFIED_LICENCE,
            f"licence={source.licence!r}, licence_verified={source.licence_verified}",
        )

    terms = registry.licences.get(source.licence)
    if terms is None:
        return reject(
            Reason.UNKNOWN_LICENCE,
            f"licence {source.licence!r} has no entry in metadata/licence_manifest.yaml",
        )

    try:
        use = Use(use)
    except ValueError:
        return reject(Reason.UNKNOWN_USE, f"valid uses: {[u.value for u in Use]}")

    if use not in terms.permits:
        return reject(Reason.USE_NOT_PERMITTED, f"{source.licence} does not permit {use.value}")
    if not _source_flags_allow(source, use):
        return reject(
            Reason.USE_NOT_PERMITTED,
            f"source flags: derivatives_allowed={source.derivatives_allowed}, "
            f"redistribution_allowed={source.redistribution_allowed}",
        )

    if source.attribution_required is not False and not (source.attribution or "").strip():
        return reject(Reason.MISSING_ATTRIBUTION, "attribution required but not stored")

    return LicenceDecision(
        source_id, use.value, True, Reason.OK, source.licence, source.attribution
    )


def require(source_id: str, use: Use | str, registry: Registry | None = None) -> LicenceDecision:
    """Return the decision if allowed; raise `LicenceGateError` otherwise."""
    decision = check(source_id, use, registry or Registry.load())
    if not decision.allowed:
        raise LicenceGateError(decision)
    return decision


def attribution_block(source_ids: list[str], registry: Registry) -> str:
    """Attribution text for a set of sources (deduplicated, registry order preserved)."""
    lines: list[str] = []
    for source_id in source_ids:
        source = registry.sources[source_id]
        if not source.attribution:
            continue
        line = " ".join(source.attribution.split())
        if source.licence_url:
            line += f" Licence: {source.licence_url}"
        if line not in lines:
            lines.append(line)
    return "\n".join(lines)

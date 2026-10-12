"""Licence registry and fail-closed licence gate."""

from cloud2grid.licensing.gate import (
    LicenceDecision,
    LicenceGateError,
    Reason,
    attribution_block,
    check,
    require,
)
from cloud2grid.licensing.registry import UNVERIFIED, Registry, SourceRecord, Use

__all__ = [
    "UNVERIFIED",
    "LicenceDecision",
    "LicenceGateError",
    "Reason",
    "Registry",
    "SourceRecord",
    "Use",
    "attribution_block",
    "check",
    "require",
]

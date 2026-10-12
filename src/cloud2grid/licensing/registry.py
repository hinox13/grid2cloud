"""YAML-backed source registry and licence manifest (schemas + loading)."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

UNVERIFIED = "UNVERIFIED"

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCES_PATH = REPO_ROOT / "metadata" / "data_sources.yaml"
DEFAULT_MANIFEST_PATH = REPO_ROOT / "metadata" / "licence_manifest.yaml"


class Use(StrEnum):
    """Intended uses the licence gate can authorise (closed vocabulary)."""

    DOWNLOAD = "download"
    PROCESS = "process"
    DERIVE = "derive"
    REDISTRIBUTE_DERIVED = "redistribute_derived"
    REDISTRIBUTE_RAW = "redistribute_raw"


class SourceRecord(BaseModel):
    """One entry of metadata/data_sources.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["dataset", "software", "model", "paper", "web_page"]
    provider: str
    name: str
    identifier: str
    source_url: str
    documentation_url: str | None = None
    api_dataset_id: str | None = None
    licence: str
    licence_url: str | None = None
    licence_evidence: str
    redistribution_allowed: bool | None = None
    derivatives_allowed: bool | None = None
    attribution_required: bool | None = None
    attribution: str | None = None
    raw_data_committed: Literal[False] = False
    licence_verified: dt.date | None = None
    added_beyond_readme: bool = False
    notes: str | None = None

    @property
    def is_verified(self) -> bool:
        return self.licence != UNVERIFIED and self.licence_verified is not None


class LicenceTerms(BaseModel):
    """One entry of metadata/licence_manifest.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    url: str
    permits: frozenset[Use]
    obligations: list[str] = Field(default_factory=list)


class Registry(BaseModel):
    """Sources plus the licence terms they reference."""

    model_config = ConfigDict(frozen=True)

    sources: dict[str, SourceRecord]
    licences: dict[str, LicenceTerms]

    @classmethod
    def load(
        cls,
        sources_path: Path = DEFAULT_SOURCES_PATH,
        manifest_path: Path = DEFAULT_MANIFEST_PATH,
    ) -> Registry:
        sources_doc = yaml.safe_load(Path(sources_path).read_text()) or {}
        manifest_doc = yaml.safe_load(Path(manifest_path).read_text()) or {}
        if UNVERIFIED in (manifest_doc.get("licences") or {}):
            raise ValueError(f"{UNVERIFIED!r} must not appear in the licence manifest")
        return cls(
            sources=sources_doc.get("sources") or {},
            licences=manifest_doc.get("licences") or {},
        )

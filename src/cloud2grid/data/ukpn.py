"""Minimal client for the UKPN Open Data Portal (Opendatasoft Explore API v2.1).

Catalogue metadata is public. Records and exports are only returned to a logged-in account:
anonymous exports succeed with HTTP 200 but contain zero rows, so `export` treats an empty
result for a non-empty dataset as an access failure rather than as valid data.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq
import requests


class UKPNAccessError(RuntimeError):
    """Records could not be retrieved (missing/invalid API key or access restriction)."""


@dataclass(frozen=True)
class DatasetMetadata:
    dataset_id: str
    title: str
    licence: str | None
    licence_url: str | None
    records_count: int | None
    modified: str | None
    data_visible: bool | None
    fields: tuple[str, ...]
    attributions: tuple[str, ...]

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> DatasetMetadata:
        meta = payload.get("metas", {}).get("default", {})
        return cls(
            dataset_id=payload["dataset_id"],
            title=meta.get("title", ""),
            licence=meta.get("license"),
            licence_url=meta.get("license_url"),
            records_count=meta.get("records_count"),
            modified=meta.get("modified"),
            data_visible=payload.get("data_visible"),
            fields=tuple(f["name"] for f in payload.get("fields", [])),
            attributions=tuple(meta.get("attributions") or ()),
        )


# Opendatasoft licence labels → SPDX-style identifiers used in metadata/licence_manifest.yaml.
ODS_LICENCE_TO_ID = {"CC BY 4.0": "CC-BY-4.0"}


class UKPNClient:
    def __init__(self, base_url: str, api_key: str | None = None, timeout_s: float = 600) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.session = requests.Session()
        if api_key:
            self.session.headers["Authorization"] = f"Apikey {api_key}"

    @classmethod
    def from_config(cls, portal: dict[str, Any]) -> UKPNClient:
        return cls(
            base_url=portal["base_url"],
            api_key=os.environ.get(portal["api_key_env"]) or None,
            timeout_s=portal.get("timeout_s", 600),
        )

    def _dataset_url(self, dataset_id: str) -> str:
        return f"{self.base_url}/catalog/datasets/{dataset_id}"

    def metadata(self, dataset_id: str) -> DatasetMetadata:
        response = self.session.get(self._dataset_url(dataset_id), timeout=60)
        response.raise_for_status()
        return DatasetMetadata.from_api(response.json())

    def export_url(self, dataset_id: str, fmt: str = "parquet") -> str:
        return f"{self._dataset_url(dataset_id)}/exports/{fmt}"

    def export_parquet(
        self,
        dataset_id: str,
        dest: Path,
        params: dict[str, str] | None = None,
        expected_records: int | None = None,
    ) -> int:
        """Stream an export to `dest` (Parquet). Returns the number of rows written."""
        if not self.api_key:
            raise UKPNAccessError(
                f"{dataset_id}: no API key configured — UKPN records require a registered account"
            )
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        with self.session.get(
            self.export_url(dataset_id), params=params, stream=True, timeout=self.timeout_s
        ) as response:
            _raise_for_status(dataset_id, response)
            with tmp.open("wb") as fh:
                for chunk in response.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
        n_rows = pq.ParquetFile(tmp).metadata.num_rows
        if n_rows == 0 and (expected_records or 0) > 0:
            tmp.unlink()
            raise UKPNAccessError(
                f"{dataset_id}: export returned 0 rows but the catalogue reports "
                f"{expected_records} records — access is restricted for this account"
            )
        tmp.replace(dest)
        return n_rows

    def export_aggregate(self, dataset_id: str, params: dict[str, str], dest: Path) -> int:
        """Run an ODSQL `group_by` aggregation server-side and store the result as Parquet.

        Parquet exports reject grouping (`AggregationNotSupported`), so the JSON export is used.
        Only the aggregate (one row per group) is transferred.
        """
        if not self.api_key:
            raise UKPNAccessError(
                f"{dataset_id}: no API key configured — UKPN records require a registered account"
            )
        response = self.session.get(
            self.export_url(dataset_id, "json"), params=params, timeout=self.timeout_s
        )
        _raise_for_status(dataset_id, response)
        rows = response.json()
        if not rows:
            raise UKPNAccessError(f"{dataset_id}: aggregation returned no groups")
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_parquet(dest, index=False)
        return len(rows)


def _raise_for_status(dataset_id: str, response: requests.Response) -> None:
    """Raise with the server's error code/message (never echoes request headers)."""
    if response.status_code < 400:
        return
    try:
        body = response.json()
        detail = f"{body.get('error_code')}: {body.get('message')}"
    except ValueError:
        detail = response.reason
    error = UKPNAccessError if response.status_code in (401, 403) else RuntimeError
    raise error(f"{dataset_id}: HTTP {response.status_code} {detail}")

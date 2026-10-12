"""Download half-hourly operational series for ONE study region only (E1/E2).

    uv run --env-file .env python scripts/download_region_timeseries.py \
        [--region configs/networks/study_region.yaml] [--refresh]

Full UKPN half-hourly datasets (tens of millions of rows) are never downloaded: each request
filters server-side with ODSQL `where ltds_line_name in (...)` / `where tx_id in (...)`, using
the identifiers frozen in study_region.yaml. Every extract is licence-gated and recorded in
metadata/provenance.json (URL, filter, timestamp, size, SHA-256).

Outputs
    data/raw/ukpn/regions/<slug>/<series>.parquet          raw extracts (gitignored)
    data/interim/<slug>/circuits_active_power.parquet       P-capable circuits
    data/interim/<slug>/circuits_current_only.parquet       current-only circuits
    reports/tables/e1_measurement_series.csv               per-series classification
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from cloud2grid.data.ukpn import UKPNClient
from cloud2grid.licensing import Registry, Use, require
from cloud2grid.licensing.registry import REPO_ROOT
from cloud2grid.utils import provenance

DATA_CONFIG = REPO_ROOT / "configs" / "data" / "ukpn.yaml"
DEFAULT_REGION = REPO_ROOT / "configs" / "networks" / "study_region.yaml"

# Registry source → (portal dataset id, identifier column)
SERIES_SOURCES = {
    "ukpn_33kv_operational_half_hourly_epn": "ltds_line_name",
    "ukpn_33kv_operational_half_hourly_spn": "ltds_line_name",
    "ukpn_132kv_operational_half_hourly": "ltds_line_name",
    "ukpn_grid_transformer_half_hourly": "tx_id",
    "ukpn_primary_transformer_half_hourly_epn": "tx_id",
}
COVERAGE_TO_SOURCE = {
    "op_33kv_epn_half_hourly": "ukpn_33kv_operational_half_hourly_epn",
    "op_33kv_spn_half_hourly": "ukpn_33kv_operational_half_hourly_spn",
    "op_132kv_half_hourly": "ukpn_132kv_operational_half_hourly",
}
MIN_COMPLETENESS = 0.5  # share of non-null half-hours to call a series P-capable / I-capable


def slug(region_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", region_id.lower()).strip("_")


def in_clause(column: str, values: list[str]) -> str:
    quoted = ", ".join('"' + v.replace('"', '\\"') + '"' for v in sorted(set(values)))
    return f"{column} in ({quoted})"


def requests_for(region: dict[str, Any]) -> dict[str, list[str]]:
    """Registry source id → identifiers to fetch."""
    wanted: dict[str, list[str]] = {}
    for c in region["measurements"]["circuits"]:
        if c["half_hourly"]:
            src = COVERAGE_TO_SOURCE[c["half_hourly"]["dataset"]]
            wanted.setdefault(src, []).append(c["ltds_line_name"])
    for key, src in [
        ("grid_transformers", "ukpn_grid_transformer_half_hourly"),
        ("primary_transformers", "ukpn_primary_transformer_half_hourly_epn"),
    ]:
        ids = [t["tx_id"] for t in region["measurements"][key]]
        if ids:
            wanted[src] = ids
    return wanted


def classify(df: pd.DataFrame, id_col: str) -> pd.DataFrame:
    g = df.groupby(id_col)
    out = pd.DataFrame(
        {
            "rows": g.size(),
            "active_power_completeness": g["active_power_mw"].apply(lambda s: s.notna().mean()),
            "current_completeness": g["current_amps"].apply(lambda s: s.notna().mean()),
            "first": g["timestamp"].min(),
            "last": g["timestamp"].max(),
        }
    )
    out["class"] = "no_measurement"
    out.loc[out["current_completeness"] >= MIN_COMPLETENESS, "class"] = "current_only"
    out.loc[out["active_power_completeness"] >= MIN_COMPLETENESS, "class"] = "active_power"
    return out.reset_index().rename(columns={id_col: "series_id"})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--region", type=Path, default=DEFAULT_REGION)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    region = yaml.safe_load(args.region.read_text())
    cfg = yaml.safe_load(DATA_CONFIG.read_text())
    registry = Registry.load()
    client = UKPNClient.from_config(cfg["portal"])
    name = slug(region["region_id"])
    raw_dir = REPO_ROOT / "data" / "raw" / "ukpn" / "regions" / name
    interim = REPO_ROOT / "data" / "interim" / name

    frames, classes = {}, []
    for source_id, ids in requests_for(region).items():
        require(source_id, Use.DOWNLOAD, registry)
        source = registry.sources[source_id]
        id_col = SERIES_SOURCES[source_id]
        dest = raw_dir / f"{source_id}.parquet"
        where = in_clause(id_col, ids)
        if args.refresh or not dest.exists():
            n = client.export_parquet(source.api_dataset_id, dest, {"where": where})
            provenance.record(
                dest,
                source_id=source_id,
                url=client.export_url(source.api_dataset_id),
                licence=source.licence,
                extra={
                    "export_params": {"where": where},
                    "n_rows": n,
                    "region_id": region["region_id"],
                },
            )
            print(f"downloaded {source_id}: {n} rows")
        df = pd.read_parquet(dest)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        for col in ("active_power_mw", "current_amps"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        missing = sorted(set(ids) - set(df[id_col].dropna()))
        if missing:
            print(f"  {source_id}: no rows for {missing}")
        frames[source_id] = df
        cls = classify(df, id_col).assign(source_id=source_id, requested=True)
        cls = pd.concat(
            [
                cls,
                pd.DataFrame(
                    {
                        "series_id": missing,
                        "source_id": source_id,
                        "class": "absent_from_dataset",
                        "requested": True,
                    }
                ),
            ],
            ignore_index=True,
        )
        classes.append(cls)

    table = pd.concat(classes, ignore_index=True)
    out_csv = REPO_ROOT / "reports" / "tables" / "e1_measurement_series.csv"
    table.to_csv(out_csv, index=False)

    interim.mkdir(parents=True, exist_ok=True)
    circuits = pd.concat(
        [f.assign(source_id=s) for s, f in frames.items() if SERIES_SOURCES[s] == "ltds_line_name"],
        ignore_index=True,
    )
    cls = table.set_index("series_id")["class"]
    circuits["class"] = circuits["ltds_line_name"].map(cls)
    circuits[circuits["class"] == "active_power"].to_parquet(
        interim / "circuits_active_power.parquet", index=False
    )
    circuits[circuits["class"] == "current_only"].to_parquet(
        interim / "circuits_current_only.parquet", index=False
    )
    tx = pd.concat(
        [f.assign(source_id=s) for s, f in frames.items() if SERIES_SOURCES[s] == "tx_id"],
        ignore_index=True,
    )
    tx.to_parquet(interim / "transformers.parquet", index=False)
    print(table[["source_id", "series_id", "rows", "class"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

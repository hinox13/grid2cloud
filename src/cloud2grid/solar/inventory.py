"""Sundon PV inventory: E0-attributed solar assets + ECR history fields + LTDS T5 evidence.

The asset list and electrical link come from the generated study region
(configs/networks/study_region.yaml, E0 attribution — authoritative). Only non-identifying ECR
fields are joined (dates, status, capacities, flags); customer fields are never read out.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from cloud2grid.licensing.registry import REPO_ROOT
from cloud2grid.solar import capacity as capm

ECR_FIELDS = [
    "date_connected",
    "date_accepted",
    "target_energisation_date",
    "last_updated",
    "flexible_connection_yes_no",
    "in_a_connection_queue_y_n",
    "maximum_export_capacity_mw",
    "bulk_supply_point",
    "primary",
    "point_of_connection_poc_voltage_kv",
]


def _clean(v: Any) -> Any:
    if isinstance(v, bytes):
        return v.decode("latin-1")
    return v


def asset_id(ecr_row: int) -> str:
    """E0 identifier: row of the concatenated ECR (>=1MW register first, then <1MW), as in
    reports/tables/e0_ukpn_solar_attribution.csv and the study region."""
    return f"ECR:{int(ecr_row)}"


def load(cfg: dict[str, Any], root: Path = REPO_ROOT) -> pd.DataFrame:
    """One row per E0-attributed solar asset of the study region (connected and accepted)."""
    region = yaml.safe_load((root / cfg["inventory"]["study_region"]).read_text())
    a = pd.DataFrame(region["assets"])
    a = a[a["is_solar"]].copy()
    raw = {
        ">=1MW": pd.read_parquet(root / cfg["inventory"]["ecr_raw"]),
        "<1MW": pd.read_parquet(root / cfg["inventory"]["ecr_raw_small"]),
    }
    offset = {">=1MW": 0, "<1MW": len(raw[">=1MW"])}  # E0 concatenation order
    extra = []
    for r in a.itertuples():
        # The two registers name some columns differently; absent fields become None.
        row = raw[r.ecr_register].loc[int(r.ecr_row) - offset[r.ecr_register]].reindex(ECR_FIELDS)
        extra.append({k: _clean(row[k]) if pd.notna(row[k]) else None for k in ECR_FIELDS})
    a = pd.concat([a.reset_index(drop=True), pd.DataFrame(extra)], axis=1)
    a = a.loc[:, ~a.columns.duplicated(keep="first")]
    a["asset_id"] = [asset_id(r) for r in a.ecr_row]
    connected = a["status"].eq("Connected")
    a["capacity_mw"] = np.where(connected, a["capacity_mw_connected"], a["registered_capacity_mw"])
    a["date_connected"] = a["date_connected"].where(a["date_connected"].notna(), None)
    keep = [
        "asset_id",
        "ecr_register",
        "ecr_row",
        "technology",
        "status",
        "capacity_mw",
        "registered_capacity_mw",
        "connection_voltage_kv",
        "date_connected",
        "date_accepted",
        "target_energisation_date",
        "last_updated",
        "flexible_connection_yes_no",
        "in_a_connection_queue_y_n",
        "bulk_supply_point",
        "primary",
        "site_floc",
        "attribution_route",
        "attributed_nodes",
        "lat",
        "lon",
    ]
    return (
        a[keep]
        .sort_values(["status", "capacity_mw"], ascending=[True, False])
        .reset_index(drop=True)
    )


def ltds_evidence(
    inv: pd.DataFrame, cfg: dict[str, Any], root: Path = REPO_ROOT
) -> tuple[dict[str, dict], list[dict]]:
    """Reconcile each configured group against LTDS T5; returns (asset_id → result, results)."""
    c = cfg["capacity"]
    t5 = pd.read_parquet(root / cfg["inventory"]["ltds_t5"])
    for col in t5.columns:
        if t5[col].dtype == object:
            t5[col] = t5[col].map(_clean)
    by_asset, results = {}, []
    for g in c["reconciliation_groups"]:
        sel = t5.copy()
        for k, v in g["ltds"].items():
            sel = sel[sel[k].astype(str) == str(v)]
        sel = sel[sel["connected_accepted"] == "Connected"]
        ltds_mw = float(sel["installedcapacity_mva"].sum()) / c["ltds_mva_per_mw"]
        members = inv[(inv["status"] == "Connected") & (inv["ecr_register"] == ">=1MW")]
        for k, v in g["ecr"].items():
            col = "connection_voltage_kv" if k == "connection_voltage_kv" else k
            members = members[members[col].astype(str) == str(v)]
        res = capm.reconcile_with_ltds(
            members[["asset_id", "capacity_mw", "date_connected"]],
            ltds_mw,
            c["ltds_snapshot"],
            g["group"],
        )
        res["ltds_rows"] = sel["id"].astype(str).tolist()
        results.append(res)
        for aid in res["undated_assets"]:
            by_asset[aid] = res
    return by_asset, results

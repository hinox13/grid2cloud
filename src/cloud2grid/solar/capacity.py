"""Historically active PV capacity (never apply today's ECR capacity blindly to the past).

Per asset and timestamp t the status is one of:

    ACTIVE                connected, ECR `date_connected` <= t
    NOT_YET_CONNECTED     connected later: `date_connected` > t
    NOT_CONNECTED         ECR status is not "Connected" (accepted / in queue only)
    EXCLUDED_BY_EVIDENCE  connected but undated, and published evidence shows it was not
                          connected before a known date (see `reconcile_with_ltds`)
    UNDATED               connected, no date and no evidence either way: uncertain; the
                          policy decides (default: excluded and reported)

Only ACTIVE (and UNDATED when the policy includes it) contribute capacity.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Any

import numpy as np
import pandas as pd


class Activity(StrEnum):
    ACTIVE = "ACTIVE"
    NOT_YET_CONNECTED = "NOT_YET_CONNECTED"
    NOT_CONNECTED = "NOT_CONNECTED"
    EXCLUDED_BY_EVIDENCE = "EXCLUDED_BY_EVIDENCE"
    UNDATED = "UNDATED"


def _ts(x: Any) -> pd.Timestamp | None:
    if x is None or (isinstance(x, float) and np.isnan(x)) or x == "":
        return None
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def reconcile_with_ltds(
    assets: pd.DataFrame, ltds_connected_mw: float, snapshot: str, group: str, tol_mw: float = 0.05
) -> dict[str, Any]:
    """Use an LTDS Table 5 connected-capacity snapshot to date undated assets in one group.

    `assets` = the connected ECR assets of one LTDS (substation, voltage, fuel) group with
    columns asset_id, capacity_mw, date_connected. If the dated assets connected before the
    snapshot already explain the LTDS figure (within `tol_mw`), the undated assets were not
    yet connected at the snapshot date → they are EXCLUDED_BY_EVIDENCE before that date.
    """
    snap = _ts(snapshot)
    dated = assets[assets["date_connected"].map(_ts).notna()]
    dated_before = dated[dated["date_connected"].map(lambda d: _ts(d) <= snap)]
    undated = assets[assets["date_connected"].map(_ts).isna()]
    explained = float(dated_before["capacity_mw"].sum())
    undated_mw = float(undated["capacity_mw"].sum())
    if abs(explained - ltds_connected_mw) <= tol_mw and len(undated):
        verdict = "undated_not_connected_at_snapshot"
    elif abs(explained + undated_mw - ltds_connected_mw) <= tol_mw and len(undated):
        verdict = "undated_connected_at_snapshot"
    elif not len(undated):
        verdict = "no_undated_assets"
    else:
        verdict = "inconclusive"
    return {
        "group": group,
        "ltds_snapshot": snapshot,
        "ltds_connected_mw": ltds_connected_mw,
        "dated_connected_before_snapshot_mw": explained,
        "dated_assets": sorted(map(str, dated_before["asset_id"])),
        "undated_assets": sorted(map(str, undated["asset_id"])),
        "undated_mw": undated_mw,
        "verdict": verdict,
        "not_connected_before": snapshot
        if verdict == "undated_not_connected_at_snapshot"
        else None,
        "connected_by": snapshot if verdict == "undated_connected_at_snapshot" else None,
    }


def activity(
    asset: dict[str, Any], t: dt.datetime | pd.Timestamp, evidence: dict[str, dict[str, Any]]
) -> tuple[Activity, str]:
    """Status of one asset at time t, with the reason. `evidence` maps asset_id → a
    reconciliation result (from `reconcile_with_ltds`) that applies to it."""
    t = _ts(t)
    if str(asset.get("status", "")).strip() != "Connected":
        return Activity.NOT_CONNECTED, f"ECR status '{asset.get('status')}'"
    d = _ts(asset.get("date_connected"))
    if d is not None:
        if d <= t:
            return Activity.ACTIVE, f"date_connected {d.date()} <= {t.date()}"
        return Activity.NOT_YET_CONNECTED, f"date_connected {d.date()} > {t.date()}"
    ev = evidence.get(str(asset["asset_id"]))
    if ev and ev.get("not_connected_before") and t < _ts(ev["not_connected_before"]):
        return (
            Activity.EXCLUDED_BY_EVIDENCE,
            f"undated; LTDS T5 snapshot {ev['ltds_snapshot']} for {ev['group']} is explained "
            f"by dated assets only → not connected before {ev['not_connected_before']}",
        )
    if ev and ev.get("connected_by") and t >= _ts(ev["connected_by"]):
        return Activity.ACTIVE, f"undated; included in LTDS T5 snapshot {ev['ltds_snapshot']}"
    return Activity.UNDATED, "connected, no date_connected and no dating evidence"


def active_capacity(
    assets: pd.DataFrame,
    t: dt.datetime | pd.Timestamp,
    evidence: dict[str, dict[str, Any]],
    include_undated: bool = False,
) -> pd.DataFrame:
    """Per-asset active capacity at t: columns activity, reason, active_capacity_mw."""
    rows = []
    for a in assets.to_dict("records"):
        act, why = activity(a, t, evidence)
        on = act == Activity.ACTIVE or (act == Activity.UNDATED and include_undated)
        rows.append(
            {
                "asset_id": a["asset_id"],
                "activity": act.value,
                "reason": why,
                "active_capacity_mw": float(a["capacity_mw"]) if on else 0.0,
                "uncertain": act == Activity.UNDATED,
            }
        )
    return pd.DataFrame(rows)

"""PV assets → electrical nodes → per-bus time series (README §12: P_PV(bus,t) = Σ P_PV(asset_i,t)).

The electrical link is E0's identifier attribution (site FLOC → the site's region nodes); it is
never re-derived from geography. Within the linked site the injection node set depends on the
connection voltage (`bus_rule` per asset, from configs/experiments/e3_pv_model.yaml):

    33 kV assets           the site's 33 kV busbar nodes (E0 `attributed_nodes`)
    11 kV / LV assets      the model load nodes of the same site FLOC (network config `loads`)

When a set has several nodes and the published data do not say which section the asset is on,
the asset is split EQUALLY across them (ASSUMED; `bus_split: equal`).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from cloud2grid.satellite.quality import Status

# Worst-first ordering used to summarise a bus from its assets.
_SEVERITY = [
    Status.MISSING.value,
    Status.INVALID.value,
    Status.OUT_OF_RANGE.value,
    Status.LOW_QUALITY.value,
    Status.GOOD.value,
    Status.NIGHT.value,
]


def node_shares(asset_nodes: dict[str, list[str]]) -> pd.DataFrame:
    """Long table asset_id → node, share (equal split)."""
    rows = [
        {"asset_id": a, "bus_id": n, "share": 1.0 / len(nodes)}
        for a, nodes in asset_nodes.items()
        for n in nodes
    ]
    return pd.DataFrame(rows)


def to_bus(pv: pd.DataFrame, shares: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-asset rows to per-bus rows.

    `pv`: timestamp, asset_id, active_capacity_mw, estimated_pv_mw, quality.
    Returns timestamp, bus_id, active_solar_capacity_mw, estimated_pv_mw, n_assets_active,
    n_assets_missing, quality. A bus with any active asset lacking a value gets NaN power
    (never a silent partial sum) and the worst contributing quality.
    """
    m = pv.merge(shares, on="asset_id", how="inner")
    m["cap"] = m["active_capacity_mw"] * m["share"]
    m["p"] = m["estimated_pv_mw"] * m["share"]
    active = m["active_capacity_mw"] > 0
    m["missing"] = active & ~np.isfinite(m["estimated_pv_mw"])

    def worst(q: pd.Series) -> str:
        present = set(q)
        return next((s for s in _SEVERITY if s in present), "NO_ACTIVE_ASSET")

    g = m.groupby(["timestamp", "bus_id"], sort=True)
    out = g.agg(
        active_solar_capacity_mw=("cap", "sum"),
        estimated_pv_mw=("p", lambda s: s.sum(min_count=1)),
        n_assets_active=("active_capacity_mw", lambda s: int((s > 0).sum())),
        n_assets_missing=("missing", "sum"),
    ).reset_index()
    q = (
        m[active]
        .groupby(["timestamp", "bus_id"])["quality"]
        .agg(worst)
        .rename("quality")
        .reset_index()
    )
    out = out.merge(q, on=["timestamp", "bus_id"], how="left")
    out["quality"] = out["quality"].fillna("NO_ACTIVE_ASSET")
    out.loc[out["n_assets_missing"] > 0, "estimated_pv_mw"] = np.nan
    out.loc[out["n_assets_active"] == 0, "estimated_pv_mw"] = 0.0
    out["n_assets_missing"] = out["n_assets_missing"].astype(int)
    return out


def bus_rules(
    inventory: pd.DataFrame, site_load_nodes: dict[str, list[str]], rules: dict[str, Any]
) -> dict[str, list[str]]:
    """Injection node set per asset from its E0 attribution and connection voltage."""
    out = {}
    for a in inventory.to_dict("records"):
        kv = a.get("connection_voltage_kv")
        if kv is not None and np.isfinite(kv) and kv >= rules["hv_threshold_kv"]:
            out[a["asset_id"]] = list(a["attributed_nodes"])
        else:
            nodes = site_load_nodes.get(a.get("site_floc"), [])
            out[a["asset_id"]] = list(nodes) if nodes else list(a["attributed_nodes"])
    return out

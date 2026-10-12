"""Freeze a study region's membership (nodes, branches, sites, assets, measurement series).

The E0-D region (`Region` from ukpn_regions) is recorded exactly. For E1 it is extended by two
deterministic, identifier-based rules — nothing is added by proximity or by hand:

    boundary     132 kV LTDS circuits with an endpoint at a region 132 kV node (the grid
                 transformers' HV side), plus their other endpoint (the upstream busbar)
    primaries    every LTDS T2a transformer whose HV node is a region 33 kV node, plus its LV
                 node (the primary 11 kV busbar where observed demand is connected)

Measurement series are linked by LTDS identifiers: circuits by monthly-index from/to node keys,
transformers by the transformer monthly index `hv_ltds_node`/`lv_ltds_node`.
No customer-identifying ECR fields are written.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

from cloud2grid.network import ukpn_audit as ua
from cloud2grid.network import ukpn_regions as ur


def _none(value: Any) -> Any:
    if isinstance(value, float) and pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def model_branches(region: ur.Region, branches_all: pd.DataFrame, t2: pd.DataFrame) -> pd.DataFrame:
    """E0 region branches + boundary 132 kV circuits + primary transformers, with a `role`."""
    e0 = branches_all[branches_all["branch_id"].isin(region.branch_ids)].assign(role="e0_region")
    hv132 = {
        k
        for k in region.node_keys
        if branches_all.loc[
            (branches_all["from_key"] == k) | (branches_all["to_key"] == k), "from_kv"
        ]
        .eq(132.0)
        .any()
    }
    boundary = branches_all[
        (branches_all["kind"] == "circuit")
        & (branches_all["from_kv"] == 132.0)
        & (branches_all["from_key"].isin(hv132) | branches_all["to_key"].isin(hv132))
        & ~branches_all["branch_id"].isin(region.branch_ids)
    ].assign(role="boundary_132kv")

    nodes33 = {k for k in region.node_keys if k not in hv132}
    rows = []
    for rec in t2.to_dict(orient="records"):
        hv = ua.node_key(rec.get("licencearea"), rec.get("hv_node"))
        if hv not in nodes33:
            continue
        rows.append(
            {
                "branch_id": f"T2a:{rec.get('id')}",
                "kind": "transformer",
                "area": ua.licence_area_code(rec.get("licencearea")),
                "gsp": rec.get("gridsupplypoint"),
                "from_key": hv,
                "to_key": ua.node_key(rec.get("licencearea"), rec.get("lv_node")),
                "from_kv": ua.parse_voltage_kv(rec.get("voltage_hv")),
                "to_kv": ua.parse_voltage_kv(rec.get("voltage_lv")),
                "line_name": None,
                "from_sub": rec.get("hv_substation"),
                "to_sub": rec.get("lv_substation"),
                "params_complete": bool(
                    pd.notna(rec.get("positive_sequence_impedance_r_percent"))
                    and pd.notna(rec.get("positive_sequence_impedance_x_percent"))
                    and pd.notna(rec.get("transformer_rating_mva_summer"))
                ),
                "role": "primary_transformer",
            }
        )
    primaries = pd.DataFrame(rows)
    return pd.concat([e0, boundary, primaries], ignore_index=True)


def linked_circuit_series(
    monthly: pd.DataFrame,
    node_keys: Iterable[str],
    coverages: dict[str, pd.DataFrame],
    ltds_line_names: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Monthly-index circuits linked to the model, with half-hourly availability.

    Linked if BOTH monthly node keys are model nodes (`node_match`) OR the line name equals an
    LTDS line name of a model branch (`name_match`). Name-only links are flagged: they mean the
    operational index and LTDS disagree on the circuit's nodes.
    """
    keys = set(node_keys)
    names = set(ltds_line_names)
    m = monthly.assign(
        f=[
            ua.node_key(a, n)
            for a, n in zip(monthly.licence_area, monthly.from_ltds_node, strict=True)
        ],
        t=[
            ua.node_key(a, n)
            for a, n in zip(monthly.licence_area, monthly.to_ltds_node, strict=True)
        ],
        red=monthly["redacted"].map(ua.parse_flag),
    )
    node_ok = m["f"].isin(keys) & m["t"].isin(keys)
    m = m[(node_ok | m["ltds_line_name"].isin(names)) & m["ltds_line_name"].notna()].assign(
        node_ok=node_ok
    )
    out = []
    for line, grp in m.groupby("ltds_line_name"):
        hh = None
        for name, table in coverages.items():
            hit = table[table["ltds_line_name"] == line]
            if len(hit):
                h = hit.iloc[0]
                n = float(h["n_rows"])
                hh = {
                    "dataset": name,
                    "rows": int(n),
                    "active_power_completeness": round(float(h["n_active_power"]) / n, 4),
                    "current_completeness": round(float(h["n_current"]) / n, 4),
                    "first": str(h["first_timestamp"]),
                    "last": str(h["last_timestamp"]),
                }
        quantity = "none"
        if hh and hh["active_power_completeness"] >= 0.5:
            quantity = "active_power_mw"
        elif hh and hh["current_completeness"] >= 0.5:
            quantity = "current_amps"
        out.append(
            {
                "ltds_line_name": line,
                "from_node": grp["f"].iloc[0],
                "to_node": grp["t"].iloc[0],
                "n_node_pairs": int(grp[["f", "t"]].drop_duplicates().shape[0]),
                "node_match": bool(grp["node_ok"].all()),
                "name_match": line in names,
                "monthly_months": int(len(grp)),
                "monthly_redacted_months": int((grp["red"] == True).sum()),  # noqa: E712
                "half_hourly": hh,
                "quantity": quantity,
                "sign_convention_source": "monthly index orientation from_node -> to_node",
            }
        )
    return out


def linked_transformer_series(
    tx_monthly: pd.DataFrame, node_keys: Iterable[str]
) -> list[dict[str, Any]]:
    keys = set(node_keys)
    m = tx_monthly.assign(
        hv=[
            ua.node_key(a, n)
            for a, n in zip(tx_monthly.licence_area, tx_monthly.hv_ltds_node, strict=True)
        ],
        lv=[
            ua.node_key(a, n)
            for a, n in zip(tx_monthly.licence_area, tx_monthly.lv_ltds_node, strict=True)
        ],
        red=tx_monthly["redacted"].map(ua.parse_flag),
    )
    # Linked by HV node (unique per transformer in LTDS T2a). The LV node is checked separately:
    # e.g. LTDS writes Sundon Primary LV nodes as SURP5A/SURP5B, the index as SUPR5A/SUPR5B.
    m = m[m["hv"].isin(keys)]
    out = []
    for tx_id, grp in m.groupby("tx_id"):
        out.append(
            {
                "tx_id": tx_id,
                "ltds_name": grp["ltds_name"].iloc[0],
                "description": grp["tx_description"].iloc[0],
                "hv_node": grp["hv"].iloc[0],
                "lv_node": grp["lv"].iloc[0],
                "lv_node_in_model": bool(grp["lv"].iloc[0] in keys),
                "monthly_months": int(len(grp)),
                "monthly_redacted_months": int((grp["red"] == True).sum()),  # noqa: E712
                "monthly_has_active_power": bool(grp["active_power_month_mean_mw"].notna().any()),
                "monthly_has_current": bool(grp["current_month_mean_amps"].notna().any()),
            }
        )
    return out


def attached_assets(attr: pd.DataFrame, node_keys: Iterable[str]) -> list[dict[str, Any]]:
    """ECR assets (any technology) whose identifier-attributed nodes are all model nodes."""
    keys = frozenset(node_keys)
    inside = attr[attr["nodes"].map(lambda ns: bool(ns) and ns <= keys)]
    out = []
    for rec in inside.itertuples():
        poc = ua.parse_voltage_kv(rec.point_of_connection_poc_voltage_kv)
        out.append(
            {
                "ecr_register": rec.register,
                "ecr_row": int(rec.Index),
                "technology": rec.energy_source_1,
                "is_solar": bool(rec.is_solar),
                "status": rec.connection_status,
                "capacity_mw_connected": _none(rec.capacity_mw),
                "registered_capacity_mw": _none(
                    pd.to_numeric(
                        rec.energy_source_energy_conversion_technology_1_registered_capacity_mw,
                        errors="coerce",
                    )
                ),
                "connection_voltage_kv": poc,
                "date_connected": None if pd.isna(rec.date_connected) else str(rec.date_connected),
                "site_floc": rec.floc,
                "attribution_route": rec.route,
                "attributed_nodes": sorted(rec.nodes),
                "lat": _none(rec.latitude),
                "lon": _none(rec.longitude),
                "data_source": "UKPN Embedded Capacity Register (" + rec.register + ")",
            }
        )
    return out

"""Observed UKPN series → model inputs and validation targets (E1/E2).

Conventions (verified on data, see reports/e2_operational_validation.md):
  circuits      P > 0 from the monthly index's from_ltds_node to its to_ltds_node
  transformers  declared per series in the operating-state config and checked against an
                independently metered circuit on the same path (`check_transformer_signs`)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import pandapower as pp
import pandas as pd


@dataclass
class Series:
    circuit_p: pd.DataFrame  # timestamp × ltds_line_name, MW (monthly-index orientation)
    circuit_i: pd.DataFrame  # timestamp × ltds_line_name, A
    tx_p: pd.DataFrame  # timestamp × tx_id, MW (raw sign as published)
    tx_i: pd.DataFrame  # timestamp × tx_id, A


def load_series(measurements_dir: Path) -> Series:
    d = Path(measurements_dir)
    circuits = pd.concat(
        [
            pd.read_parquet(d / "circuits_active_power.parquet"),
            pd.read_parquet(d / "circuits_current_only.parquet"),
        ],
        ignore_index=True,
    )
    tx = pd.read_parquet(d / "transformers.parquet")

    def pivot(df: pd.DataFrame, key: str, value: str) -> pd.DataFrame:
        return df.pivot_table(index="timestamp", columns=key, values=value, aggfunc="mean")

    return Series(
        circuit_p=pivot(circuits, "ltds_line_name", "active_power_mw"),
        circuit_i=pivot(circuits, "ltds_line_name", "current_amps"),
        tx_p=pivot(tx, "tx_id", "active_power_mw"),
        tx_i=pivot(tx, "tx_id", "current_amps"),
    )


# ------------------------------------------------------------------------ sign conventions


def check_transformer_signs(cfg: dict[str, Any], s: Series, min_abs_r: float = 0.5) -> pd.DataFrame:
    """Correlate each P-metered transformer with its evidence circuit; flag disagreement.

    Expected correlation sign: a circuit whose positive direction flows INTO the transformer
    correlates negatively with a transformer reporting LV→HV as positive, and so on.
    """
    rows = []
    for tx_id, spec in cfg["transformer_series"].items():
        ev = spec["evidence"]
        if "same_as" in ev:
            ref = cfg["transformer_series"][ev["same_as"]]
            r_pair = s.tx_p[[tx_id, ev["same_as"]]].dropna().corr().iloc[0, 1]
            rows.append(
                {
                    "tx_id": tx_id,
                    "declared": spec["positive"],
                    "evidence": f"same_as {ev['same_as']}",
                    "r": float(r_pair),
                    "expected_sign": 1,
                    "n": int(s.tx_p[[tx_id, ev["same_as"]]].dropna().shape[0]),
                    "ok": spec["positive"] == ref["positive"] and r_pair > 0.9,
                    "class": "ASSUMED",
                }
            )
            continue
        into = ev["circuit_positive_into_transformer"]
        expected = (-1 if into else 1) * (1 if spec["positive"] == "lv_to_hv" else -1)
        pair = pd.concat([s.tx_p[tx_id], s.circuit_p[ev["circuit"]]], axis=1).dropna()
        r = (
            float(np.corrcoef(pair.iloc[:, 0], pair.iloc[:, 1])[0, 1])
            if len(pair) > 50
            else math.nan
        )
        rows.append(
            {
                "tx_id": tx_id,
                "declared": spec["positive"],
                "evidence": ev["circuit"],
                "r": r,
                "expected_sign": expected,
                "n": len(pair),
                "ok": bool(np.sign(r) == expected and abs(r) >= min_abs_r),
                "class": "DERIVED",
            }
        )
    return pd.DataFrame(rows)


def transformer_demand(s: Series, tx_id: str, positive: str) -> pd.Series:
    """Transformer P as demand (HV→LV positive), whatever the published convention."""
    p = s.tx_p[tx_id]
    return -p if positive == "lv_to_hv" else p


# ------------------------------------------------------------------- meter → model mapping


@dataclass(frozen=True)
class MeterMap:
    line: str
    element: str  # "line"
    index: int
    end: str  # "from" | "to": pandapower end where the monthly from-node sits
    mapping: str  # exact | name_node_mismatch | node_path
    note: str = ""


def map_meters(
    region: dict[str, Any], net: pp.pandapowerNet, lines: list[str]
) -> dict[str, MeterMap]:
    meas = {c["ltds_line_name"]: c for c in region["measurements"]["circuits"]}
    bus_name = net.bus["name"]
    g = nx.Graph()
    for idx, r in net.line.iterrows():
        g.add_edge(bus_name.at[r.from_bus], bus_name.at[r.to_bus], line=idx)
    out = {}
    for line in lines:
        m = meas[line]
        f, t = m["from_node"], m["to_node"]
        cand = net.line[net.line["name"] == line]
        if len(cand) == 1:
            idx = int(cand.index[0])
            fb, tb = bus_name.at[cand.at[idx, "from_bus"]], bus_name.at[cand.at[idx, "to_bus"]]
            if {fb, tb} == {f, t}:
                out[line] = MeterMap(line, "line", idx, "from" if fb == f else "to", "exact")
            else:
                end = "from" if fb == f else ("to" if tb == f else "from")
                out[line] = MeterMap(
                    line,
                    "line",
                    idx,
                    end,
                    "name_node_mismatch",
                    f"index nodes {f}->{t}, LTDS nodes {fb}->{tb}",
                )
            continue
        if f in g and t in g and nx.has_path(g, f, t):
            path = nx.shortest_path(g, f, t)
            idx = g.edges[path[0], path[1]]["line"]
            fb = bus_name.at[net.line.at[idx, "from_bus"]]
            out[line] = MeterMap(
                line,
                "line",
                int(idx),
                "from" if fb == f else "to",
                "node_path",
                "metered composite circuit = LTDS sections "
                + " -> ".join(path)
                + f"; meter assumed at {f}",
            )
    return out


def model_flow(net: pp.pandapowerNet, mm: MeterMap) -> tuple[float, float]:
    """(P in MW, |I| in A) at the metered end, P positive away from the monthly from-node."""
    res = net.res_line.loc[mm.index]
    if mm.end == "from":
        return float(res.p_from_mw), float(res.i_from_ka * 1000)
    return float(res.p_to_mw), float(res.i_to_ka * 1000)


# ------------------------------------------------------------------------- operating state


def season(ts: pd.Timestamp) -> str:
    return "Winter" if ts.month in (11, 12, 1, 2, 3) else "Summer"  # A08_season_mapping


def power_factor(demand_3a: pd.DataFrame, floc: str, season_name: str) -> float:
    row = demand_3a[(demand_3a.functional_location == floc) & (demand_3a.season == season_name)]
    if row.empty or pd.isna(row.maximum_demand_24_25_pf.iloc[0]):
        raise KeyError(f"no LTDS 3a power factor for {floc} {season_name}")
    return float(row.maximum_demand_24_25_pf.iloc[0])


def nodal_demand(
    cfg: dict[str, Any], s: Series, demand_3a: pd.DataFrame
) -> dict[str, pd.DataFrame]:
    """node → DataFrame[p_mw, q_mvar, class] indexed by timestamp (NaN where inputs missing)."""
    signs = {k: v["positive"] for k, v in cfg["transformer_series"].items()}
    index = s.circuit_p.index.union(s.tx_p.index).union(s.tx_i.index)
    out = {}
    for spec in cfg["loads"]:
        method = spec["method"]
        if method == "transformer_active_power":
            p = sum(transformer_demand(s, t, signs[t]).reindex(index) for t in spec["series"])
            cls = "OBSERVED"
        elif method == "transformer_current":
            amps = sum(s.tx_i[t].reindex(index) for t in spec["series"])
            p = None  # computed with pf below (A10)
            cls = "DERIVED"
        elif method == "circuit_active_power":
            # optional `scale`: an explicit, documented measurement-interpretation variant
            p = sum(
                (1 if c["positive_into_node"] else -1)
                * c.get("scale", 1.0)
                * s.circuit_p[c["line"]].reindex(index)
                for c in spec["circuits"]
            )
            cls = "DERIVED (observed circuits)" if len(spec["circuits"]) > 1 else "OBSERVED"
        else:
            raise ValueError(method)
        pf_by_season = {
            name: power_factor(demand_3a, spec["pf_site_floc"], name)
            for name in ("Winter", "Summer")
        }
        seasons = pd.Series(
            np.where(index.month.isin([11, 12, 1, 2, 3]), "Winter", "Summer"), index=index
        )
        pf = seasons.map(pf_by_season).astype(float)
        tan = np.tan(np.arccos(pf))
        if method == "transformer_current":
            s_mva = math.sqrt(3) * spec["current_kv"] * amps / 1000
            p = s_mva * pf
        out[spec["node"]] = pd.DataFrame({"p_mw": p, "q_mvar": p * tan, "class": cls})
    return out


def observed_import(cfg: dict[str, Any], s: Series) -> pd.Series:
    """Sundon 132→33 kV import (MW, positive = into the 33 kV network) from the GT meters."""
    signs = {k: v["positive"] for k, v in cfg["transformer_series"].items()}
    parts = [transformer_demand(s, t, signs[t]) for t in cfg["import_series"]]
    return pd.concat(parts, axis=1).sum(axis=1, min_count=len(parts))

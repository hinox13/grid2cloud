"""Per-scenario GENCO metrics against the AC reference (E4).

Inputs are gridfm-graphkit `predict` outputs (its own residual definitions, units after the
inverse transform) and the exported AC tables:

    bus predictions:    scenario, bus, PQ/PV/REF, Vm/Va/Pg/Qg _pred/_target,
                        "active res. (MW)", "reactive res. (MVar)", PBE   (|·|, per bus)
    branch predictions: scenario, from_bus, to_bus (directed edges), Pft/Qft and *_target

Metric definitions (per scenario):
    PBE_mean / PBE_max     mean / max over buses of graphkit's per-bus PBE (as graphkit's
                           "PBE Mean" = mean over graphs of the per-graph mean)
    P_residual / Q_residual mean |residual| over buses ("Avg. active/reactive res.")
    V_error                mean |Vm_pred − Vm_AC| over PQ buses (unknown Vm), pu
    angle_error            mean |Va_pred − Va_AC| over non-REF buses, degrees (wrapped)
    branch_P_error / _Q    mean |Pft_pred − Pft_AC| over directed edges, MW / MVAr
    max_loading_error      max over bus-pair groups of |loading_pred − loading_AC|, % of the
                           LTDS rating (parallel circuits grouped; GENCO's graph has no ratings)
    dc_P_residual          mean |P mismatch| of the DC power flow on the same state (baseline)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

V_LIMITS = (0.94, 1.06)  # ESQCR statutory ±6 % (33/11 kV) used for voltage-limit detection


def _wrap_deg(x: np.ndarray) -> np.ndarray:
    return (x + 180.0) % 360.0 - 180.0


def bus_metrics(bus: pd.DataFrame, v_limits: tuple[float, float] = V_LIMITS) -> pd.DataFrame:
    b = bus.copy()
    b["dv"] = (b["Vm_pred"] - b["Vm_target"]).abs()
    b["dva"] = np.abs(_wrap_deg(np.rad2deg(b["Va_pred"] - b["Va_target"])))
    g = b.groupby("scenario")
    out = pd.DataFrame(
        {
            "PBE_mean": g["PBE"].mean(),
            "PBE_max": g["PBE"].max(),
            "P_residual": g["active res. (MW)"].apply(lambda s: s.abs().mean()),
            "Q_residual": g["reactive res. (MVar)"].apply(lambda s: s.abs().mean()),
            "V_error": b[b["PQ"] == 1].groupby("scenario")["dv"].mean(),
            "angle_error": b[b["REF"] == 0].groupby("scenario")["dva"].mean(),
            "vm_ac_min": g["Vm_target"].min(),
            "vm_ac_max": g["Vm_target"].max(),
            "n_bus": g.size(),
        }
    )
    lo, hi = v_limits
    pq_pred = b["Vm_pred"].where(b["PQ"] == 1, b["Vm_target"])
    out["vlim_ac"] = g["Vm_target"].apply(lambda s: bool(((s < lo) | (s > hi)).any()))
    out["vlim_pred"] = pq_pred.groupby(b["scenario"]).apply(
        lambda s: bool(((s < lo) | (s > hi)).any())
    )
    return out


def branch_metrics(branch: pd.DataFrame, ratings: pd.DataFrame | None) -> pd.DataFrame:
    br = branch.copy()
    br["dp"] = (br["Pft"] - br["Pft_target"]).abs()
    br["dq"] = (br["Qft"] - br["Qft_target"]).abs()
    g = br.groupby("scenario")
    out = pd.DataFrame({"branch_P_error": g["dp"].mean(), "branch_Q_error": g["dq"].mean()})
    if ratings is None or ratings.empty:
        return out
    # directed flows summed over parallel edges, then S at the sending end
    d = (
        br.groupby(["scenario", "from_bus", "to_bus"])[["Pft", "Qft", "Pft_target", "Qft_target"]]
        .sum()
        .reset_index()
    )
    d["bus_a"] = d[["from_bus", "to_bus"]].min(axis=1)
    d["bus_b"] = d[["from_bus", "to_bus"]].max(axis=1)
    d = d.merge(
        ratings[["scenario", "bus_a", "bus_b", "rating_mva"]],
        on=["scenario", "bus_a", "bus_b"],
        how="left",
    )
    d["load_pred"] = 100 * np.hypot(d["Pft"], d["Qft"]) / d["rating_mva"]
    d["load_ac"] = 100 * np.hypot(d["Pft_target"], d["Qft_target"]) / d["rating_mva"]
    d["dload"] = (d["load_pred"] - d["load_ac"]).abs()
    gg = d.groupby("scenario")
    out["max_loading_error"] = gg["dload"].max()
    out["max_loading_ac"] = gg["load_ac"].max()
    out["max_loading_pred"] = gg["load_pred"].max()
    out["overload_ac"] = gg["load_ac"].max() > 100.0
    out["overload_pred"] = gg["load_pred"].max() > 100.0
    out["unrated_groups"] = gg["rating_mva"].apply(lambda s: int(s.isna().sum()))
    return out


def dc_baseline(raw_dir: Any, sn_mva: float = 100.0) -> pd.DataFrame:
    """Per-scenario DC-PF active residual (graphkit's pf_ac_dc_baseline computation)."""
    bus = pd.read_parquet(f"{raw_dir}/bus_data.parquet")
    branch = pd.read_parquet(f"{raw_dir}/branch_data.parquet")
    return dc_baseline_frames(bus, branch, sn_mva)


def dc_baseline_frames(
    bus: pd.DataFrame, branch: pd.DataFrame, sn_mva: float = 100.0
) -> pd.DataFrame:
    """`dc_baseline` on already-loaded (possibly scenario-filtered) bus / branch tables (E5)."""
    from gridfm_datakit.utils.power_balance import (
        compute_branch_powers_vectorized,
        compute_bus_balance,
    )

    bus = bus.reset_index(drop=True)
    branch = branch.reset_index(drop=True)
    pf_dc, _, pt_dc, _ = compute_branch_powers_vectorized(branch, bus, dc=True, sn_mva=sn_mva)
    bal_dc = compute_bus_balance(
        bus,
        branch,
        pd.DataFrame({"pf_dc": pf_dc, "pt_dc": pt_dc}, index=branch.index),
        dc=True,
        sn_mva=sn_mva,
    )
    bal_ac = compute_bus_balance(
        bus, branch, branch[["pf", "qf", "pt", "qt"]], dc=False, sn_mva=sn_mva
    )
    return pd.DataFrame(
        {
            "dc_P_residual": bal_dc.groupby("scenario")["P_mis_dc"].apply(
                lambda s: np.nanmean(np.abs(s))
            ),
            "ac_ref_P_residual": bal_ac.groupby("scenario")["P_mis_ac"].apply(
                lambda s: np.nanmean(np.abs(s))
            ),
        }
    )


def scenario_metrics(
    bus: pd.DataFrame, branch: pd.DataFrame, ratings: pd.DataFrame | None = None
) -> pd.DataFrame:
    return bus_metrics(bus).join(branch_metrics(branch, ratings), how="outer").reset_index()


def family_summary(m: pd.DataFrame, cols: list[str]) -> dict[str, float]:
    """Graphkit-compatible aggregates for one family (means over scenarios; PBE_max = max)."""
    out = {c: float(m[c].mean()) for c in cols if c in m and c != "PBE_max"}
    if "PBE_max" in m:
        out["PBE_max"] = float(m["PBE_max"].max())
    return out

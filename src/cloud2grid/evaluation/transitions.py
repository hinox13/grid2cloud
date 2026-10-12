"""Transition (state-change) metrics for E4-D: does GENCO track the network RESPONSE?

For consecutive 15-min states i → j on the same network, per element:
    Δ_AC = x_AC(j) − x_AC(i),   Δ_G = x_GENCO(j) − x_GENCO(i),   error = Δ_G − Δ_AC
for x in {Vm (PQ buses), Va (non-REF, degrees), branch Pft, branch Qft (directed edges)}.
Pairs whose element sets differ (e.g. an observed outage starts) are not compared.
This is distinct from steady-state per-scenario accuracy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _bus_matrix(bus: pd.DataFrame, col: str) -> pd.DataFrame:
    return bus.pivot(index="scenario", columns="bus", values=col)


def _edge_matrix(branch: pd.DataFrame, col: str) -> pd.DataFrame:
    br = branch.copy()
    br["k"] = br.groupby(["scenario", "from_bus", "to_bus"]).cumcount()
    return br.pivot_table(
        index="scenario", columns=["from_bus", "to_bus", "k"], values=col, aggfunc="first"
    )


def transition_metrics(
    bus: pd.DataFrame, branch: pd.DataFrame, pairs: pd.DataFrame
) -> pd.DataFrame:
    """`pairs`: columns scenario_i, scenario_j (+ any descriptors, carried through)."""
    i, j = pairs["scenario_i"].to_numpy(), pairs["scenario_j"].to_numpy()
    out = pairs.copy()
    pq = bus.groupby("bus")["PQ"].max().astype(bool)
    nonref = ~bus.groupby("bus")["REF"].max().astype(bool)
    for name, col_p, col_t, mask, scale in [
        ("Vm", "Vm_pred", "Vm_target", pq, 1.0),
        ("Va", "Va_pred", "Va_target", nonref, 180.0 / np.pi),
    ]:
        P = _bus_matrix(bus, col_p).loc[:, mask[mask].index]
        T = _bus_matrix(bus, col_t).loc[:, mask[mask].index]
        dG = (P.loc[j].to_numpy() - P.loc[i].to_numpy()) * scale
        dA = (T.loc[j].to_numpy() - T.loc[i].to_numpy()) * scale
        out[f"d{name}_ac_mean_abs"] = np.nanmean(np.abs(dA), axis=1)
        out[f"d{name}_err_mean_abs"] = np.nanmean(np.abs(dG - dA), axis=1)
    for name, col_p, col_t in [("P", "Pft", "Pft_target"), ("Q", "Qft", "Qft_target")]:
        P = _edge_matrix(branch, col_p)
        T = _edge_matrix(branch, col_t)
        a_i, a_j = T.loc[i].to_numpy(), T.loc[j].to_numpy()
        same = np.isfinite(a_i) == np.isfinite(a_j)
        valid = same.all(axis=1)
        dG = P.loc[j].to_numpy() - P.loc[i].to_numpy()
        dA = a_j - a_i
        out[f"d{name}_ac_mean_abs"] = np.where(valid, np.nanmean(np.abs(dA), axis=1), np.nan)
        out[f"d{name}_err_mean_abs"] = np.where(valid, np.nanmean(np.abs(dG - dA), axis=1), np.nan)
        if name == "P":
            num = np.nansum(np.abs(dG), axis=1)
            den = np.nansum(np.abs(dA), axis=1)
            out["dP_tracking_ratio"] = np.where(
                valid & (den > 0), num / np.where(den > 0, den, 1), np.nan
            )
            out["same_branch_set"] = valid
    return out


def consecutive_pairs(meta: pd.DataFrame, step_min: int = 15) -> pd.DataFrame:
    """Consecutive accepted states (Δt = step) → pairs, flagged within-half-hour (load held)."""
    m = meta.dropna(subset=["scenario"]).sort_values("slot")
    s = pd.to_datetime(m["slot"], utc=True).to_numpy()
    sc = m["scenario"].astype(int).to_numpy()
    dt = (s[1:] - s[:-1]).astype("timedelta64[m]").astype(int)
    keep = dt == step_min
    pairs = pd.DataFrame(
        {
            "scenario_i": sc[:-1][keep],
            "scenario_j": sc[1:][keep],
            "slot_i": m["slot"].to_numpy()[:-1][keep],
            "slot_j": m["slot"].to_numpy()[1:][keep],
        }
    )
    si = pd.to_datetime(pairs["slot_i"], utc=True)
    pairs["within_halfhour"] = si.dt.floor("30min") == pd.to_datetime(
        pairs["slot_j"], utc=True
    ).dt.floor("30min")
    hv = m.set_index("scenario")["p_hv_injected_mw"]
    pairs["dPV_injected_mw"] = (
        hv.loc[pairs["scenario_j"]].to_numpy() - hv.loc[pairs["scenario_i"]].to_numpy()
    )
    pairs["abs_dPV_injected_mw"] = pairs["dPV_injected_mw"].abs()
    return pairs


def ramp_bins(values: pd.Series, quantiles: list[float], labels: list[str]) -> pd.Series:
    edges = np.quantile(values.dropna(), quantiles)
    edges[0], edges[-1] = -np.inf, np.inf
    return pd.cut(
        values,
        bins=np.unique(edges),
        labels=labels[: len(np.unique(edges)) - 1],
        include_lowest=True,
    )

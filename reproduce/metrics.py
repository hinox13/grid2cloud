# ruff: noqa: E501  (metric definitions kept on one line each)
"""Metric definitions for the Cloud2Grid model verification (self-contained; pandas / numpy only).

These re-implement, independently of the research code, the definitions behind the published
tables `reports/tables/e5d_response_probes.csv` (responses) and `reports/tables/e5d_seed_results.csv`
(static state accuracy). `verify_models.py` first checks that, applied to the FROZEN predictions,
they reproduce the published tables; only then are they applied to fresh inference.

Inputs are GraphKit `predict` outputs (per scenario × bus; per scenario × directed branch).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TYPES = ("pv", "battery", "load")
SIGN_MW = 5.0  # ST3: import sign accuracy on states with |AC import| >= 5 MW


def ref_import(bus: pd.DataFrame) -> pd.DataFrame:
    """Per scenario: AC and GENCO grid import = Pg at the REF (slack) bus, MW."""
    r = bus[bus["REF"] == 1].set_index("scenario")
    return pd.DataFrame({"ac": r["Pg_target"], "pred": r["Pg_pred"]})


def complete_pairs(manifest: pd.DataFrame) -> pd.DataFrame:
    """One row per complete pair: probe_type, magnitude_class, x_mw, scenario_a (base), scenario_b."""
    m = manifest[manifest["complete"]]
    a = m[m["member"] == "A"].set_index("probe_id")
    b = m[m["member"] == "B"].set_index("probe_id").reindex(a.index)
    return pd.DataFrame({"probe_type": a["probe_type"], "magnitude_class": a["magnitude_class"], "x_mw": a["x_mw"],
                         "scenario_a": a["scenario"].astype(int), "scenario_b": b["scenario"].astype(int)}).reset_index()  # fmt: skip


def pair_deltas(bus: pd.DataFrame, branch: pd.DataFrame, pairs: pd.DataFrame) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Per family: (ΔGENCO, ΔAC), shape [n_pairs, n_elements]; Δ = state B − state A.
    import (MW); branch_P / branch_Q (MW / MVAr, every directed edge); Vm (pu, PQ buses);
    Va (degrees, non-REF buses)."""
    i, j = pairs["scenario_a"].to_numpy(), pairs["scenario_b"].to_numpy()
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    imp = ref_import(bus)
    out["import"] = tuple((imp.loc[j, c].to_numpy() - imp.loc[i, c].to_numpy())[:, None] for c in ("pred", "ac"))
    pq = bus.groupby("bus")["PQ"].max().astype(bool)
    nonref = ~bus.groupby("bus")["REF"].max().astype(bool)
    for name, cp, ct, mask, scale in (("Vm", "Vm_pred", "Vm_target", pq, 1.0), ("Va", "Va_pred", "Va_target", nonref, 180.0 / np.pi)):
        cols = mask[mask].index
        P = bus.pivot(index="scenario", columns="bus", values=cp).loc[:, cols]
        T = bus.pivot(index="scenario", columns="bus", values=ct).loc[:, cols]
        out[name] = ((P.loc[j].to_numpy() - P.loc[i].to_numpy()) * scale, (T.loc[j].to_numpy() - T.loc[i].to_numpy()) * scale)
    b2 = branch.copy()
    b2["k"] = b2.groupby(["scenario", "from_bus", "to_bus"]).cumcount()  # parallel circuits kept apart
    for name, cp, ct in (("branch_P", "Pft", "Pft_target"), ("branch_Q", "Qft", "Qft_target")):
        P = b2.pivot_table(index="scenario", columns=["from_bus", "to_bus", "k"], values=cp)
        T = b2.pivot_table(index="scenario", columns=["from_bus", "to_bus", "k"], values=ct)
        out[name] = (P.loc[j].to_numpy() - P.loc[i].to_numpy(), T.loc[j].to_numpy() - T.loc[i].to_numpy())
    return out


def response_table(bus: pd.DataFrame, branch: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    """Rows (probe_type, magnitude_class|'all', family):
    rel_err = Σ|ΔGENCO − ΔAC| / Σ|ΔAC|  (0 = exact response, 1 = no response);
    import slope = Σ(Δ·x) / Σ(x²) through the origin vs the perturbation size x (MW), slope_ratio = GENCO / AC."""
    el = pair_deltas(bus, branch, pairs)
    rows = []
    groups = [("all", np.ones(len(pairs), bool))] + [(c, (pairs["magnitude_class"] == c).to_numpy()) for c in pairs["magnitude_class"].unique()]
    for k in TYPES:
        tk = (pairs["probe_type"] == k).to_numpy()
        for cls, cm in groups:
            sel = tk & cm
            if not sel.any():
                continue
            x = pairs["x_mw"].to_numpy()[sel]
            for fam, (dg, da) in el.items():
                g, a = dg[sel], da[sel]
                ok = np.isfinite(g) & np.isfinite(a)
                gf, af = g[ok], a[ok]
                row = {"probe_type": k, "magnitude_class": cls, "family": fam, "n_pairs": int(sel.sum()),
                       "rel_err": float(np.abs(gf - af).sum() / np.abs(af).sum()),
                       "corr": float(np.corrcoef(gf, af)[0, 1]) if gf.std() > 0 else np.nan}  # fmt: skip
                if fam == "import":
                    s_ac = float((a[:, 0] * x).sum() / (x * x).sum())
                    s_g = float((g[:, 0] * x).sum() / (x * x).sum())
                    row.update(slope_ac=s_ac, slope_genco=s_g, slope_ratio=s_g / s_ac)
                rows.append(row)
    return pd.DataFrame(rows)


def static_metrics(bus: pd.DataFrame, branch: pd.DataFrame) -> dict[str, float]:
    """Means over scenarios of per-scenario metrics (GraphKit's per-bus residuals; AC targets)."""
    g = bus.groupby("scenario")
    pq = bus[bus["PQ"] == 1].assign(dv=lambda d: (d["Vm_pred"] - d["Vm_target"]).abs())
    imp = ref_import(bus)
    err = imp["pred"] - imp["ac"]
    big = imp["ac"].abs() >= SIGN_MW
    return {
        "n_states": int(bus["scenario"].nunique()),
        "PBE_mean": float(g["PBE"].mean().mean()),
        "P_residual": float(g["active res. (MW)"].apply(lambda s: s.abs().mean()).mean()),
        "V_error": float(pq.groupby("scenario")["dv"].mean().mean()),
        "branch_P_error": float((branch["Pft"] - branch["Pft_target"]).abs().groupby(branch["scenario"]).mean().mean()),
        "import_mae_mw": float(err.abs().mean()),
        "import_bias_mw": float(err.mean()),
        "import_corr": float(np.corrcoef(imp["ac"], imp["pred"])[0, 1]),
        "import_sign_accuracy_big": float((np.sign(imp.loc[big, "ac"]) == np.sign(imp.loc[big, "pred"])).mean()),
    }

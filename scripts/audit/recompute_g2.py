# ruff: noqa: E501
# Audit (22 Oct 2026): run from the repository root, e.g. .venv/bin/python scripts/audit/recompute_g2.py /tmp/out.json
# Needs the local per-state predictions in data/interim (not redistributed).
"""Independent recomputation of G2A-S (Aylesbury, synthetic) headline metrics from per-state parquets."""

import glob
import json
import sys

import numpy as np
import pandas as pd

W = "data/interim/g2a"


def imp(d: str) -> tuple[pd.Series, pd.Series, pd.Series]:
    f = [p for p in glob.glob(f"{d}/*_predictions.parquet") if "branch" not in p][0]
    b = pd.read_parquet(f, columns=["scenario", "REF", "Pg_target", "Pg_pred", "PBE"])
    r = b[b.REF == 1].set_index("scenario")
    return r.Pg_target, r.Pg_pred, b.groupby("scenario").PBE.mean()


def pairs(enc: str) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    m = pd.read_parquet(f"{W}/pairs/test_{enc}/pairs.parquet")
    m = m[m.complete]
    a = m[m.member == "A"].set_index("probe_id")
    bb = m[m.member == "B"].set_index("probe_id").reindex(a.index)
    return a.probe_type, a.x_mw.astype(float), a.scenario.astype(int), bb.scenario.astype(int)


out = {}
for run in ["zero_shot_ga"] + [f"g2a_{a}_s{s}" for a in "BCD" for s in range(3)]:
    enc = "neg" if "_B_" in run else "ga"
    ac, pr, pbe = imp(f"{W}/predictions/{run}/abs_test")
    e = pr - ac
    res = dict(
        n=len(ac),
        mae=e.abs().mean(),
        bias=e.mean(),
        r=np.corrcoef(ac, pr)[0, 1],
        pbe=pbe.mean(),
        export_states=int((ac < -5).sum()),
        export_recall=float((pr[ac < -5] < 0).mean()),
        ac_std=ac.std(),
    )
    pac, ppr, _ = imp(f"{W}/predictions/{run}/pairs_test")
    t, x, A, B = pairs(enc)
    for k in ("pv", "load"):
        mk = (t == k).to_numpy()
        xx = x[mk].to_numpy()
        dac = pac.reindex(B[mk]).to_numpy() - pac.reindex(A[mk]).to_numpy()
        dpr = ppr.reindex(B[mk]).to_numpy() - ppr.reindex(A[mk]).to_numpy()
        sa, sg = (dac * xx).sum() / (xx * xx).sum(), (dpr * xx).sum() / (xx * xx).sum()
        res[f"{k}_n"] = int(mk.sum())
        res[f"{k}_slope_ac"] = sa
        res[f"{k}_ratio"] = sg / sa
        res[f"{k}_relerr"] = np.abs(dpr - dac).mean() / np.abs(dac).mean()
        if k == "pv":
            res["pair_level_mae_A"] = np.abs(
                ppr.reindex(A[mk]).to_numpy() - pac.reindex(A[mk]).to_numpy()
            ).mean()
            res["pair_delta_err"] = np.abs(dpr - dac).mean()
    out[run] = {k: float(v) for k, v in res.items()}
T = pd.DataFrame(out).T
print(T.round(3).to_string())
with open(sys.argv[1], "w") as fh:
    json.dump(out, fh, indent=1)

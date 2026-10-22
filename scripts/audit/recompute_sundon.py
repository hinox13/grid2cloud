# ruff: noqa: E501
# Audit (22 Oct 2026): run from the repository root, e.g. .venv/bin/python scripts/audit/recompute_g2.py /tmp/out.json
# Needs the local per-state predictions in data/interim (not redistributed).
"""Independent recomputation of Sundon S1 real-state metrics from per-state prediction parquets.
Only the S1 state features (load/PV/battery injections) come from project code (raw-data reader)."""

import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "scripts")
import evaluate_e5b as ev5b

R = "data/interim"  # local predictions
runs = {
    "E5b e5b_ft_n10000_s2": f"{R}/e5b/predictions/e5b_ft_n10000_s2/S1_WEATHER_ALIGNED",
    "E5c e5c_ft_n10000_s2": f"{R}/e5c/predictions/e5c_ft_n10000_s2/S1_WEATHER_ALIGNED_GENAWARE",
    "E5d e5d_l1_s0": f"{R}/e5d/predictions/e5d_l1_s0/S1_WEATHER_ALIGNED_GENAWARE",
    "E5d e5d_l1_s1": f"{R}/e5d/predictions/e5d_l1_s1/S1_WEATHER_ALIGNED_GENAWARE",
    "E5d e5d_l1_s2": f"{R}/e5d/predictions/e5d_l1_s2/S1_WEATHER_ALIGNED_GENAWARE",
    "E5d e5d_l0.3_s0": f"{R}/e5d/predictions/e5d_l0.3_s0/S1_WEATHER_ALIGNED_GENAWARE",
    "E5d e5d_l0_s0": f"{R}/e5d/predictions/e5d_l0_s0/S1_WEATHER_ALIGNED_GENAWARE",
}
feats = ev5b.state_features(ev5b.E4W / "datasets/S1_WEATHER_ALIGNED")
load = feats[[f"Pd {n}" for n in ev5b.LOAD_NODES]].sum(axis=1)
out = {}
for lab, p in runs.items():
    b = pd.read_parquet(f"{p}/sundon_33kv_predictions.parquet")
    ref = b[b.REF == 1].set_index("scenario")
    ac, pr = ref.Pg_target, ref.Pg_pred
    pbe = b.groupby("scenario").PBE.mean()
    x = feats.reindex(ref.index)
    X = np.column_stack(
        [np.ones(len(x)), load.reindex(ref.index), x[f"Pd {ev5b.BATT}"], x.pv_injection_mw]
    )
    sa = np.linalg.lstsq(X, ac.to_numpy(), rcond=None)[0]
    sg = np.linalg.lstsq(X, pr.to_numpy(), rcond=None)[0]
    out[lab] = dict(
        n=int(len(ref)),
        import_bias=float((pr - ac).mean()),
        import_mae=float((pr - ac).abs().mean()),
        import_r=float(np.corrcoef(ac, pr)[0, 1]),
        pbe_mean=float(pbe.mean()),
        pbe_p95=float(pbe.quantile(0.95)),
        active_res=float(b.groupby("scenario")["active res. (MW)"].mean().mean()),
        ac_pv_slope=float(sa[3]),
        pv_slope=float(sg[3]),
        pv_ratio=float(sg[3] / sa[3]),
        ac_load_slope=float(sa[1]),
        load_slope=float(sg[1]),
        ac_batt_slope=float(sa[2]),
        batt_slope=float(sg[2]),
        mean_pv_inj=float(x.pv_injection_mw.mean()),
        max_pv_inj=float(x.pv_injection_mw.max()),
        ac_import_mean=float(ac.mean()),
        ids_hash=hash(tuple(sorted(ref.index.tolist()))),
    )
print(pd.DataFrame(out).T.to_string())
with open(sys.argv[1], "w") as fh:
    json.dump(out, fh, indent=1)

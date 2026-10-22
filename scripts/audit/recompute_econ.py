# ruff: noqa: E501
# Audit (22 Oct 2026): run from the repository root, e.g. .venv/bin/python scripts/audit/recompute_g2.py /tmp/out.json
# Needs only the released per-half-hour table reports/economic_impact/tables/periods.csv.
import json
import sys

import pandas as pd

P = pd.read_csv("reports/economic_impact/tables/periods.csv", parse_dates=["slot"])
P["date"] = P.slot.dt.date
o = {
    "n_periods": len(P),
    "n_days": P.date.nunique(),
    "first": str(P.slot.min()),
    "last": str(P.slot.max()),
    "missing_apx": int(P.apx_gbp_mwh.isna().sum()),
    "neg_apx_periods": int((P.apx_gbp_mwh < 0).sum()),
    "min_apx": float(P.apx_gbp_mwh.min()),
    "max_apx": float(P.apx_gbp_mwh.max()),
}
for m in ["AC", "E5c", "E5d", "accounting"]:
    for q in ["dpv", "dcl"]:
        e = P[f"{q}_{m}"] * 0.5
        o[f"{q}_{m}_mwh"] = float(e.sum())
        o[f"{q}_{m}_gbp"] = float((e * P.apx_gbp_mwh).sum(min_count=1))
o["dcl_AC_negative_periods"] = int((P.dcl_AC < 0).sum())
o["dcl_AC_negative_mwh"] = float((P.dcl_AC.clip(upper=0) * 0.5).sum())
o["dcl_AC_negative_gbp"] = float((P.dcl_AC.clip(upper=0) * 0.5 * P.apx_gbp_mwh).sum())
o["dcl_value_contrib_negative_periods"] = int(((P.dcl_AC * P.apx_gbp_mwh) < 0).sum())
# per half-hour errors vs AC
for m in ["E5d", "accounting", "E5c"]:
    o[f"dpv_mae_{m}"] = float((P[f"dpv_{m}"] - P.dpv_AC).abs().mean())
    o[f"dcl_mae_{m}"] = float((P[f"dcl_{m}"] - P.dcl_AC).abs().mean())
    o[f"dpv_winrate_vs_ac_{m}"] = None
o["share_halfhours_accounting_closer_dpv"] = float(
    ((P.dpv_accounting - P.dpv_AC).abs() < (P.dpv_E5d - P.dpv_AC).abs()).mean()
)
o["share_halfhours_accounting_closer_dcl"] = float(
    ((P.dcl_accounting - P.dcl_AC).abs() < (P.dcl_E5d - P.dcl_AC).abs()).mean()
)
o["E5d_dpv_signed_err_mean"] = float((P.dpv_E5d - P.dpv_AC).mean())
o["acc_dpv_signed_err_mean"] = float((P.dpv_accounting - P.dpv_AC).mean())
o["abs_import_AC_gbp"] = float((P.I_AC * 0.5 * P.apx_gbp_mwh).sum())
o["abs_import_E5d_gbp"] = float((P.I_E5d * 0.5 * P.apx_gbp_mwh).sum())
o["base_vs_frozen_max_dev"] = float((P.import_AC - P.s1_frozen_import_mw).abs().max())
# coverage
pd_ = P.groupby("date").size()
o["periods_per_day_min_med_max"] = [int(pd_.min()), float(pd_.median()), int(pd_.max())]
o["months"] = P.groupby(P.slot.dt.month).size().to_dict()
o["hours_utc_min_max"] = [str(P.slot.dt.time.min()), str(P.slot.dt.time.max())]
d = P[P.date.astype(str) == "2024-06-15"]
o["jun15_n"] = len(d)
o["jun15_cloud_mwh"] = float((d.dcl_AC * 0.5).sum())
o["jun15_cloud_gbp"] = float((d.dcl_AC * 0.5 * d.apx_gbp_mwh).sum())
h = d[d.slot.dt.strftime("%H:%M") == "11:00"].iloc[0]
o["jun15_1100"] = dict(
    pv=h.pv_mw,
    clear=h.pv_clear_mw,
    dcl_AC=h.dcl_AC,
    dcl_E5d=h.dcl_E5d,
    dcl_E5c=h.dcl_E5c,
    apx=h.apx_gbp_mwh,
    gbp=h.dcl_AC * 0.5 * h.apx_gbp_mwh,
    sp=h.settlement_period,
)
daily = P.assign(v=P.dcl_AC * 0.5 * P.apx_gbp_mwh).groupby("date").v.sum()
o["daily_cloud_gbp_median_p90_max"] = [
    float(daily.median()),
    float(daily.quantile(0.9)),
    float(daily.max()),
    str(daily.idxmax()),
]
print(json.dumps(o, indent=1, default=float))
with open(sys.argv[1], "w") as fh:
    json.dump(o, fh, indent=1, default=float)

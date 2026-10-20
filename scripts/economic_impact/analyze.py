# ruff: noqa: E501
"""Pre-registered economic analysis (configs/economic_impact/prereg.yaml): valuation, method errors, events.

    .venv/bin/python scripts/economic_impact/analyze.py
    → reports/economic_impact/{results.json, tables/*.csv}

Inputs: data/interim/economic_impact/{imports,mid,system_prices}.parquet.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
import clearsky  # noqa: E402

WORK = ROOT / "data/interim/economic_impact"
OUT = ROOT / "reports/economic_impact"
EVENTS = {"2024-06-15": "cloud clearing (Explorer)", "2024-04-15": "broken cumulus (Explorer)", "2024-08-23": "clear-sky control (Explorer)",
          "2024-07-07": "30-min PV ramp of +6.76 MW (10:15 → 10:45 UTC)"}  # fmt: skip
METHODS = ["AC", "accounting", "E5c", "E5d"]


def table() -> pd.DataFrame:
    imp = pd.read_parquet(WORK / "imports.parquet")
    imp = imp[imp.scenario.notna()]
    w = imp.pivot(index="scenario_id", columns="action", values=["import_AC", "import_E5c", "import_E5d"])
    meta = imp[imp.action == "base"].set_index("scenario_id")[["slot", "pv_mw", "pv_clear_mw", "import_AC", "s1_frozen_import_mw"]]
    T = meta.copy()
    for m in ("AC", "E5c", "E5d"):
        T[f"I_{m}"] = w[(f"import_{m}", "base")]
        T[f"dpv_{m}"] = w[(f"import_{m}", "noPV")] - w[(f"import_{m}", "base")]
        T[f"dcl_{m}"] = w[(f"import_{m}", "base")] - w[(f"import_{m}", "clear")]
    T["dpv_accounting"] = T.pv_mw
    T["dcl_accounting"] = T.pv_clear_mw - T.pv_mw
    T = T.dropna(subset=[f"dpv_{m}" for m in ("AC", "E5c", "E5d")])
    M = pd.read_parquet(WORK / "mid.parquet")
    apx = M[M.dataProvider == "APXMIDP"].set_index("startTime")
    sp = pd.read_parquet(WORK / "system_prices.parquet").set_index("startTime")
    T["apx_gbp_mwh"] = T.slot.map(apx.price)
    T["apx_volume_mwh"] = T.slot.map(apx.volume)
    T["settlement_date"] = T.slot.map(apx.settlementDate)
    T["settlement_period"] = T.slot.map(apx.settlementPeriod)
    T["system_price_gbp_mwh"] = T.slot.map(sp.systemSellPrice)
    # sensitivity: half-hour mean of the two 15-min explicit-PV estimates
    a = clearsky.assets_table()
    p955 = a[a.asset_id == "ECR:955"].set_index("slot").estimated_pv_mw
    T["pv_halfhour_mean_mw"] = (T.slot.map(p955) + (T.slot + pd.Timedelta(minutes=15)).map(p955)) / 2
    return T.reset_index()


def value(T: pd.DataFrame, col: str, price: str) -> float:
    return float((T[col] * 0.5 * T[price]).sum())


def main() -> int:
    T = table()
    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    T.to_csv(OUT / "tables" / "periods.csv", index=False)
    rec = {"periods_valued": int(len(T)), "periods_missing_apx": int(T.apx_gbp_mwh.isna().sum()),
           "periods_missing_system_price": int(T.system_price_gbp_mwh.isna().sum()),
           "base_vs_frozen_import_max_abs_mw": float((T.import_AC - T.s1_frozen_import_mw).abs().max())}  # fmt: skip
    season = {}
    for q, lab in (("dpv", "pv_attributed"), ("dcl", "cloud_attributed")):
        s = {}
        for m in METHODS:
            col = f"{q}_{m}"
            s[m] = {"energy_mwh": float((T[col] * 0.5).sum()), "value_apx_gbp": value(T, col, "apx_gbp_mwh"), "value_system_gbp": value(T, col, "system_price_gbp_mwh")}
        for m in METHODS[1:]:
            s[m]["value_apx_error_gbp"] = s[m]["value_apx_gbp"] - s["AC"]["value_apx_gbp"]
            s[m]["value_apx_error_pct"] = 100 * s[m]["value_apx_error_gbp"] / s["AC"]["value_apx_gbp"]
            s[m]["value_system_error_pct"] = 100 * (s[m]["value_system_gbp"] - s["AC"]["value_system_gbp"]) / s["AC"]["value_system_gbp"]
            d = T[f"{q}_{m}"] - T[f"{q}_AC"]
            s[m]["period_mae_mw"] = float(d.abs().mean())
            s[m]["period_value_mae_gbp"] = float((d * 0.5 * T.apx_gbp_mwh).abs().mean())
        season[lab] = s
    rec["season"] = season
    rec["season_import_energy_ac_mwh"] = float((T.I_AC * 0.5).sum())
    rec["absolute_mode_diagnostic"] = {m: {"import_value_apx_gbp": value(T, f"I_{m}", "apx_gbp_mwh")} for m in ("AC", "E5c", "E5d")}
    for m in ("E5c", "E5d"):
        rec["absolute_mode_diagnostic"][m]["error_vs_ac_gbp"] = rec["absolute_mode_diagnostic"][m]["import_value_apx_gbp"] - rec["absolute_mode_diagnostic"]["AC"]["import_value_apx_gbp"]
    ok = T.pv_halfhour_mean_mw.notna() & (T.pv_mw > 0.05)
    sens = T[ok].dpv_AC * T[ok].pv_halfhour_mean_mw / T[ok].pv_mw
    rec["sensitivity_halfhour_mean_pv"] = {"periods": int(ok.sum()), "pv_attributed_energy_mwh_slot": float((T[ok].dpv_AC * 0.5).sum()),
                                           "pv_attributed_energy_mwh_halfhour_mean": float((sens * 0.5).sum()),
                                           "value_apx_slot_gbp": float((T[ok].dpv_AC * 0.5 * T[ok].apx_gbp_mwh).sum()),
                                           "value_apx_halfhour_mean_gbp": float((sens * 0.5 * T[ok].apx_gbp_mwh).sum())}  # fmt: skip
    T["day"] = T.slot.dt.strftime("%Y-%m-%d")
    daily = T.groupby("day").apply(lambda g: pd.Series({"periods": len(g), "pv_value_apx_gbp": value(g, "dpv_AC", "apx_gbp_mwh"),
                                                        "cloud_value_apx_gbp": value(g, "dcl_AC", "apx_gbp_mwh"),
                                                        "cloud_energy_mwh": float((g.dcl_AC * 0.5).sum()), "apx_mean": float(g.apx_gbp_mwh.mean())}), include_groups=False)  # fmt: skip
    daily.to_csv(OUT / "tables" / "daily.csv")
    rec["daily_context"] = {"days": int(len(daily)), "cloud_value_apx_gbp_median": float(daily.cloud_value_apx_gbp.median()),
                            "cloud_value_apx_gbp_p90": float(daily.cloud_value_apx_gbp.quantile(0.9)), "cloud_value_apx_gbp_max": float(daily.cloud_value_apx_gbp.max()),
                            "max_day": str(daily.cloud_value_apx_gbp.idxmax())}  # fmt: skip
    ev = {}
    for day, lab in EVENTS.items():
        g = T[T.day == day]
        cols = ["slot", "settlement_date", "settlement_period", "pv_mw", "pv_clear_mw", "I_AC", "dpv_AC", "dcl_AC", "dpv_accounting", "dpv_E5c", "dpv_E5d", "apx_gbp_mwh", "system_price_gbp_mwh"]
        g[cols].to_csv(OUT / "tables" / f"event_{day}.csv", index=False)
        e = {"label": lab, "periods": int(len(g)), "first_last_utc": [str(g.slot.min()), str(g.slot.max())], "missing_prices": int(g.apx_gbp_mwh.isna().sum())}
        for m in METHODS:
            e[m] = {"pv_energy_mwh": float((g[f"dpv_{m}"] * 0.5).sum()), "pv_value_apx_gbp": value(g, f"dpv_{m}", "apx_gbp_mwh"),
                    "cloud_energy_mwh": float((g[f"dcl_{m}"] * 0.5).sum()), "cloud_value_apx_gbp": value(g, f"dcl_{m}", "apx_gbp_mwh"),
                    "cloud_value_system_gbp": value(g, f"dcl_{m}", "system_price_gbp_mwh")}  # fmt: skip
        e["day_rank_by_cloud_value"] = int((daily.cloud_value_apx_gbp > daily.at[day, "cloud_value_apx_gbp"]).sum() + 1) if day in daily.index else None
        e["apx_day_mean_percentile"] = float((daily.apx_mean < daily.at[day, "apx_mean"]).mean() * 100) if day in daily.index else None
        e["apx_range_gbp_mwh"] = [float(g.apx_gbp_mwh.min()), float(g.apx_gbp_mwh.max())]
        ev[day] = e
    rec["events"] = ev
    pv = season["pv_attributed"]
    rec["outcome"] = {
        "events_have_prices": all(e["missing_prices"] == 0 and e["periods"] > 0 for e in ev.values()),
        "e5d_err_le_half_e5c": abs(pv["E5d"]["value_apx_error_gbp"]) <= 0.5 * abs(pv["E5c"]["value_apx_error_gbp"]),
        "e5d_err_lt_accounting": abs(pv["E5d"]["value_apx_error_gbp"]) < abs(pv["accounting"]["value_apx_error_gbp"]),
        "season_pv_value_ge_1000": pv["AC"]["value_apx_gbp"] >= 1000,
        "consistent_resolve": rec["base_vs_frozen_import_max_abs_mw"] <= 0.05,
    }
    o = rec["outcome"]
    o["classification"] = ("A_strong" if (o["events_have_prices"] and o["e5d_err_le_half_e5c"] and o["e5d_err_lt_accounting"]) else
                           "C_weak" if (not o["events_have_prices"] or not o["season_pv_value_ge_1000"] or not o["consistent_resolve"]) else "B_moderate")  # fmt: skip
    (OUT / "results.json").write_text(json.dumps(rec, indent=2, default=float))
    print(json.dumps({k: rec[k] for k in ("periods_valued", "base_vs_frozen_import_max_abs_mw", "outcome")}, indent=1, default=float))
    for lab, s in season.items():
        print(lab, {m: {k: round(v, 2) for k, v in s[m].items()} for m in METHODS})
    print("absolute:", rec["absolute_mode_diagnostic"])
    print("sensitivity:", rec["sensitivity_halfhour_mean_pv"])
    print("daily:", rec["daily_context"])
    for d, e in ev.items():
        print(d, e["label"], e["periods"], "AC pv", round(e["AC"]["pv_energy_mwh"], 2), "MWh £", round(e["AC"]["pv_value_apx_gbp"], 0), "| cloud", round(e["AC"]["cloud_energy_mwh"], 2), "MWh £", round(e["AC"]["cloud_value_apx_gbp"], 0),
              "| E5c pv £", round(e["E5c"]["pv_value_apx_gbp"], 0), "E5d pv £", round(e["E5d"]["pv_value_apx_gbp"], 0), "acct £", round(e["accounting"]["pv_value_apx_gbp"], 0),
              "| rank", e["day_rank_by_cloud_value"], "price pct", round(e["apx_day_mean_percentile"] or -1, 0), "range", e["apx_range_gbp_mwh"])  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())

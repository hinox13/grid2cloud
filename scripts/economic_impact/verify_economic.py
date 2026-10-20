# ruff: noqa: E501
"""Independently re-derive every economic number the Cloud Impact view shows (exits non-zero on failure).

    .venv/bin/python scripts/economic_impact/verify_economic.py

1. Bundle checks (always; data/demo/cloud_impact is committed): the 15 June totals recomputed from the
   24 periods equal season.json; settlement periods match BST; no duplicate or missing period; the
   single 11:00 period is distinct from the day total.
2. Released-table checks (always): the 16 season totals re-derived from the published per-half-hour
   table reports/economic_impact/tables/periods.csv equal results.json and season.json; the APX gap is
   exactly the documented one. This re-does the arithmetic only: it does not re-solve AC or re-run GENCO.
3. Full re-derivation (local study outputs only, data/interim/economic_impact; not in a public clone): season
   energies and values for AC, accounting, E5c and E5d recomputed from imports and prices with a
   separate implementation, compared exactly with reports/economic_impact/results.json; price
   alignment, negative prices, counts; the base states reproduce the frozen S1 AC import.
4. Where a frozen fallback checksum list exists (development repository only), it still passes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "data/demo/cloud_impact"
WORK = ROOT / "data/interim/economic_impact"
RESULTS = ROOT / "reports/economic_impact/results.json"
TABLE = ROOT / "reports/economic_impact/tables/periods.csv"
H = 0.5  # hours per settlement period


def bst_settlement(slot: pd.Series) -> tuple[pd.Series, pd.Series]:
    """GB settlement date and period for UTC period starts in British Summer Time (UTC+1)."""
    local = slot.dt.tz_convert("Europe/London")
    day = local.dt.normalize()
    period = ((local - day) / pd.Timedelta(minutes=30)).astype(int) + 1
    return local.dt.strftime("%Y-%m-%d"), period


def bundle_checks() -> list[tuple[str, bool, str]]:
    P = pd.read_parquet(BUNDLE / "periods_2024-06-15.parquet")
    S = json.loads((BUNDLE / "season.json").read_text())
    ev = S["event_2024-06-15"]["AC"]
    out = []
    d_cloud = P.import_AC_observed_mw - P.import_AC_clear_sky_mw
    d_pv = P.import_AC_no_plant_mw - P.import_AC_observed_mw
    e_cloud, v_cloud = float((d_cloud * H).sum()), float((d_cloud * H * P.apx_gbp_per_mwh).sum())
    e_pv, v_pv = float((d_pv * H).sum()), float((d_pv * H * P.apx_gbp_per_mwh).sum())
    out.append(("15 Jun cloud energy (MWh) = season.json", np.isclose(e_cloud, ev["cloud_energy_mwh"], rtol=1e-6), f"{e_cloud:.4f} vs {ev['cloud_energy_mwh']:.4f}"))
    out.append(("15 Jun cloud value (GBP) = season.json", np.isclose(v_cloud, ev["cloud_value_apx_gbp"], rtol=1e-6), f"{v_cloud:.2f} vs {ev['cloud_value_apx_gbp']:.2f}"))
    out.append(("15 Jun plant-displaced energy (MWh) = season.json", np.isclose(e_pv, ev["pv_energy_mwh"], rtol=1e-6), f"{e_pv:.4f}"))
    out.append(("15 Jun plant-displaced value (GBP) = season.json", np.isclose(v_pv, ev["pv_value_apx_gbp"], rtol=1e-6), f"{v_pv:.2f}"))
    out.append(("24 unique half-hours, 05:00–16:30 UTC", P.slot_utc.is_unique and len(P) == 24 and P.slot_utc.min().strftime("%H:%M") == "05:00" and P.slot_utc.max().strftime("%H:%M") == "16:30", f"{len(P)}"))
    out.append(("consecutive 30-min spacing (no gap, no double count)", bool((P.slot_utc.diff().dropna() == pd.Timedelta(minutes=30)).all()), ""))
    sd, spn = bst_settlement(P.slot_utc)
    out.append(("settlement date/period match BST numbering", bool((sd == P.settlement_date).all() and (spn == P.settlement_period.astype(int)).all()), f"SP {int(P.settlement_period.min())}–{int(P.settlement_period.max())}"))
    out.append(("no missing price", bool(P.apx_gbp_per_mwh.notna().all() and P.system_price_gbp_per_mwh.notna().all()), ""))
    one = P[P.slot_utc.dt.strftime("%H:%M") == "11:00"].iloc[0]
    v_one = float((one.import_AC_observed_mw - one.import_AC_clear_sky_mw) * H * one.apx_gbp_per_mwh)
    out.append(("11:00 period value is distinct from the day total", v_one < 0.2 * v_cloud, f"11:00 £{v_one:.2f} vs day £{v_cloud:.2f}"))
    out.append(("fleet PV 11:00 → 11:30 = 2.38 → 8.86 MW", f"{P.set_index(P.slot_utc.dt.strftime('%H:%M')).fleet_pv_mw['11:00']:.2f}" == "2.38" and f"{P.set_index(P.slot_utc.dt.strftime('%H:%M')).fleet_pv_mw['11:30']:.2f}" == "8.86", ""))
    return out


def released_checks() -> list[tuple[str, bool, str]]:
    """Season totals re-derived from the released per-half-hour table (reports/economic_impact/tables/periods.csv).

    This re-does the energy and price arithmetic from published values; it does not re-solve the AC
    counterfactuals or re-run GENCO (that needs the local study outputs, see full_checks)."""
    R = json.loads(RESULTS.read_text())
    S = json.loads((BUNDLE / "season.json").read_text())
    T = pd.read_csv(TABLE, parse_dates=["slot"])
    out = [("released table: 2,820 unique half-hours", len(T) == R["periods_valued"] == 2820 and T.slot.is_unique, f"{len(T)}")]
    missing = sorted(T.slot[T.apx_gbp_mwh.isna()].dt.strftime("%Y-%m-%dT%H:%MZ"))
    out.append(("released table: APX missing only at the documented source gap (2024-04-13 07:00 UTC)", missing == ["2024-04-13T07:00Z"], f"missing {missing}"))
    sd, spn = bst_settlement(T.slot)
    has = T.settlement_period.notna()  # the gap row carries no Elexon period fields
    out.append(("released table: settlement periods match BST numbering", bool((spn[has] == T.settlement_period[has].astype(int)).all()) and int((~has).sum()) <= 1, f"{int(has.sum())} periods"))
    out.append(("released table: negative prices kept (not filtered)", int((T.apx_gbp_mwh < 0).sum()) > 0, f"{int((T.apx_gbp_mwh < 0).sum())} negative-price half-hours"))
    for q, pre in (("pv_attributed", "dpv"), ("cloud_attributed", "dcl")):
        for m in ("AC", "E5c", "E5d", "accounting"):
            d = T[f"{pre}_{m}"]
            e, v = float((d * H).sum()), float((d * H * T.apx_gbp_mwh).sum())
            ref = R["season"][q][m]
            out.append((f"released table: {q} {m} energy and APX value = results.json", np.isclose(e, ref["energy_mwh"], rtol=1e-6) and np.isclose(v, ref["value_apx_gbp"], rtol=1e-6), f"{e:,.2f} MWh, £{v:,.2f}"))
    ac = R["season"]["pv_attributed"]["AC"]["value_apx_gbp"]
    for m, shown in (("E5c", "−98.4 %"), ("E5d", "−0.3 %"), ("accounting", "−1.5 %")):
        pct = 100 * (R["season"]["pv_attributed"][m]["value_apx_gbp"] - ac) / ac
        out.append((f"{m} season value error displayed as {shown}", f"{pct:+.1f} %".replace("-", "−") == shown, f"{pct:+.3f} %"))
    same = all(S[q][m][k] == R["season"][q][m][k] for q in ("pv_attributed", "cloud_attributed") for m in ("AC", "E5c", "E5d", "accounting") for k in ("energy_mwh", "value_apx_gbp"))
    out.append(("bundle season.json totals = results.json", same, ""))
    return out


def full_checks() -> list[tuple[str, bool, str]]:
    R = json.loads(RESULTS.read_text())
    imp = pd.read_parquet(WORK / "imports.parquet")
    mid = pd.read_parquet(WORK / "mid.parquet")
    apx = mid[mid.dataProvider == "APXMIDP"].drop_duplicates("startTime").set_index("startTime").price
    out = []
    base = imp[imp.action == "base"].set_index("scenario_id")
    by = {a: imp[imp.action == a].set_index("scenario_id") for a in ("base", "noPV", "clear")}
    price = base.slot.map(apx)
    out.append(("2,820 valued half-hours", len(base) == R["periods_valued"] == 2820, f"{len(base)}"))
    missing = sorted(base.slot[price.isna()].dt.strftime("%Y-%m-%dT%H:%MZ"))
    # documented exception: Elexon publishes no APXMIDP row for 2024-04-13 SP17 (07:00 UTC); its energy is counted, its value is not
    out.append(("APX missing only at the documented source gap (2024-04-13 07:00 UTC, SP 17)", missing == ["2024-04-13T07:00Z"] and R["periods_missing_apx"] == 1, f"missing {missing}"))
    gap = base[base.slot.dt.strftime("%Y-%m-%dT%H:%MZ") == "2024-04-13T07:00Z"].iloc[0]
    bound = float(gap.pv_mw * H * 6.84)  # upper bound at the higher neighbouring APX price (£6.84/MWh, SP 18)
    out.append(("value omitted at the gap is negligible (< 0.01 % of the season)", bound < 1e-4 * R["season"]["pv_attributed"]["AC"]["value_apx_gbp"], f"≤ £{bound:.2f}"))
    out.append(("no duplicate half-hour", base.slot.is_unique, ""))
    out.append(("negative prices kept (not filtered)", int((price < 0).sum()) > 0, f"{int((price < 0).sum())} negative-price half-hours"))
    sd, spn = bst_settlement(base.slot)
    out.append(("all half-hours inside BST (no clock change in the sample)", bool((base.slot.dt.tz_convert("Europe/London").dt.strftime("%z") == "+0100").all()), ""))
    out.append(("base states reproduce the frozen S1 AC import (≤ 0.05 MW)", float((base.import_AC - base.s1_frozen_import_mw).abs().max()) <= 0.05, f"max {float((base.import_AC - base.s1_frozen_import_mw).abs().max()):.2e} MW"))
    for q, (a1, a0), acct in (("pv_attributed", ("noPV", "base"), base.pv_mw), ("cloud_attributed", ("base", "clear"), base.pv_clear_mw - base.pv_mw)):
        for m in ("AC", "E5c", "E5d", "accounting"):
            d = acct if m == "accounting" else by[a1][f"import_{m}"] - by[a0][f"import_{m}"]
            e, v = float((d * H).sum()), float((d * H * price).sum())
            ref = R["season"][q][m]
            out.append((f"{q} {m}: energy and APX value = results.json", np.isclose(e, ref["energy_mwh"], rtol=1e-9) and np.isclose(v, ref["value_apx_gbp"], rtol=1e-9), f"{e:,.2f} MWh, £{v:,.2f}"))
    return out


def main() -> int:
    checks = [("[bundle] " + n, ok, d) for n, ok, d in bundle_checks()]
    checks += [("[released tables] " + n, ok, d) for n, ok, d in released_checks()]
    if (WORK / "imports.parquet").exists():
        checks += [("[local study data] " + n, ok, d) for n, ok, d in full_checks()]
    else:
        print("note: local study outputs absent (public clone). Checked: the bundle and the season arithmetic from the\n"
              "released per-half-hour table. NOT re-checked here: the AC counterfactual solves, the GENCO predictions and\n"
              "the raw Elexon prices (they need data/interim/economic_impact/ and the local S1 states).")
    if (ROOT / "submission/FALLBACK_SHA256SUMS").exists():  # development repository only
        fz = subprocess.run(["sha256sum", "-c", "submission/FALLBACK_SHA256SUMS"], cwd=ROOT, capture_output=True, text=True)
        checks.append(("frozen fallback: 20/20 checksums", fz.returncode == 0 and fz.stdout.count(": OK") == 20, ""))
    bad = 0
    for name, ok, detail in checks:
        print(f"{'ok  ' if ok else 'FAIL'} {name} {detail}")
        bad += not ok
    print(f"{len(checks) - bad}/{len(checks)} checks pass")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

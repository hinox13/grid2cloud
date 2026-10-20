# ruff: noqa: E501
"""Figures for the economic-impact investigation (from reports/economic_impact/results.json and tables/).

    C2G_FONT_DIR=<fonts> .venv/bin/python scripts/economic_impact/figures.py → reports/economic_impact/figures/
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import matplotlib.dates as mdates
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/economic_impact"
spec = importlib.util.spec_from_file_location("mf", ROOT / "submission/make_figures.py")
mf = importlib.util.module_from_spec(spec)
sys.modules["mf"] = mf
spec.loader.exec_module(mf)
plt = mf.plt
COL = {"AC": mf.INK, "accounting": mf.MUTED, "E5c": mf.COL["E5c"], "E5d": mf.COL["E5d"]}
LAB = {"AC": "AC reference", "accounting": "injection accounting", "E5c": "E5c", "E5d": "E5d"}


def methods() -> None:
    R = json.loads((OUT / "results.json").read_text())
    fig, axs = plt.subplots(1, 2, figsize=(14, 5.6))
    for ax, key, title in ((axs[0], "pv_attributed", "A  Import displaced by the 6 MW plant"), (axs[1], "cloud_attributed", "B  Extra import caused by clouds")):
        s = R["season"][key]
        ms = ["AC", "accounting", "E5d", "E5c"]
        v = [s[m]["value_apx_gbp"] / 1000 for m in ms]
        ax.bar(range(4), v, color=[COL[m] for m in ms])
        for i, m in enumerate(ms):
            txt = f"£{v[i]:.1f}k" + ("" if m == "AC" else f"\n({s[m]['value_apx_error_pct']:+.1f} %)")
            ax.text(i, v[i] + max(v) * 0.02, mf.um(txt), ha="center", fontsize=11, color=mf.INK_2)
        ax.set_xticks(range(4), [LAB[m] for m in ms], fontsize=11)
        ax.set_ylabel("illustrative value at APX prices (£ thousand)")
        ax.set_ylim(0, max(v) * 1.25)
        ax.set_title(title, loc="left", fontsize=13.5, fontweight="semibold")
        ax.grid(axis="x", visible=False)
    fig.suptitle(f"Valuation over the {R['periods_valued']:,} AC-reconstructed half-hours of April–September 2024 (in brackets: error vs AC)", x=0.02, ha="left", fontsize=13)
    fig.text(0.02, 0.01, "Illustrative avoided-import valuation at observed APX Market Index prices, not a realised saving. Per half-hour, accounting is slightly more accurate than E5d (0.04 vs 0.05 MW); E5d's smaller season error partly reflects cancelling errors.\n"
             "One half-hour (13 Apr 07:00 UTC) has no APX price at source; its value is omitted. Contains BMRS data © Elexon Limited copyright and database right 2024.",
             fontsize=9.5, color=mf.MUTED)  # fmt: skip
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    fig.savefig(OUT / "figures/method_comparison.png", dpi=160)
    plt.close(fig)


def event() -> None:
    e = pd.read_csv(OUT / "tables/event_2024-06-15.csv", parse_dates=["slot"])
    t = e.slot + pd.Timedelta(minutes=15)
    fig, axs = plt.subplots(3, 1, figsize=(12, 9.4), sharex=True, gridspec_kw={"height_ratios": [1, 1, 0.9]})
    a = axs[0]
    a.plot(t, e.pv_clear_mw, color=mf.MUTED, ls="--", lw=1.6, label="clear-sky estimate (same chain)")
    a.plot(t, e.pv_mw, color=mf.PV if hasattr(mf, "PV") else "#c98500", lw=2.4, marker="o", ms=3.5, label="satellite-derived estimate")
    a.set_ylabel("6 MW plant (MW)")
    a.legend(frameon=False, fontsize=10)
    a.set_title("15 June 2024, Sundon: solar, grid import and observed prices per settlement period (UTC)", loc="left", fontsize=13)
    b = axs[1]
    b.plot(t, e.I_AC, color=mf.INK, lw=2.4, label="AC import, as reconstructed")
    b.plot(t, e.I_AC + e.dpv_AC, color=mf.ACCENT_TEXT, lw=1.6, ls=":", label="AC import without the plant (CF_noPV)")
    b.plot(t, e.I_AC - e.dcl_AC, color=mf.COL["E5c"], lw=1.6, ls="--", label="AC import with clear-sky output (CF_clear)")
    b.set_ylabel("grid import (MW)")
    b.legend(frameon=False, fontsize=10, ncol=3, loc="upper left")
    c = axs[2]
    c2 = c.twinx()
    val = e.dcl_AC * 0.5 * e.apx_gbp_mwh
    c.bar(t, val, width=0.018, color=np.where(val >= 0, mf.COL["E5d"], mf.MUTED), label="cloud-attributed import value (£ per half-hour)")
    c2.plot(t, e.apx_gbp_mwh, color=mf.INK_2, lw=1.6, label="APX Market Index price")
    c.set_ylabel("£ per half-hour")
    c2.set_ylabel("£/MWh")
    c.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    h1, l1 = c.get_legend_handles_labels()
    h2, l2 = c2.get_legend_handles_labels()
    c.legend(h1 + h2, l1 + l2, frameon=False, fontsize=10, loc="upper left")
    tot = val.sum()
    fig.text(0.02, 0.005, f"Day total: {(e.dcl_AC * 0.5).sum():.1f} MWh of extra import because clouds held the plant below clear sky, illustratively £{tot:,.0f} at APX prices (£{(e.dpv_AC * 0.5 * e.apx_gbp_mwh).sum():,.0f} of import displaced by the plant).\n"
             "Contains BMRS data © Elexon Limited copyright and database right 2024. Satellite-derived estimates and AC reconstructions, not measurements; illustrative valuation, not a realised saving.",
             fontsize=9.5, color=mf.MUTED)  # fmt: skip
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(OUT / "figures/event_2024-06-15.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    mf.setup_fonts()
    (OUT / "figures").mkdir(parents=True, exist_ok=True)
    methods()
    event()
    print("figures written")

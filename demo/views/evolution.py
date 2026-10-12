"""Model evolution: off-the-shelf → grid-tuned → envelope-tuned → generator-aware → response-aware
GENCO (E4–E5d), and what each stage taught us."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from c2g import data as D
from c2g import figures as F
from c2g import theme as T

T.setup("Model evolution")
evo = D.evolution()
models = D.models()
mods = [m["id"] for m in models]

st.markdown("## Model evolution")
st.markdown(
    '<div class="c2g-sub">Every number below is a frozen, published result on the same 2,829 real '
    "half-hourly 2024 states (S1). Checkpoints were selected on synthetic data only and frozen "
    "before any real state was evaluated.</div>",
    unsafe_allow_html=True,
)
st.markdown("### What did we learn?")
T.learned_ladder(evo, mods)
has_e5d = "E5d" in mods
st.markdown(
    '<div class="c2g-callout">This is not a ranking by version number, and there is no "best '
    'model": each stage fixed a different failure mode. The envelope-tuned model has the lowest '
    "real-state error; the generator-aware model the best import variance and battery response"
    + (
        "; the response-aware model is the only one with the physical PV and load sensitivity, "
        "but with a larger import bias"
        if has_e5d
        else "; none responds correctly to PV"
    )
    + ". None passes the full pre-registered real-transfer gate. "
    "<b>Synthetic-to-real transfer needs topology and operating-envelope coverage, and explicit "
    "learning of physically meaningful sensitivities.</b></div>",
    unsafe_allow_html=True,
)


def ci(col: str, m: str) -> str:
    c = evo.at[m, col + "_ci"] if col + "_ci" in evo.columns else None
    if isinstance(c, str) and c.startswith("["):
        lo, hi = (float(v) for v in c.strip("[]").split(","))
        return f" [{lo:.3g}, {hi:.3g}]"
    return ""


WORDS = {3: "three", 4: "four", 5: "five", 6: "six"}
st.markdown(f"### The {WORDS.get(len(mods), len(mods))} GENCO models")
T.model_cards(mods)

rows = []
for m in models:
    i = m["id"]
    rows.append(
        {
            "Model": f"{T.NAMES[i]} ({T.EXP[i]})",
            "Real-state PBE (MVA) ↓": f"{evo.at[i, 'PBE_mean']:.3g}{ci('PBE_mean', i)}",
            "Active residual (MW) ↓": f"{evo.at[i, 'P_residual']:.3g}{ci('P_residual', i)}",
            "Import r ↑": f"{evo.at[i, 'import_corr']:.2f}",
            "Import MAE (MW) ↓": f"{evo.at[i, 'import_mae_mw']:.1f}",
            "Vm tracking r (median) ↑": f"{evo.at[i, 'vm_tracking_median_r']:.2f}",
            "Vm MAE (pu) ↓": f"{evo.at[i, 'V_error']:.4f}",
            "PV slope (AC −1.02)": f"{evo.at[i, 'genco_slope_pv']:+.2f}",
            "Selection": ("flagged fallback" if m.get("selection_flagged") else "gated")
            if m.get("registry")
            else "off-the-shelf",
        }
    )
T.html_table(pd.DataFrame(rows))
st.markdown(
    '<div class="c2g-note">↓ lower is better · ↑ higher is better · PV slope: closer to the AC '
    "value −1.02 is better. Brackets: 95 % block-bootstrap confidence intervals (resampled by "
    "day). PBE = mean nodal power-balance error; Vm tracking r = median per-bus correlation of "
    "predicted and AC voltage over time.</div>",
    unsafe_allow_html=True,
)

ac_vm_r = 1.0
c1, c2, c3 = st.columns(3)
with c1:
    st.plotly_chart(
        F.metric_bars(
            evo, mods, "PBE_mean", "Power-balance error (MVA, log) ↓", log=True, fmt=".3g"
        ),
        width="stretch",
        config={"displayModeBar": False},
    )
with c2:
    st.plotly_chart(
        F.metric_bars(evo, mods, "import_mae_mw", "Grid import error (MW) ↓", log=True, fmt=".1f"),
        width="stretch",
        config={"displayModeBar": False},
    )
with c3:
    st.plotly_chart(
        F.metric_bars(
            evo, mods, "genco_slope_pv", "PV slope (MW per MW) — AC −1.02", ref=-1.02, fmt="+.2f"
        ),
        width="stretch",
        config={"displayModeBar": False},
    )
c4, c5, c6 = st.columns(3)
with c4:
    st.plotly_chart(
        F.metric_bars(evo, mods, "import_corr", "Import correlation with AC ↑", ref=1.0, fmt=".2f"),
        width="stretch",
        config={"displayModeBar": False},
    )
with c5:
    st.plotly_chart(
        F.metric_bars(
            evo,
            mods,
            "vm_tracking_median_r",
            "Voltage tracking r (median) ↑",
            ref=ac_vm_r,
            fmt=".2f",
        ),
        width="stretch",
        config={"displayModeBar": False},
    )
with c6:
    st.plotly_chart(
        F.metric_bars(
            evo,
            mods,
            "genco_slope_chap31",
            "Battery slope (MW per MW) — AC +1.00",
            ref=float(evo.iloc[0]["ac_slope_chap31"]),
            fmt="+.2f",
        ),
        width="stretch",
        config={"displayModeBar": False},
    )

st.markdown("### Verdicts (pre-registered)")
v = {
    "zero_shot": "**Off-the-shelf (E4) — fails.** GENCO as published cannot transfer to the Sundon "
    "topology: it predicts ~211 MW of export where AC gives ~49 MW of import.",
    "E5": "**Grid-tuned (E5) — verdict D.** Fine-tuning on standard synthetic Sundon states fits "
    "held-out synthetic states but does not transfer to real operation.",
    "E5b": "**Envelope-tuned (E5b) — E5B-C, partial.** Fine-tuning on a broad physics-informed "
    "synthetic envelope cuts real-state error by ~99 % (vs grid-tuned); import (R3) and voltage "
    "(R4) criteria still fail.",
    "E5c": "**Generator-aware (E5c) — E5C-B.** Explicit generator nodes improve load and battery "
    "tracking, but the PV response stays near zero (R3, R4, R5 fail). Selection flagged: no run "
    "passed the synthetic gate.",
    "E5d": "**Response-aware (E5d) — E5D-D, partial.** An extra loss on paired synthetic AC states "
    "(one input changed: PV, battery or a load) teaches the response; no real or weather data "
    "was used for training or selection. The synthetic PV response is learned (slope ratio 0.997 "
    "on held-out pairs) and transfers to real operation (PV slope −0.04 → −1.07, AC −1.02; load "
    "0.61 → 0.93). The full gate still fails: import bias +13 MW (R3), Vm MAE 0.0109 pu (R4), "
    "battery overshoot 1.17 (R6). Selection flagged: no run passed the static synthetic gate.",
}
for m in models:
    st.markdown(f"{T.swatch(m['id'])} {v[m['id']]}", unsafe_allow_html=True)
st.markdown(
    '<div class="c2g-note">Sources: reports/tables/e5d_real_transfer.csv and '
    "e5d_response_transfer.csv (every model on the same states; earlier models identical to the "
    "E5c tables; copied verbatim into the demo bundle, sha256 in catalog.json).</div>",
    unsafe_allow_html=True,
)
T.footer()

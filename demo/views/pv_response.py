"""The central finding: the PV blind spot (E4–E5c) and what closed it (E5d), with its limits."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from c2g import data as D
from c2g import figures as F
from c2g import theme as T

T.setup("PV response")
cat = D.catalog()
evo = D.evolution()
resp = D.pv_response()
coefs = cat["ols_coefficients_s1"]
mods = [m["id"] for m in D.models()]
OLD, NEW = "E5c", "E5d"
HAS = NEW in mods  # E5d is optional: without it the page shows the E5c blind spot only

st.markdown("## The PV blind spot — and what closed it")
key = (
    f"The {T.NAMES[NEW].lower()} model ({T.EXP[NEW]}) learns the correct PV sensitivity from "
    "paired synthetic AC states, and that sensitivity transfers to real operation. Every earlier "
    "GENCO model was nearly blind to PV."
    if HAS
    else "Broad synthetic adaptation reduces real-state error dramatically, but GENCO still fails "
    "to learn the correct response to relatively small PV perturbations."
)
st.markdown(f'<div class="c2g-callout"><b>Key result.</b> {key}</div>', unsafe_allow_html=True)

ac_pv = coefs["AC"]["pv"]
st.markdown("### One extra MW of PV — what happens to the grid import?")
cells = [
    ("AC reference · physics", f"{ac_pv:+.2f} MW", "import falls almost one-for-one", T.AC),
    (
        T.LABELS[OLD],
        f"{coefs[OLD]['pv']:+.2f} MW",
        f"{coefs[OLD]['pv'] / ac_pv:.0%} of the physical response: blind to PV",
        T.colour(OLD),
    ),
]
if HAS:
    cells.append(
        (
            T.LABELS[NEW],
            f"{coefs[NEW]['pv']:+.2f} MW",
            f"{coefs[NEW]['pv'] / ac_pv:.0%} of the physical response: learned and transferred",
            T.colour(NEW),
        )
    )
T.faceoff(*cells)
st.plotly_chart(
    F.partial_residuals(resp, [OLD, NEW] if HAS else [OLD], coefs, height=340),
    width="stretch",
    config={"displayModeBar": False},
)
st.markdown(
    '<div class="c2g-note">Each point is one real half-hourly 2024 state (2,829). Vertical axis: '
    "grid import with the load and battery effects removed. Lines: the published PV slopes "
    "(dotted yellow = AC, for comparison). Frozen values from the S1 regression; nothing is "
    "re-fitted here. Neither model saw a real state, a satellite value or a real slope in "
    "training or selection.</div>",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------- the limitation, immediately
def limitation() -> None:
    st.markdown("### …but the real grid is not yet calibrated")
    e = evo.loc[NEW]
    T.tiles(
        [
            (
                f"Import bias · {T.SHORT[NEW]}",
                f"{e['import_bias_mw']:+.1f} MW",
                f"predicted import sits too high in almost every state "
                f"({T.SHORT[OLD]} {evo.at[OLD, 'import_bias_mw']:+.1f} MW)",
            ),
            (
                f"Import error · {T.SHORT[NEW]}",
                f"{e['import_mae_mw']:.1f} MW",
                f"criterion ≤ 5 MW: fails, yet it follows the variation (r {e['import_corr']:.3f})",
            ),
            (
                f"Voltage error · {T.SHORT[NEW]}",
                f"{e['V_error']:.4f} pu",
                "criterion ≤ 0.010 pu: fails (closest so far)",
            ),
            (
                f"Battery response · {T.SHORT[NEW]}",
                f"{coefs[NEW]['chap31']:+.2f} MW",
                f"per MW of battery output, AC {coefs['AC']['chap31']:+.2f}: overshoots",
            ),
        ]
    )
    st.markdown(
        '<div class="c2g-callout"><b>Correct physical sensitivity does not imply fully calibrated '
        "real-grid transfer.</b> The response-aware model knows how much the import should move "
        "when PV, load or the battery change, but not yet where the import level sits. Its "
        "pre-registered verdict is <b>E5D-D — partial</b>: the PV and load criteria pass; import, "
        "voltage and battery criteria fail.</div>",
        unsafe_allow_html=True,
    )


if HAS:
    limitation()

# ---------------------------------------------------------------- hero clearing
st.markdown("### 15 June 2024 — the cloud clears")
ev = D.event("jun15_cloud_clearing")
c1, c2 = st.columns([3, 2], vertical_alignment="bottom")
with c1:
    model = st.segmented_control(
        "Compare AC with",
        mods,
        default=NEW if HAS else OLD,
        key="pv_model",
        format_func=lambda m: T.SHORT[m],
    ) or (NEW if HAS else OLD)
ids = ev.meta["grid_scenarios"]
x = resp.set_index("scenario").loc[ids]
slots = pd.to_datetime(ev.meta["grid_slots_utc"])
steps = [(slots[j - 1], slots[j], ids[j - 1], ids[j]) for j in range(1, len(ids))]
dpv = [x.at[b, "pv_injection_mw"] - x.at[a, "pv_injection_mw"] for _, _, a, b in steps]
best = int(pd.Series(dpv).abs().idxmax())
with c2:
    j = st.select_slider(
        "Half-hour step",
        options=list(range(len(steps))),
        value=best,
        format_func=lambda k: f"{steps[k][0]:%H:%M}→{steps[k][1]:%H:%M}",
    )
t0, t1, a, b = steps[j]

left, right = st.columns([1.5, 1], gap="large")
with left:
    T.panel_title("PV, AC import and modelled import", "DERIVED", "SIMULATED", "PREDICTED")
    st.plotly_chart(
        F.timeline(ev.fleet_pv, ev.summary, model, t1, t1),
        width="stretch",
        config={"displayModeBar": False},
    )
with right:
    T.panel_title(f"What moved the import, {t0:%H:%M}→{t1:%H:%M}")
    d = {k: x.at[b, k] - x.at[a, k] for k in ("load_mw", "chap31_mw", "pv_injection_mw")}
    rows = []
    for who in ("AC", model):
        c = coefs[who]
        total = x.at[b, f"import_{who}"] - x.at[a, f"import_{who}"]
        terms = {
            f"PV ({d['pv_injection_mw']:+.1f} MW)": c["pv"] * d["pv_injection_mw"],
            f"Load ({d['load_mw']:+.1f} MW)": c["load"] * d["load_mw"],
            f"Battery ({d['chap31_mw']:+.1f} MW)": c["chap31"] * d["chap31_mw"],
        }
        terms["Actual total change"] = total
        rows += [{"who": who, "driver": k, "mw": v} for k, v in terms.items()]
    st.plotly_chart(
        F.decomposition(pd.DataFrame(rows), model),
        width="stretch",
        config={"displayModeBar": False},
    )
    pv_ac = coefs["AC"]["pv"] * d["pv_injection_mw"]
    pv_m = coefs[model]["pv"] * d["pv_injection_mw"]
    st.markdown(
        f'<div class="c2g-note">PV added {d["pv_injection_mw"]:+.1f} MW. Physics (AC) attributes '
        f"{pv_ac:+.1f} MW of import change to it; {T.SHORT[model]} attributes {pv_m:+.1f} MW. "
        "Terms = published S1-wide coefficients × this step's input changes; they need not add "
        "up exactly to the actual change (the remainder is nonlinearity and model error). "
        "Grid states are the frozen half-hourly real states used for every published metric.</div>",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------- S1-wide evidence
st.markdown("### Across all 2,829 real states")
T.panel_title(
    "Import with load and battery effects removed, against HV PV injection",
    "SIMULATED",
    "PREDICTED",
)
st.plotly_chart(
    F.partial_residuals(resp, mods, coefs), width="stretch", config={"displayModeBar": False}
)
st.markdown(
    '<div class="c2g-note">Each point is one real half-hourly state. Solid line: the published PV '
    "slope of that panel; dotted yellow line: the AC slope for comparison. A model that "
    "understood PV tilts like the AC panel.</div>",
    unsafe_allow_html=True,
)

T.panel_title(
    "How strongly each driver moves the grid import (MW per MW)", "SIMULATED", "PREDICTED"
)
st.plotly_chart(F.slopes_bars(evo, mods), width="stretch", config={"displayModeBar": False})

G, GE = T.SHORT[OLD], T.EXP[OLD]
Rw, RwE = T.SHORT[NEW], T.EXP[NEW]
R, RE = T.SHORT["E5"], T.EXP["E5"]
st.markdown("#### Reading it")
bullets = [
    "- **AC (physics):** about −1 MW of import per MW of PV, as energy balance requires.",
    f"""- **{G}** ({GE}) tracks the battery almost one-for-one ({coefs[OLD]["chap31"]:+.2f} vs
  {coefs["AC"]["chap31"]:+.2f}) and load partially ({coefs[OLD]["load"]:+.2f} vs
  {coefs["AC"]["load"]:+.2f}), but its PV response is {coefs[OLD]["pv"]:+.2f}: **about
  {abs(coefs[OLD]["pv"] / ac_pv):.0%} of the physical response.** Its synthetic paired probes
  showed the same blind spot before any real data entered.""",
]
if HAS:
    bullets.append(
        f"""- **{Rw}** ({RwE}) was trained with an extra loss on pairs of synthetic AC states that
  differ in one input (PV, battery or one load). Its real PV response is
  {coefs[NEW]["pv"]:+.2f} and its load response {coefs[NEW]["load"]:+.2f} (AC
  {coefs["AC"]["load"]:+.2f}): **the sensitivity transferred.** The battery response overshoots
  ({coefs[NEW]["chap31"]:+.2f}) and the import level is biased by
  {evo.at[NEW, "import_bias_mw"]:+.0f} MW, so the full transfer gate fails."""
    )
bullets += [
    f"""- **{R}** ({RE}) shows a PV slope of {coefs["E5"]["pv"]:+.2f}, but with an import error of
  {evo.at["E5", "import_mae_mw"]:.0f} MW and import correlation r =
  {evo.at["E5", "import_corr"]:.2f}: it does not track real operation, so this slope is not a
  usable response.""",
    """- **Why PV was hard:** HV PV varies by at most 6 MW, while primary load swings by tens of MW
  and the battery by up to ±49.5 MW. In the ordinary training loss such a small signal barely
  counts"""
    + (
        "; normalising the response error per MW of perturbation is what made it count."
        if HAS
        else "."
    ),
    """- **Weather:** the original weather-generalisation question remains unresolved, because no
  model passes the full real-transfer gate.""",
]
st.markdown("\n".join(bullets))
T.footer()

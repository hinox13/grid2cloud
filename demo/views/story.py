"""Scientific story and methodology, in one page: the question and its short answer, what was
built, the original model and its four fine-tuning steps (cards + one chart), the bottom line,
how the evidence was kept honest, the limits of this demo, and possible follow-up work.
Every number comes from model_evolution.csv (the published S1 results); nothing is computed anew."""

from __future__ import annotations

import streamlit as st
from c2g import data as D
from c2g import figures as F
from c2g import theme as T

T.setup("Scientific story")
p = T.palette()
evo = D.evolution()
mods = [m["id"] for m in D.models()]
has_e5d = "E5d" in mods
num = T.num
ac = evo.iloc[0]  # the physics (AC) columns are identical on every row

st.markdown(
    f"""
<style>
.sc-answer {{ color: {p["INK"]}; font-size: 1.02rem; line-height: 1.55; background: {p["SURFACE"]};
  border-left: 4px solid {p["ACCENT"]}; border-radius: 0 10px 10px 0; padding: 10px 16px;
  box-shadow: {p["SHADOW"]}; margin: 12px 0 8px 0; }}
.sc-flow {{ display: grid; grid-template-columns: 1fr auto 1fr auto 1fr auto 1fr; gap: 8px;
  align-items: stretch; margin: 4px 0 6px 0; }}
@media (max-width: 900px) {{ .sc-flow {{ grid-template-columns: 1fr 1fr; }}
  .sc-flow .sc-arrow {{ display: none; }} }}
.sc-stage {{ background: {p["SURFACE"]}; border: 1px solid {p["BORDER"]}; border-radius: 12px;
  padding: 10px 14px; box-shadow: {p["SHADOW"]}; }}
.sc-stage .n {{ color: {p["INK"]}; font-weight: 700; font-size: 1.0rem; margin: 6px 0 4px 0; }}
.sc-stage .d {{ color: {p["INK_2"]}; font-size: 0.9rem; line-height: 1.45; }}
.sc-arrow {{ color: {p["MUTED"]}; align-self: center; font-size: 1.2rem; }}
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------- question and short answer
st.markdown("## The scientific story")
st.markdown(
    '<div class="c2g-sub">Can a neural power-flow foundation model (GENCO) stand in for a physical '
    "AC solver on a real distribution network when the weather drives the grid?</div>",
    unsafe_allow_html=True,
)
if has_e5d:
    e5d = evo.loc["E5d"]
    answer = (
        "<b>Short answer: partly.</b> Out of the box GENCO cannot read this grid. After four "
        "fine-tuning steps on synthetic data only, it learned how the real grid responds to "
        "solar, battery and load, but it still overestimates how much power Sundon draws "
        f"({num(float(e5d.import_bias_mw), '+.0f')} MW), so real transfer is only partial and "
        "the weather question stays open."
    )
else:
    answer = (
        "<b>Short answer: not yet.</b> Fine-tuning on synthetic data fixes the topology and the "
        "operating range, but no model responds correctly to solar, so real transfer fails."
    )
st.markdown(f'<div class="sc-answer">{answer}</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------- what we built
st.markdown("### What we built")
STAGES = [
    ("OBSERVED", "Satellite and grid data", T.INK_2,
     "Meteosat E-View imagery every 15 minutes; UK Power Networks half-hourly operational load "
     "data."),
    ("DERIVED", "Satellite solar forcing", T.PV,
     "LSA SAF irradiance sampled at every registered solar asset and converted to estimated "
     "output with pvlib. Never metered solar."),
    ("SIMULATED", "Physics reference", T.AC,
     "The Sundon 33 kV network rebuilt from public LTDS tables, validated against operational "
     "metering and solved with a full AC power flow."),
    ("PREDICTED", "GENCO", T.MUTED,
     "Frozen GENCO checkpoints predicting the same states: the original model, then four "
     "fine-tuning steps."),
]  # fmt: skip
flow = '<div class="sc-arrow">→</div>'.join(
    f'<div class="sc-stage" style="border-top:3px solid {c}">{T.badge(kind)}'
    f'<div class="n">{title}</div><div class="d">{desc}</div></div>'
    for kind, title, c, desc in STAGES
)
st.markdown(f'<div class="sc-flow">{flow}</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------- the steps (cards + chart)
st.markdown("### From the original model to four fine-tuning steps")
zs, e5, e5b, e5c = (evo.loc[m] for m in ("zero_shot", "E5", "E5b", "E5c"))
cut = (1 - float(e5b.PBE_mean) / float(e5.PBE_mean)) * 100
DETAIL = {
    "zero_shot": (
        "Trained on other grids, it predicts about "
        f"{abs(float(zs.genco_import_mean_mw)):.0f} MW of export where the physics says Sundon "
        f"draws {float(ac.ac_import_mean_mw):.0f} MW: power flows the wrong way in "
        f"{(1 - float(zs.import_sign_accuracy)) * 100:.1f}&nbsp;% of states."
    ),
    "E5": (
        "It fits held-out synthetic states well (error 0.47 MVA), but real loads, battery and "
        "solar lie outside what it was trained on, so its real-state errors stay heavy-tailed."
    ),
    "E5b": (
        "Sampling load, battery and generation over their physical ranges, from public metadata "
        f"only, cuts the real-state error by {cut:.0f}&nbsp;%. Import and voltage tracking still "
        "fail."
    ),
    "E5c": (
        f"Import tracking improves (correlation r = {float(e5c.import_corr):.2f}) and so does the "
        f"battery response ({num(float(e5c.genco_slope_chap31), '+.2f')} against physics "
        f"{num(float(ac.ac_slope_chap31), '+.2f')}), but the solar response stays near zero."
    ),
}
if has_e5d:
    DETAIL["E5d"] = (
        "Trained on pairs of synthetic states that differ in one input, it learns the response: "
        f"solar {num(float(e5d.genco_slope_pv), '+.2f')} and load "
        f"{num(float(e5d.genco_slope_load), '+.2f')} against physics "
        f"{num(float(ac.ac_slope_pv), '+.2f')} and {num(float(ac.ac_slope_load), '+.2f')}. Its "
        "level is too high, voltage error misses its limit and the battery response overshoots "
        f"({num(float(e5d.genco_slope_chap31), '+.2f')}). Verdict: partial."
    )
T.learned_ladder(evo, mods, DETAIL)

st.markdown('<div style="height:14px"></div>', unsafe_allow_html=True)
T.panel_title("Solar response by step, against the physics")
st.plotly_chart(
    F.solar_response_by_step(evo, mods),
    width="stretch",
    config={"displayModeBar": False},
    key="sc_pv",
)

# ---------------------------------------------------------------- the bottom line
st.markdown(
    '<div class="c2g-callout"><b>Bottom line.</b> Synthetic-to-real transfer needs topology and '
    "operating-envelope coverage, and explicit learning of physically meaningful sensitivities. "
    "Correct sensitivity is still not a calibrated model: the final step fails the full "
    "pre-registered real-transfer gate, so the original weather question stays "
    "<b>unresolved</b>. Nothing here shows that weather has no effect, or that GENCO is "
    "weather-robust.</div>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------- honesty and limits
c_honest, c_limits = st.columns(2, gap="large")
with c_honest:
    st.markdown("### How the evidence was kept honest")
    st.markdown(
        """
- **Pre-registration.** Every experiment's gates, selection rule, transfer criteria and verdict
  rules were committed before its data, training or evaluation existed.
- **Synthetic-only selection.** Checkpoints were chosen on synthetic data and frozen, with their
  SHA256 hashes committed, before any real 2024 state was opened.
- **Events chosen by weather, not by model.** The showcase events come from a pre-registered
  meteorological ranking (ramps, broken cloud, clearing, clear sky). None was chosen for how
  GENCO behaved on it.
- **Same real states for every model.** All five models are scored on the same 2,829
  half-hourly 2024 states, with confidence intervals from a day-block bootstrap.
- **No real data in training.** The response-aware model learned its sensitivities from paired
  synthetic states only. The real solar response was never a training or selection target.
- **Stop rules respected.** The weather re-test was pre-registered to run only if real transfer
  succeeded. It did not, so it was not run for steps 2 to 4.
"""
    )
with c_limits:
    st.markdown("### Limits of this demo")
    st.markdown(
        """
- **Half-hourly grid states.** Grid states are half-hourly (UKPN data), while the satellite and
  solar run at 15 minutes. Between grid states the app holds the last state and labels it.
  Nothing is interpolated.
- **Estimated solar, simulated flows.** Solar is a satellite-derived estimate, not metered
  output. The flows are a simulation on a reconstructed network, validated against operational
  metering but not identical to it.
- **Schematic network.** Several network junctions have no published coordinates, so they
  appear only in the schematic.
- **Average sensitivities.** The solar, load and battery responses are averages over 2,829
  states. The per-step attributions on the PV response page apply those averages to one event.
- **No 15-minute predictions for step 4.** Every model is shown on the frozen half-hourly real
  states behind its published metrics. No 15-minute, ramp or weather predictions were made for
  the response-aware model, because its pre-registered rules stopped before that step.
"""
    )

# ---------------------------------------------------------------- follow-up
st.markdown("### Possible follow-up directions")
offset = (
    f" (the response-aware model's {num(float(e5d.import_bias_mw), '+.0f')} MW offset)"
    if has_e5d
    else ""
)
st.markdown(
    f"""
Ideas for further work; each would need its own pre-registration.

- **Calibration correction.** Correct the absolute import level{offset}, learning the
  correction from synthetic data only.
- **Seed stability.** Response-aware training gave very different real accuracy across seeds.
- **Joint response and state training.** Balance absolute accuracy and sensitivities explicitly
  in one training objective.
- **A second network.** Canterbury, where solar is spread over many satellite pixels, so the
  spatial structure of the weather can be tested (hypothesis H2 in the pre-registration).
- **Weather re-test.** Rerun the frozen weather-test protocol (S1 and S2 in the reports) once a
  future model passes the complete real-transfer gate.
"""
)
T.footer()

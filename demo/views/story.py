"""Scientific story and methodology, in one page."""

from __future__ import annotations

import streamlit as st
from c2g import data as D
from c2g import theme as T

T.setup("Scientific story")
evo = D.evolution()
mods = [m["id"] for m in D.models()]

st.markdown("## The scientific story")
st.markdown(
    '<div class="c2g-sub">Can a neural power-flow foundation model (GENCO) stand in for a physical '
    "AC solver on a real distribution network when the weather drives the grid?</div>",
    unsafe_allow_html=True,
)

st.markdown("### What we built")
c1, c2, c3, c4 = st.columns(4)
c1.markdown(
    f"{T.badge('OBSERVED')}\n\n**Satellite & grid data**\n\nMeteosat E-View imagery every "
    "15 minutes; UK Power Networks half-hourly operational load data.",
    unsafe_allow_html=True,
)
c2.markdown(
    f"{T.badge('DERIVED')}\n\n**Satellite PV forcing**\n\nLSA SAF irradiance sampled at "
    "every registered PV asset, converted to estimated output with pvlib. Never measured "
    "PV.",
    unsafe_allow_html=True,
)
c3.markdown(
    f"{T.badge('SIMULATED')}\n\n**AC reference**\n\nThe Sundon 33 kV network rebuilt "
    "from LTDS tables, validated against operational metering, solved with a full AC "
    "power flow.",
    unsafe_allow_html=True,
)
c4.markdown(
    f"{T.badge('PREDICTED')}\n\n**GENCO**\n\nFrozen GENCO checkpoints predicting the same "
    "states: off-the-shelf, then four adaptation recipes (grid-tuned, envelope-tuned, "
    "generator-aware, response-aware).",
    unsafe_allow_html=True,
)

st.markdown("### What each experiment found")
zs, e5, e5b, e5c = (evo.loc[m] for m in ("zero_shot", "E5", "E5b", "E5c"))
e5d = evo.loc["E5d"] if "E5d" in mods else None
steps = [
    (
        "zero_shot",
        "Off-the-shelf GENCO fails on a new grid (E4)",
        "Off-the-shelf GENCO, trained on other grids, predicts about "
        f"{abs(zs.genco_import_mean_mw):.0f}"
        f" MW of export where the AC solution imports {zs.ac_import_mean_mw:.0f} MW. Mean power-"
        f"balance error {zs.PBE_mean:.1f} MVA.",
    ),
    (
        "E5",
        "Grid-tuned: fits synthetic states, not real operation (E5)",
        "Fine-tuning on synthetic Sundon states brings held-out synthetic error down to 0.47 MVA, "
        f"but on real states the error stays heavy-tailed (PBE {e5.PBE_mean:.1f} MVA, import r = "
        f"{e5.import_corr:.2f}): real loads, battery and PV lie outside the synthetic support.",
    ),
    (
        "E5b",
        "Envelope-tuned: a broad physics-informed envelope cuts real error by ~99 % (E5b)",
        f"Sampling loads, battery and generation over their physical ranges from static metadata "
        f"(no real data) brings real-state PBE down to {e5b.PBE_mean:.2f} MVA "
        f"({1 - e5b.PBE_mean / e5.PBE_mean:.1%} below grid-tuned). "
        "Import and voltage tracking still fail.",
    ),
    (
        "E5c",
        "Generator-aware: explicit generators help load and battery, not PV (E5c)",
        f"Representing PV as explicit generator nodes improves import tracking (r = "
        f"{e5c.import_corr:.2f}, battery slope {e5c.genco_slope_chap31:+.2f} vs AC "
        f"{e5c.ac_slope_chap31:+.2f}), but the PV slope stays at {e5c.genco_slope_pv:+.2f} against "
        f"AC {e5c.ac_slope_pv:+.2f}.",
    ),
]
if e5d is not None:
    steps.append(
        (
            "E5d",
            "Response-aware: the PV sensitivity is learned and transfers; calibration is still off "
            "(E5d)",
            "Adding a loss on pairs of synthetic AC states that differ in one input teaches the "
            f"response: the real PV slope moves from {e5c.genco_slope_pv:+.2f} to "
            f"{e5d.genco_slope_pv:+.2f} (AC {e5d.ac_slope_pv:+.2f}) and load from "
            f"{e5c.genco_slope_load:+.2f} to {e5d.genco_slope_load:+.2f}. But the import sits "
            f"{e5d.import_bias_mw:+.0f} MW too high, voltage error misses its limit and the "
            "battery "
            f"response overshoots ({e5d.genco_slope_chap31:+.2f}): verdict E5D-D, partial.",
        )
    )
for mid, head, body in steps:
    st.markdown(f"{T.swatch(mid)} **{head}**  \n{body}", unsafe_allow_html=True)

st.markdown(
    '<div class="c2g-callout"><b>Synthetic-to-real transfer requires not only topology and '
    "operating-envelope coverage, but explicit learning of physically meaningful sensitivities."
    "</b> Correct sensitivity is still not the same as a fully calibrated real-grid model.</div>",
    unsafe_allow_html=True,
)
st.markdown("### What did we learn?")
T.learned_ladder(evo, mods)
st.markdown(
    '<div class="c2g-callout">The original weather-generalisation question remains '
    "<b>unresolved</b>, because the final model still fails the full real-transfer gate. Nothing "
    "here shows that weather has no effect, or that GENCO is weather-robust.</div>",
    unsafe_allow_html=True,
)

st.markdown("### How the evidence was kept honest")
st.markdown(
    """
- **Pre-registration.** Every experiment's gates, selection rule, transfer criteria and verdict
  rules were committed before its data, training or evaluation existed.
- **Synthetic-only selection.** Checkpoints were chosen on synthetic data and frozen (sha256
  hashes committed) before any real 2024 state was opened.
- **Events chosen by weather, not by model.** Hero events come from a pre-registered
  meteorological ranking (ramps, broken cloud, clearing, clear sky). None was chosen for how
  GENCO behaved on it.
- **Same real states for every model.** All five models are scored on the same 2,829 half-hourly
  2024 states, with confidence intervals from a day-block bootstrap.
- **No real data in training.** The response-aware model learned its sensitivities from paired
  synthetic AC states only; the real PV slope was never a training or selection target.
- **Stop rules respected.** The weather-generalisation re-test was pre-registered to run only if
  real transfer succeeded. It did not, so it was not run for the envelope-tuned,
  generator-aware or response-aware models.
"""
)

st.markdown("### Limits of this demo")
st.markdown(
    """
- Grid states are **half-hourly** (UKPN data); the satellite and PV run at 15 minutes. Between
  grid states the app holds the last state and labels it. Nothing is interpolated.
- PV is a **satellite-derived estimate**, not metered output. The AC flows are a **simulation**
  on a reconstructed network, validated against operational metering but not identical to it.
- Several network junctions have **no published coordinates**; they appear only in the
  schematic.
- The S1 regression slopes summarise average sensitivity over 2,829 states; per-step
  attributions on the PV page apply those averages to one event's input changes.
- Every model, including the response-aware one, is shown on the frozen half-hourly real states
  used for its published metrics. No 15-minute, ramp or weather predictions were made for the
  response-aware model, because its pre-registered rules stopped before that step.
"""
)

st.markdown("### Possible follow-up directions")
st.markdown(
    """
Ideas for further work; each would need its own pre-registration.

- **Bias / calibration correction** of the absolute import level (the response-aware model's
  +13 MW offset), learned from synthetic data only.
- **Seed stability.** Response-aware training gave very different real accuracy across seeds.
- **Multi-objective response + state training**, balancing absolute accuracy and sensitivities
  explicitly.
- **Canterbury spatial experiment:** a second network where PV is spread over many pixels, so
  spatial weather structure (hypothesis H2) can be tested.
- **Weather re-test** with the frozen S1 / S2 protocol, once a future model passes the complete
  real-transfer gate.
"""
)
T.footer()

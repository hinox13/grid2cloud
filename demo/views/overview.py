"""Overview: the 30-second version — the question, the finding, and one frozen moment of the
15 June story (11:00 → 11:30 UTC). Every number comes from the frozen bundle and the published
S1 coefficients (the same sources as the story captions); nothing is computed anew."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from c2g import data as D
from c2g import figures as F
from c2g import satellite as SAT
from c2g import story as S
from c2g import theme as T

T.setup("Overview", toggle=False)
ss = st.session_state
sc = S.script()
ev = D.event(sc["event"])
a, b = (pd.Timestamp(sc["refs"][k]) for k in ("a", "b"))
v = S._static_vars()
REPO = "https://github.com/hinox13/grid2cloud"

# ---------------------------------------------------------------- hero header
h_left, h_right = st.columns([3.2, 1.2], vertical_alignment="center")
with h_left:
    st.markdown(
        '<div class="c2g-hero"><div class="c2g-hero-title">'
        'Cloud<span class="c2g-two">2</span>Grid</div>'
        '<div class="c2g-hero-tag">Testing a grid foundation model against real '
        "satellite-driven renewable variability.</div></div>",
        unsafe_allow_html=True,
    )
with h_right:
    _, tcol = st.columns([2.2, 1])
    with tcol:
        T.theme_toggle()

st.markdown(
    """
- **The question.** Can GENCO, a grid foundation model trained on synthetic networks, transfer to
  an unseen *real* distribution network whose solar output follows the real weather?
- **What we did.** We rebuilt the Sundon network (UK Power Networks), drove it with
  satellite-derived PV, and adapted GENCO step by step — ending with a new
  **physics-response-aware loss** that teaches GENCO how the grid responds to PV, battery and load.
- **What we found.** GENCO learned the correct PV sensitivity, and it transferred to real
  operating states — but **accurate sensitivities did not give an accurate absolute state**: its
  grid import is still biased.
"""
)

# ---------------------------------------------------------------- frozen moment
st.markdown(f"### A frozen moment: 15 June 2024, {a:%H:%M} → {b:%H:%M} UTC")
c_a, c_b, c_t = st.columns([1.0, 1.0, 1.7], gap="medium")
for col, t in ((c_a, a), (c_b, b)):
    frame = ev.frames[ev.frames.timestamp_utc == t].iloc[0]
    pv_now = ev.pv_generation[ev.pv_generation.timestamp_utc == t]
    with col:
        T.panel_title(f"Meteosat E-View · {t:%H:%M} UTC · zoomed to Sundon", "OBSERVED")
        st.html(SAT.render(frame, None, ev.nodes, ev.edges, ev.assets, pv_now, True))
with c_t:
    T.panel_title(
        "PV and grid import · AC vs response-aware GENCO", "DERIVED", "SIMULATED", "PREDICTED"
    )
    st.plotly_chart(
        F.timeline(ev.fleet_pv, ev.summary, "E5d", b, b, band=(a, b, "cloud field clears")),
        width="stretch",
        config={"displayModeBar": False},
        key="ov_tl",
    )
beat3 = next(bt for bt in S.beats() if bt.highlight == "cloud field clears")
st.markdown(
    f'<div class="c2g-note">{S.caption(beat3, b, float("nan"), float("nan"), float("nan"))}</div>',
    unsafe_allow_html=True,
)

st.markdown("### The finding, across all 2,829 real states")
T.faceoff(
    ("AC reference", f"{v['s_ac_pv']} MW", "import change per MW of PV (physics)", T.AC),
    ("Generator-aware GENCO (E5c)", f"{v['s_e5c_pv']} MW", "almost blind to PV", T.colour("E5c")),
    (
        "Response-aware GENCO (E5d)",
        f"{v['s_e5d_pv']} MW",
        "the PV sensitivity is learned",
        T.colour("E5d"),
    ),
    (
        "E5d import level",
        f"{v['bias_e5d']} MW",
        "too high: not yet calibrated (verdict partial)",
        T.colour("E5d"),
    ),
)
st.markdown(
    '<div class="c2g-note">Sensitivities are slopes from the published regression of grid '
    "import on PV, load and battery over the 2,829 held-out 2024 states. AC values are simulated "
    "physical "
    "references, not measurements.</div>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------- next steps
b1, b2, b3 = st.columns(3)
if b1.button(
    "Play the 15 June story", icon=":material/play_circle:", type="primary", width="stretch"
):
    ss.update(story_on=True, story_paused=False, beat=0, beat_age=-1, playing=False)
    st.switch_page("views/explorer.py")
if b2.button("Open the demo", icon=":material/satellite_alt:", width="stretch"):
    st.switch_page("views/explorer.py")
with b3:
    st.page_link("views/story.py", label="Read the scientific story", icon=":material/explore:")
st.markdown(
    f"[Code]({REPO}) · "
    f"[Frozen models + verification data]({REPO}/releases/tag/cloud2grid-models-v1) · "
    f"[Reproduce in one command]({REPO}/blob/cloud2grid-models-v1/reproduce/README.md)"
)
T.footer()

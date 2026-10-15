"""Demo: replay a frozen hero event — real clouds → solar power → power grid → GENCO.

Two modes share one stage:
  manual  pick event / model / time, or Play the event;
  story   "Play the 15 June story": a fixed, captioned sequence of scenes (c2g/story.py), shown
          like slides — within a scene, image steps advance quickly (1 s) and model changes keep
          their authored hold; at the end of each scene the story waits for Next (or continues
          after the authored hold when Auto-play is on).
Charts keep stable keys so Plotly updates in place during playback (no remount flicker)."""

from __future__ import annotations

import streamlit as st
from c2g import data as D
from c2g import figures as F
from c2g import satellite as SAT
from c2g import story as S
from c2g import theme as T

T.setup("Demo", toggle=False)
cat = D.catalog()
mods = [m["id"] for m in D.models()]
events = {e["event_id"]: e for e in cat["events"]}
layout = D.network_layout()
BEATS = S.beats()
STORY_EVENT = S.script()["event"]
TICK_S = 1.0

ss = st.session_state
ss.setdefault("story_on", False)
ss.setdefault("story_paused", False)
ss.setdefault("beat", 0)
ss.setdefault("beat_age", 0)
ss.setdefault("playing", False)
ss.setdefault("story_auto", False)
ss.setdefault("t_idx", 0)
ss.setdefault("model", "E5c")
ss.setdefault("colour_by", "Loading")


def scene_start(scene: int) -> int:
    """Index of the first beat of a scene."""
    return next(k for k, b in enumerate(BEATS) if b.scene == scene)


def start_story() -> None:
    ss.update(story_on=True, story_paused=False, beat=0, beat_age=-1, playing=False)


def stop_story() -> None:
    b = BEATS[min(ss.beat, len(BEATS) - 1)]
    # leave the explorer where the story ended
    ss.update(
        story_on=False,
        story_paused=False,
        _event=STORY_EVENT,
        event=STORY_EVENT,
        t_idx=b.t,
        model=b.model,
    )


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
    if ss.story_on:  # story controls live in the header so the stage keeps its height
        cur = BEATS[ss.beat].scene
        c1, c2, c3 = st.columns(3)
        if c1.button(
            "Back", icon=":material/skip_previous:", width="stretch", key="story_back",
            disabled=cur == 0,
        ):  # fmt: skip
            ss.update(beat=scene_start(cur - 1), beat_age=-1, story_paused=False)
            st.rerun()
        if c2.button(
            "Next", icon=":material/skip_next:", width="stretch", key="story_next",
            type="primary", disabled=cur == S.n_scenes() - 1,
        ):  # fmt: skip
            ss.update(beat=scene_start(cur + 1), beat_age=-1, story_paused=False)
            st.rerun()
        if c3.button("Exit", icon=":material/close:", width="stretch", key="exit_story"):
            stop_story()
            st.rerun()
        st.toggle("Auto-play", key="story_auto", help="Continue to the next scene automatically.")
    elif st.button(
        "Play the 15 June story",
        icon=":material/play_circle:",
        type="primary",
        width="stretch",
        key="play_story",
    ):
        start_story()
        st.rerun()

# ---------------------------------------------------------------- manual controls
if ss.story_on:
    bid = STORY_EVENT
    colour_by = "Loading"
else:
    c_ev, c_model, c_view, c_play = st.columns([1.5, 4.7, 1.4, 0.8], vertical_alignment="bottom")
    with c_ev:
        bid = st.selectbox(
            "Hero event", list(events), key="event", format_func=lambda k: events[k]["title"]
        )
    with c_model:
        st.segmented_control(
            "Grid shown",
            ["AC", *mods],
            key="model",
            format_func=lambda m: "AC" if m == "AC" else T.SHORT[m],
        )
        sel = ss.get("model") or "AC"
        st.markdown(
            f'<div class="c2g-pill">{T.swatch(sel)}<b>{T.NAMES[sel]}</b>{T.exp_tag(sel)} — '
            f"{T.ABOUT[sel]}. <i>Result:</i> {T.VERDICT[sel]}</div>",
            unsafe_allow_html=True,
        )
    with c_view:
        colour_by = (
            st.segmented_control("Branch colour", ["Loading", "Error vs AC"], key="colour_by")
            or "Loading"
        )
ev = D.event(bid)
n = len(ev.steps)
if not ss.story_on and ss.get("_event") != bid:
    ss.update(_event=bid, t_idx=0, playing=False)
if not ss.story_on:
    with c_play:
        if st.button(
            "Pause" if ss.playing else "Play",
            icon=":material/pause:" if ss.playing else ":material/play_arrow:",
            width="stretch",
            key="play_btn",
        ):
            if not ss.playing and ss.t_idx >= n - 1:
                ss.t_idx = 0
            ss.playing = not ss.playing
            st.rerun()

ticking = (ss.story_on and not ss.story_paused) or (not ss.story_on and ss.playing)


def flow(items: list[tuple[str, str, str, str, str]]) -> None:
    """REAL CLOUDS → SOLAR POWER → POWER GRID → GENCO, with live values and provenance."""
    html = []
    for i, (stage, kind, v, s, accent) in enumerate(items):
        if i:
            html.append('<div class="c2g-arrow">→</div>')
        html.append(
            f'<div class="c2g-chip" style="border-top:3px solid {accent}">'
            f'<div class="k">{stage} {T.badge(kind)}</div><div class="v">{v}</div>'
            f'<div class="s">{s}</div></div>'
        )
    st.markdown(f'<div class="c2g-chain">{"".join(html)}</div>', unsafe_allow_html=True)


@st.fragment(run_every=TICK_S if ticking else None)
def stage() -> None:
    # ---- advance the clock (story beats or manual playback)
    if ss.story_on:
        if not ss.story_paused:
            beat = BEATS[ss.beat]
            ss.beat_age += 1
            nxt = ss.beat + 1 if ss.beat < len(BEATS) - 1 else None
            if nxt is not None and BEATS[nxt].scene == beat.scene:
                # within a scene: image steps advance quickly; a model change keeps its hold
                wait = 1 if BEATS[nxt].model == beat.model else max(beat.hold, 1)
                if ss.beat_age >= wait:
                    ss.update(beat=nxt, beat_age=0)
            elif nxt is not None and ss.story_auto:
                if ss.beat_age >= max(beat.hold, 2):
                    ss.update(beat=nxt, beat_age=0)
            else:
                ss.story_paused = True  # end of a scene (or of the story): wait for Next
                st.rerun()  # full rerun: stops the timer
        beat = BEATS[ss.beat]
        i, view, watch = beat.t, beat.model, beat.watch
    else:
        if ss.playing:
            if ss.t_idx >= n - 1:
                ss.playing = False
                st.rerun()
            ss.t_idx += 1
        i, view, watch = int(ss.t_idx), (ss.get("model") or "AC"), ""

    frame = ev.frames.iloc[i]
    t = frame.timestamp_utc
    g = ev.grid_slot_for(t)
    fleet = ev.fleet_pv.set_index("timestamp_utc").fleet_pv_mw
    pv_t = float(fleet.get(t, float("nan")))
    pv_now = ev.pv_generation[ev.pv_generation.timestamp_utc == t]
    irr = ev.irradiance[ev.irradiance.timestamp_utc == t]
    hv = irr[irr.asset_id == "ECR:955"]
    site = hv if len(hv) else irr
    kc = float(site.clearsky_index.mean())
    ghi = float(site.ghi_wm2.mean())
    s = ev.summary[ev.summary.timestamp_utc == g].set_index("model")
    ac_imp = float(s.at["AC", "import_mw"])
    m_imp = float(s.at[view, "import_mw"])
    sky = "clear" if kc >= 0.8 else "broken cloud" if kc >= 0.5 else "overcast"
    held = (
        f"grid state {g:%H:%M}"
        if g == t
        else f"grid state held since {g:%H:%M}"
        if g < t
        else f"next grid state {g:%H:%M}"
    )

    # ---- story banner or manual time slider
    if ss.story_on:
        beat = BEATS[ss.beat]
        dots = "".join(
            f'<span class="c2g-dot{" on" if k <= beat.scene else ""}"></span>'
            for k in range(S.n_scenes())
        )
        st.markdown(
            f'<div class="c2g-story"><div class="c2g-story-head">{dots}'
            f'<span class="c2g-story-step">{beat.scene + 1} / {S.n_scenes()}</span>'
            f'<span class="c2g-story-title">{beat.title}</span></div>'
            f'<div class="c2g-story-cap">{S.caption(beat, t, pv_t, ac_imp, m_imp)}</div></div>',
            unsafe_allow_html=True,
        )
        if ss.story_paused and beat.scene < S.n_scenes() - 1:
            st.markdown(
                '<div class="c2g-note">Press <b>Next</b> for the next scene.</div>',
                unsafe_allow_html=True,
            )
        if ss.beat == len(BEATS) - 1:
            st.page_link(
                "views/pv_response.py", label="See the PV response →", icon=":material/wb_sunny:"
            )

    flow(
        [
            ("Real clouds", "OBSERVED", sky, f"Meteosat · clear-sky index {kc:.2f}", T.INK_2),
            ("Solar power", "DERIVED", f"{pv_t:.1f} MW", f"PV fleet · GHI {ghi:.0f} W/m²", T.PV),
            ("Power grid", "SIMULATED", f"{ac_imp:.1f} MW", f"AC import · {held}", T.AC),
            (
                "GENCO",
                "PREDICTED",
                f"{m_imp:.1f} MW" if view != "AC" else "—",
                f"{T.SHORT[view]} · error {m_imp - ac_imp:+.1f} MW"
                if view != "AC"
                else ("enters in scene 4" if ss.story_on else "select a model"),
                T.colour(view) if view != "AC" else T.MUTED,
            ),
        ]
    )

    if ss.story_on:  # cinema: two large panels, no metrics column
        left, mid = st.columns([1.0, 1.15], gap="medium")
        right = None
    else:
        left, mid, right = st.columns([1.0, 1.5, 0.48], gap="medium")
    with left:
        T.panel_title(
            f"Meteosat E-View · {t:%d %b %Y %H:%M} UTC", "OBSERVED", focus=watch == "satellite"
        )
        zoom = st.toggle("Zoom to Sundon", value=False, key="zoom")
        last = ss.get("_sat_prev")
        prev = ev.frames.iloc[last[1]] if last and last[0] == bid and last[1] < n else None
        st.html(
            SAT.render(
                frame,
                prev,
                ev.nodes,
                ev.edges,
                ev.assets,
                pv_now,
                zoom,
                fade_ms=int(TICK_S * 1000 * 0.97),
            )
        )
        ss["_sat_prev"] = (bid, i)
        st.markdown(
            '<div class="c2g-note">Bright = cloud · dotted box = Sundon study area · yellow = PV '
            "assets (size: capacity, opacity: estimated output). Real 15-minute images; "
            "consecutive images cross-fade (display transition only).</div>",
            unsafe_allow_html=True,
        )
    with mid:
        kind = "SIMULATED" if view == "AC" else "PREDICTED"
        T.panel_title(f"Sundon network · {T.LABELS[view]} · {held}", kind, focus=watch == "network")
        br = ev.branch[ev.branch.timestamp_utc == g]
        bus = ev.bus[(ev.bus.timestamp_utc == g) & (ev.bus.model == view)]
        mode = "error" if (colour_by == "Error vs AC" and view != "AC") else "flow"
        st.plotly_chart(
            F.network(
                ev.nodes,
                ev.edges,
                br[br.model == view],
                br[br.model == "AC"],
                bus,
                view,
                mode,
                layout,
            ),
            width="stretch",
            config={"displayModeBar": False},
            key="net",
        )
        st.markdown(T.network_legend(mode), unsafe_allow_html=True)
    if right is not None:
        with right:
            T.panel_title(f"At {g:%H:%M}")
            if view != "AC":
                st.metric(
                    "Import error",
                    f"{m_imp - ac_imp:+.1f} MW",
                    help="Predicted minus AC grid import at the Sundon 132 kV supply.",
                )
                st.metric(
                    "Power-balance error",
                    f"{float(s.at[view, 'PBE_mean']):.2f} MVA",
                    help="Mean nodal power-balance error of the prediction (PBE). AC = 0.",
                )
            st.metric("Max loading · AC", f"{float(s.at['AC', 'max_loading_pct']):.0f} %")
            if view != "AC":
                st.metric(
                    "Max loading · model",
                    f"{float(s.at[view, 'max_loading_pct']):.0f} %",
                )

    if not ss.story_on:
        st.select_slider(
            "Time (UTC)",
            options=list(range(n)),
            key="t_idx",
            format_func=lambda k: f"{ev.steps[k]:%H:%M}",
            help="15-minute satellite steps; the grid state is half-hourly and held between.",
        )
    band = S.band(BEATS[ss.beat]) if ss.story_on else None
    T.panel_title("Timeline", "DERIVED", "SIMULATED", "PREDICTED", focus=watch == "timeline")
    st.plotly_chart(
        F.timeline(ev.fleet_pv, ev.summary, view, t, g, band=band),
        width="stretch",
        config={"displayModeBar": False},
        key="tl",
    )


stage()

if not ss.story_on:
    st.markdown(f'<div class="c2g-note">{ev.meta["story"]}</div>', unsafe_allow_html=True)
with st.expander("What am I looking at?"):
    st.markdown(
        f"""
- **Real clouds ({T.PROVENANCE["OBSERVED"].lower()}):** EUMETSAT Meteosat E-View imagery, every
  15 minutes.
- **Solar power ({T.PROVENANCE["DERIVED"].lower()}):** LSA SAF satellite radiation sampled at each
  registered PV asset and converted to estimated PV output with pvlib. Not metered PV.
- **Power grid ({T.PROVENANCE["SIMULATED"].lower()}):** AC power flow on the reconstructed and
  operationally validated Sundon network, driven by UKPN half-hourly load data and satellite PV.
- **GENCO ({T.PROVENANCE["PREDICTED"].lower()}):** frozen GENCO checkpoints predicting the same
  states: **Off-the-shelf** (as published, E4), **Grid-tuned** (standard synthetic fine-tuning,
  E5), **Envelope-tuned** (fine-tuned on the real operating range, E5b), **Generator-aware**
  (envelope-tuned with PV as explicit generators, E5c) and **Response-aware** (also trained to
  match AC responses on paired synthetic states, E5d; partial result).
- **Time:** satellite and PV every 15 minutes; grid states every 30 minutes, the last one held
  in between (never interpolated). Limitations: *Scientific story* page.
"""
    )
T.footer()

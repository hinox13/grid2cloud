"""Demo: replay a frozen hero event — real clouds → solar power → power grid → GENCO.

Two modes share one stage:
  manual  pick event / model / time, or Play the event;
  story   "Play the 15 June story": a fixed, captioned sequence of scenes (c2g/story.py), shown
          as still slides. Each slide shows the last beat of its scene, with the caption filled
          at that beat, and waits for Next. "Replay this scene" steps through the scene's beats
          (1 s each) and stops on the slide again. A scene that switches model is split into one
          slide per model. Auto-play advances the slides after a short dwell.
Charts keep stable keys so Plotly updates in place during playback (no remount flicker)."""

from __future__ import annotations

import streamlit as st
from c2g import data as D
from c2g import figures as F
from c2g import satellite as SAT
from c2g import story as S
from c2g import theme as T

T.setup("Demo", toggle=False)
_p = T.palette()
st.markdown(
    f"""<style>
[data-testid="stButtonGroup"] > div {{ flex-wrap: wrap; }}
[data-testid="stButtonGroup"] button {{ min-height: 2.5rem; }}
.st-key-story_card {{ background: {_p["SURFACE"]}; border: 1px solid {_p["BORDER"]};
  border-left: 4px solid {_p["ACCENT"]}; border-radius: 0 12px 12px 0; padding: 12px 18px 8px 18px;
  box-shadow: {_p["SHADOW"]}; gap: 0.4rem; }}
.st-key-story_card .c2g-story-cap {{ min-height: 4.8em; }}
.c2g-context {{ color: {_p["INK_2"]}; font-size: 0.82rem; line-height: 1.5; margin: -2px 0 8px 0; }}
.c2g-context b {{ color: {_p["INK"]}; }}
</style>""",
    unsafe_allow_html=True,
)
cat = D.catalog()
mods = [m["id"] for m in D.models()]
events = {e["event_id"]: e for e in cat["events"]}
layout = D.network_layout()
BEATS = S.beats()
STORY_EVENT = S.script()["event"]
TICK_S = 1.0
AUTO_DWELL_S = 5  # Auto-play: seconds on each still slide


def _slides() -> list[list[int]]:
    """Beat indices per slide: one slide per scene, or one per model if the scene switches model."""
    out: list[list[int]] = []
    for sc in range(S.n_scenes()):
        idx = [k for k, b in enumerate(BEATS) if b.scene == sc]
        out.extend([[k] for k in idx] if len({BEATS[k].model for k in idx}) > 1 else [idx])
    return out


SLIDES = _slides()

ss = st.session_state
ss.setdefault("story_on", False)
ss.setdefault("slide", 0)
ss.setdefault("replay", False)
ss.setdefault("tick", 0)
ss.setdefault("beat", 0)
ss.setdefault("playing", False)
ss.setdefault("story_auto", False)
ss.setdefault("t_idx", 0)
ss.setdefault("model", "E5c")
ss.setdefault("colour_by", "Loading")


def go_slide(k: int) -> None:
    """Show slide k as a still: its scene's last beat, no replay running."""
    ss.update(slide=k, beat=SLIDES[k][-1], replay=False, tick=-1)


def slide_label(k: int) -> str:
    """'4b / 6' for the second slide of scene 4."""
    sc = BEATS[SLIDES[k][-1]].scene
    same = [j for j, sl in enumerate(SLIDES) if BEATS[sl[-1]].scene == sc]
    sub = "abcdefgh"[same.index(k)] if len(same) > 1 else ""
    return f"{sc + 1}{sub} / {S.n_scenes()}"


def start_story() -> None:
    ss.update(story_on=True, playing=False)
    go_slide(0)


def stop_story() -> None:
    b = BEATS[min(ss.beat, len(BEATS) - 1)]
    # leave the explorer where the story ended
    ss.update(
        story_on=False,
        replay=False,
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
    _, tcol = st.columns([1, 1])
    with tcol:
        T.theme_toggle()
    if ss.pop("story_start", False):  # "Take the guided tour" on the Overview
        start_story()
    if ss.story_on:  # story controls live in the header so the stage keeps its height
        c1, c2, c3 = st.columns(3)
        if c1.button(
            "Back", icon=":material/skip_previous:", width="stretch", key="story_back",
            disabled=ss.slide == 0,
        ):  # fmt: skip
            go_slide(ss.slide - 1)
            st.rerun()
        if c2.button(
            "Next", icon=":material/skip_next:", width="stretch", key="story_next",
            type="primary", disabled=ss.slide == len(SLIDES) - 1,
        ):  # fmt: skip
            go_slide(ss.slide + 1)
            st.rerun()
        if c3.button("Exit", icon=":material/close:", width="stretch", key="exit_story"):
            stop_story()
            st.rerun()
        st.toggle(
            "Auto-play", key="story_auto",
            help=f"Move to the next slide every {AUTO_DWELL_S} seconds.",
        )  # fmt: skip
    elif st.button(
        "Take the guided tour",
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
    c_ev, c_model, c_view = st.columns([2.0, 4.9, 2.0], vertical_alignment="bottom")
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
    with c_view:
        colour_by = (
            st.segmented_control("Branch colour", ["Loading", "Error vs AC"], key="colour_by")
            or "Loading"
        )
ev = D.event(bid)
n = len(ev.steps)
if not ss.story_on and ss.get("_event") != bid:
    ss.update(_event=bid, t_idx=0, playing=False)
if not ss.story_on:  # what the event and the selected model are, right under their controls
    sel = ss.get("model") or "AC"
    st.markdown(
        f'<div class="c2g-context"><b>{events[bid]["title"]}:</b> {ev.meta["story"]}<br>'
        f"{T.swatch(sel)}<b>{T.NAMES[sel]}</b>{T.exp_tag(sel)}: {T.ABOUT[sel]}. "
        f"<i>Result:</i> {T.VERDICT[sel]}</div>",
        unsafe_allow_html=True,
    )

ticking = (ss.story_on and (ss.replay or (ss.story_auto and ss.slide < len(SLIDES) - 1))) or (
    not ss.story_on and ss.playing
)


def flow(items: list[tuple[str, str, str, str, str]]) -> None:
    """REAL CLOUDS → SOLAR POWER → POWER GRID → GENCO, with live values and provenance."""
    html = []
    for i, (stage, kind, v, s, accent) in enumerate(items):
        if i:
            html.append('<div class="c2g-arrow">→</div>')
        html.append(
            f'<div class="c2g-chip" style="border-top:3px solid {accent}">'
            f'<div class="k">{stage} {"" if ss.story_on else T.badge(kind)}</div>'
            f'<div class="v">{v}</div>'
            f'<div class="s">{s}</div></div>'
        )
    st.markdown(f'<div class="c2g-chain">{"".join(html)}</div>', unsafe_allow_html=True)


@st.fragment(run_every=TICK_S if ticking else None)
def stage() -> None:
    # ---- advance the clock (story beats or manual playback)
    if ss.story_on:
        sl = SLIDES[ss.slide]
        ss.tick += 1  # -1 after a slide change, so the first run shows the frame as it is
        if ss.replay and ss.tick >= 1:  # replay: one beat per tick, then rest on the slide
            pos = sl.index(ss.beat) if ss.beat in sl else len(sl) - 1
            if pos < len(sl) - 1:
                ss.update(beat=sl[pos + 1], tick=0)
            else:
                ss.update(replay=False, tick=0)
                st.rerun()  # full rerun: stops the timer
        elif not ss.replay and ss.story_auto and ss.slide < len(SLIDES) - 1:
            if ss.tick >= AUTO_DWELL_S:
                go_slide(ss.slide + 1)
                st.rerun()  # full rerun: header buttons follow the slide
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
        # the caption is written for the slide's own beat, so it stays still during a replay
        key = BEATS[SLIDES[ss.slide][-1]]
        kt = ev.frames.iloc[key.t].timestamp_utc
        ks = ev.summary[ev.summary.timestamp_utc == ev.grid_slot_for(kt)].set_index("model")
        cap = S.caption(
            key,
            kt,
            float(fleet.get(kt, float("nan"))),
            float(ks.at["AC", "import_mw"]),
            float(ks.at[key.model, "import_mw"]),
        )
        split = (
            len(SLIDES[ss.slide]) == 1
            and sum(BEATS[sl[-1]].scene == key.scene for sl in SLIDES) > 1
        )
        title = f"{key.title} · {T.NAMES[key.model]}" if split else key.title
        dots = "".join(
            f'<span class="c2g-dot{" on" if k <= key.scene else ""}"></span>'
            for k in range(S.n_scenes())
        )
        card = st.container(key="story_card")
        card.markdown(
            f'<div class="c2g-story-head">{dots}'
            f'<span class="c2g-story-step">{slide_label(ss.slide)}</span>'
            f'<span class="c2g-story-title">{title}</span></div>'
            f'<div class="c2g-story-cap">{cap}</div>',
            unsafe_allow_html=True,
        )
        # status row inside the card: same height on every slide, so the stage never jumps
        n_c, r_c = card.columns([5, 1.1], vertical_alignment="center")
        last = ss.slide == len(SLIDES) - 1
        with n_c:
            if ss.replay:
                note = f"Replaying this scene: <b>{t:%H:%M} UTC</b>"
            elif last:
                note = "End of the story."
            elif ss.story_auto:
                note = f"Auto-play: the next slide follows in {AUTO_DWELL_S} seconds."
            else:
                note = "Press <b>Next</b> for the next scene."
            st.markdown(  # fixed height: the row keeps its size with or without a button
                f'<div class="c2g-note" style="min-height:2.6rem;display:flex;align-items:center">'
                f"<span>{note}</span></div>",
                unsafe_allow_html=True,
            )
        with r_c:
            if last:
                st.page_link(
                    "views/pv_response.py", label="See the PV response", icon=":material/wb_sunny:"
                )
            elif len(SLIDES[ss.slide]) > 1 and st.button(  # only scenes with steps to replay
                "Replay this scene", icon=":material/replay:", width="stretch",
                key="story_replay", disabled=ss.replay,
            ):  # fmt: skip
                ss.update(replay=True, beat=SLIDES[ss.slide][0], tick=-1)
                st.rerun()

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

    left, mid = st.columns([1.0, 1.15], gap="medium")
    with left:
        T.panel_title(
            f"Meteosat E-View · {t:%d %b %Y %H:%M} UTC",
            *(() if ss.story_on else ("OBSERVED",)),
            focus=watch == "satellite",
        )
        # the story is always zoomed to Sundon; in manual mode the switch sits under the image
        zoom = True if ss.story_on else bool(ss.get("zoom", False))
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
        if not ss.story_on:
            st.toggle("Zoom to Sundon", key="zoom")
        st.markdown(
            '<div class="c2g-note">Bright = cloud · dotted box = Sundon study area · yellow = PV '
            "assets (size: capacity, opacity: estimated output). Real 15-minute images; "
            "consecutive images cross-fade (display transition only).</div>",
            unsafe_allow_html=True,
        )
    with mid:
        kind = "SIMULATED" if view == "AC" else "PREDICTED"
        T.panel_title(
            f"Sundon network · {T.SHORT[view]} · {held}",
            *(() if ss.story_on else (kind,)),
            focus=watch == "network",
        )
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
        # grid-state figures (formerly a side column): one line under the network
        stats = (
            f"At {g:%H:%M}: max loading <b>{float(s.at['AC', 'max_loading_pct']):.0f}&nbsp;%</b> AC"
        )
        if view != "AC":
            stats += (
                f" vs <b>{float(s.at[view, 'max_loading_pct']):.0f}&nbsp;%</b> {T.SHORT[view]}"
                f" · power-balance error <b>{float(s.at[view, 'PBE_mean']):.2f} MVA</b>"
            )
        if not ss.story_on:  # the story's caption carries its own numbers
            st.markdown(f'<div class="c2g-pill">{stats}</div>', unsafe_allow_html=True)

    if not ss.story_on:  # player bar: Play sits next to the time it moves
        c_btn, c_sl = st.columns([1, 9], vertical_alignment="bottom")
        with c_btn:
            if st.button(
                "Pause" if ss.playing else "Play",
                icon=":material/pause:" if ss.playing else ":material/play_arrow:",
                width="stretch",
                key="play_btn",
            ):
                if not ss.playing and ss.t_idx >= n - 1:
                    ss.t_idx = 0
                ss.playing = not ss.playing
                st.rerun()  # full rerun: starts or stops the timer
        with c_sl:
            st.select_slider(
                "Time (UTC)",
                options=list(range(n)),
                key="t_idx",
                format_func=lambda k: f"{ev.steps[k]:%H:%M}",
                help="15-minute satellite steps; the grid state is half-hourly and held between.",
            )
    band = S.band(BEATS[ss.beat]) if ss.story_on else None
    T.panel_title(
        "Timeline",
        *(() if ss.story_on else ("DERIVED", "SIMULATED", "PREDICTED")),
        focus=watch == "timeline",
    )
    st.plotly_chart(
        F.timeline(ev.fleet_pv, ev.summary, view, t, g, band=band),
        width="stretch",
        config={"displayModeBar": False},
        key="tl",
    )


stage()

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

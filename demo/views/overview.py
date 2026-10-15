"""Overview: the 30-second version, read top to bottom as question -> what we did (the
fine-tuning steps) -> answer -> one moment that shows the answer -> where to go next. Every
number comes from the frozen bundle, the published S1 coefficients and model_evolution.csv (the
same sources as the story captions). The only derived figures are descriptive quantiles of the
response-aware offset, taken from the frozen per-state imports in pv_response_s1.parquet."""

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
p = T.palette()
sc = S.script()
ev = D.event(sc["event"])
evo = D.evolution()
co = D.catalog()["ols_coefficients_s1"]
a, b = (pd.Timestamp(sc["refs"][k]) for k in ("a", "b"))
v = S._static_vars()
REPO = "https://github.com/hinox13/grid2cloud"
N_STATES = f"{int(evo.at['E5d', 'n']):,}"
ALL_STATES = f"All {N_STATES} real half-hours of 2024"
imp = ev.summary.pivot(index="timestamp_utc", columns="model", values="import_mw")
OK, WARN, BAD = (
    ("#4ade80", "#fbbf24", "#f87171") if p["MODE"] == "dark" else ("#15803d", "#b45309", "#b91c1c")
)

# page-local styling: section eyebrows, answer cards with a verdict chip, inline bar rows
st.markdown(
    f"""
<style>
.ov-eyebrow {{ color: {p["ACCENT_TEXT"]}; font-size: 0.74rem; font-weight: 700;
  letter-spacing: 0.09em; text-transform: uppercase; margin: 26px 0 2px 0; }}
.ov-scope {{ display: inline-block; margin-left: 10px; padding: 1px 9px; border-radius: 999px;
  border: 1px solid {p["BORDER"]}; background: {p["SURFACE"]}; color: {p["INK_2"]};
  font-size: 0.72rem; font-weight: 600; letter-spacing: 0; text-transform: none;
  vertical-align: 1px; }}
.ov-h2 {{ color: {p["INK"]}; font-size: 1.55rem; font-weight: 700; letter-spacing: -0.01em;
  line-height: 1.25; margin: 0 0 12px 0; }}
.ov-lead {{ color: {p["INK"]}; font-size: 1.2rem; line-height: 1.5; max-width: 60rem;
  margin: 10px 0 4px 0; }}
.ov-lead b {{ color: {p["INK"]}; }}
.ov-short {{ color: {p["INK"]}; font-size: 0.98rem; line-height: 1.5; max-width: 60rem;
  border-left: 3px solid {p["ACCENT"]}; padding: 2px 0 2px 12px; margin: 10px 0 2px 0; }}
.ov-sub {{ color: {p["INK_2"]}; font-size: 0.98rem; line-height: 1.5; max-width: 60rem; }}
.ov-answers {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
@media (max-width: 900px) {{ .ov-answers {{ grid-template-columns: 1fr; }} }}
.ov-card {{ background: {p["SURFACE"]}; border: 1px solid {p["BORDER"]}; border-radius: 14px;
  padding: 16px 20px 14px 20px; box-shadow: {p["SHADOW"]}; }}
.ov-chip {{ display: inline-flex; align-items: center; gap: 6px; font-size: 0.74rem;
  font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; border-radius: 999px;
  padding: 2px 10px; border: 1px solid currentColor; }}
.ov-card h4 {{ color: {p["INK"]}; font-size: 1.15rem; font-weight: 700; margin: 10px 0 4px 0;
  padding: 0; }}
.ov-card .why {{ color: {p["INK_2"]}; font-size: 0.9rem; line-height: 1.45; margin-bottom: 12px; }}
.ov-bar {{ display: grid; grid-template-columns: 11.5rem 1fr 6.4rem; align-items: center;
  gap: 10px; margin: 7px 0; font-size: 0.86rem; color: {p["INK_2"]}; }}
.ov-bar .track {{ background: {p["GRID"]}; border-radius: 4px; height: 12px; overflow: hidden; }}
.ov-bar .fill {{ height: 100%; border-radius: 4px; }}
.ov-bar .num {{ color: {p["INK"]}; font-weight: 700; text-align: right;
  font-variant-numeric: tabular-nums; }}
.ov-unit {{ color: {p["MUTED"]}; font-size: 0.76rem; margin-top: 6px; }}
.ov-steps {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 0 0 10px 0; }}
@media (max-width: 900px) {{ .ov-steps {{ grid-template-columns: 1fr; }} }}
.ov-step {{ background: {p["SURFACE"]}; border: 1px solid {p["BORDER"]}; border-radius: 12px;
  padding: 10px 14px; box-shadow: {p["SHADOW"]}; }}
.ov-step .k {{ color: {p["MUTED"]}; font-size: 0.72rem; text-transform: uppercase;
  letter-spacing: 0.06em; }}
.ov-step .v {{ color: {p["INK"]}; font-size: 1.3rem; font-weight: 700;
  font-variant-numeric: tabular-nums; }}
.ov-step .s {{ color: {p["INK_2"]}; font-size: 0.82rem; }}
.ov-ladder {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }}
@media (max-width: 1100px) {{ .ov-ladder {{ grid-template-columns: repeat(2, 1fr); }} }}
@media (max-width: 640px) {{ .ov-ladder {{ grid-template-columns: 1fr; }} }}
.ov-rung {{ background: {p["SURFACE"]}; border: 1px solid {p["BORDER"]}; border-radius: 12px;
  padding: 10px 14px; box-shadow: {p["SHADOW"]}; display: flex; flex-direction: column; }}
.ov-rung .tag {{ color: {p["MUTED"]}; font-size: 0.70rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.07em; }}
.ov-rung .n {{ color: {p["INK"]}; font-weight: 700; font-size: 1.0rem; margin-top: 2px; }}
.ov-rung .a {{ color: {p["INK_2"]}; font-size: 0.80rem; line-height: 1.35; margin-top: 2px;
  min-height: 2.7em; }}
.ov-rung .o {{ color: {p["INK"]}; font-size: 0.84rem; font-weight: 600; line-height: 1.3;
  margin: 8px 0 6px 0; flex-grow: 1; }}
.ov-rung .m {{ display: flex; justify-content: space-between; gap: 8px; font-size: 0.78rem;
  color: {p["INK_2"]}; border-top: 1px solid {p["BORDER"]}; padding: 4px 0 2px 0; }}
.ov-rung .m b {{ color: {p["INK"]}; font-variant-numeric: tabular-nums; }}
.ov-ref {{ color: {p["INK_2"]}; font-size: 0.84rem; margin-top: 8px; }}
.ov-ref b {{ color: {p["INK"]}; }}
.ov-opens {{ display: grid; grid-template-columns: repeat(3, 1fr); background: {p["SURFACE"]};
  border: 1px solid {p["BORDER"]}; border-radius: 12px; box-shadow: {p["SHADOW"]};
  overflow: hidden; margin-top: 6px; }}
@media (max-width: 900px) {{ .ov-opens {{ grid-template-columns: 1fr; }} }}
a.ov-open {{ display: block; padding: 10px 16px; text-decoration: none !important;
  border-left: 1px solid {p["BORDER"]}; transition: background 0.15s; }}
a.ov-open:first-child {{ border-left: 0; }}
@media (max-width: 900px) {{ a.ov-open {{ border-left: 0; border-top: 1px solid {p["BORDER"]}; }}
  a.ov-open:first-child {{ border-top: 0; }} }}
a.ov-open:hover {{ background: {p["HILITE"]}; }}
.ov-open .n {{ color: {p["INK"]}; font-size: 0.95rem; font-weight: 700; }}
.ov-open .ext {{ color: {p["ACCENT_TEXT"]}; margin-left: 4px; }}
.ov-open .d {{ color: {p["INK_2"]}; font-size: 0.8rem; line-height: 1.4; margin-top: 2px; }}
.ov-open code {{ font-size: 0.74rem; padding: 0 4px; border-radius: 4px; background: {p["PAGE_2"]};
  color: {p["INK"]}; }}
.ov-frame-cap {{ color: {p["INK_2"]}; font-size: 0.85rem; margin: 2px 0 4px 0; }}
.ov-frame-cap b {{ color: {p["INK"]}; }}
[class*="st-key-ovnext"] {{ background: {p["SURFACE"]}; border: 1px solid {p["BORDER"]} !important;
  border-radius: 14px; box-shadow: {p["SHADOW"]}; padding: 4px 6px 18px 6px; }}
[class*="st-key-ovnext"]:hover {{ border-color: {p["ACCENT"]} !important; }}
[class*="st-key-ovnext"] [data-testid="stPageLink-NavLink"] span {{ color: {p["INK"]} !important;
  font-weight: 700; font-size: 1.0rem; }}
[class*="st-key-ovnext"] [data-testid="stIconMaterial"] {{ color: {p["ACCENT_TEXT"]} !important; }}
</style>
""",
    unsafe_allow_html=True,
)


def eyebrow(label: str, title: str, scope: str = "") -> None:
    """Section label + heading; `scope` says which data the section's numbers cover."""
    tag = f'<span class="ov-scope">{scope}</span>' if scope else ""
    st.markdown(
        f'<div class="ov-eyebrow">{label}{tag}</div><div class="ov-h2">{title}</div>',
        unsafe_allow_html=True,
    )


def bar(label: str, value: float, scale: float, colour: str, text: str) -> str:
    w = min(abs(value) / scale, 1.0) * 100
    return (
        f'<div class="ov-bar"><span>{label}</span><div class="track">'
        f'<div class="fill" style="width:{w:.1f}%;background:{colour}"></div></div>'
        f'<span class="num">{text}</span></div>'
    )


def start_tour() -> None:
    ss.update(story_on=True, story_paused=False, beat=0, beat_age=-1, playing=False)
    st.switch_page("views/explorer.py")


# ---------------------------------------------------------------- 1. hero: the question
h_left, h_right = st.columns([7, 1], vertical_alignment="top")
with h_left:
    st.markdown(
        '<div class="c2g-hero"><div class="c2g-hero-title">'
        'Cloud<span class="c2g-two">2</span>Grid</div>'
        '<div class="c2g-hero-tag">Testing a grid foundation model against real '
        "satellite-driven renewable variability.</div></div>"
        '<div class="ov-lead">When clouds pass over a real distribution network, can '
        "<b>GENCO</b>, an AI model trained only on synthetic grids, predict how the grid "
        "responds?</div>"
        '<div class="ov-sub">We rebuilt the Sundon network (UK Power Networks) and drove it with '
        "solar output estimated from Meteosat imagery. Out of the box GENCO could not read this "
        "grid at all, so we <b>fine-tuned it in four steps</b>, always on synthetic states only, "
        "and checked every version against a full physics simulation (AC power flow) on the real "
        "half-hours of 2024.</div>"
        '<div class="ov-short"><b>Short answer:</b> after fine-tuning, GENCO learned how the grid '
        "responds to solar, but the overall level it predicts is still off.</div>"
        '<div style="height:10px"></div>',
        unsafe_allow_html=True,
    )
with h_right:
    T.theme_toggle()

c1, c2, _ = st.columns([1.25, 1, 2.4])
if c1.button(
    "Take the guided tour", icon=":material/play_circle:", type="primary", width="stretch"
):
    start_tour()
if c2.button("Explore freely", icon=":material/satellite_alt:", width="stretch"):
    st.switch_page("views/explorer.py")

ac_pv, e5c_pv, e5d_pv = co["AC"]["pv"], co["E5c"]["pv"], co["E5d"]["pv"]
# ---------------------------------------------------------------- 2. what we did: fine-tuning
ac_imp = float(evo.at["E5d", "ac_import_mean_mw"])
zs_imp = float(evo.at["zero_shot", "genco_import_mean_mw"])
zs_wrong = 1 - float(evo.at["zero_shot", "import_sign_accuracy"])
eyebrow(
    "What we did",
    "We started from a model that could not read this grid, and fine-tuned it in four steps",
    ALL_STATES,
)
OUTCOME = {m: o for m, _, o in T.LADDER}
STEPS = [
    ("zero_shot", "Start", "As published, never trained on this grid"),
    ("E5", "Step 1", "Fine-tuned on synthetic states of the Sundon network"),
    ("E5b", "Step 2", "Synthetic states spanning the real operating range"),
    ("E5c", "Step 3", "Solar farms modelled as explicit generators"),
    ("E5d", "Step 4", "New loss: match how the grid responds to solar, battery and load"),
]
rungs = []
for m, tag, what in STEPS:
    gi = float(evo.at[m, "genco_import_mean_mw"])
    off = float(evo.at[m, "import_bias_mw"])  # = gi - physics; "import bias" on the story page
    imp_col = BAD if m in ("zero_shot", "E5") else p["INK"]
    if m == "E5":  # its PV slope is not a usable response (import r 0.11), as on Model evolution
        pv_txt, pv_col = "not usable", BAD
    else:
        pv = float(evo.at[m, "genco_slope_pv"])
        pv_txt, pv_col = f"{pv:+.2f}", (OK if m == "E5d" else p["INK"])
    name = "Original GENCO" if m == "zero_shot" else T.NAMES[m]
    rungs.append(
        f'<div class="ov-rung" style="border-top:4px solid {T.colour(m)}">'
        f'<div class="tag">{tag}</div><div class="n">{name}</div><div class="a">{what}</div>'
        f'<div class="o">{OUTCOME[m]}</div>'
        f'<div class="m"><span>Power drawn from grid</span>'
        f'<b style="color:{imp_col}">{gi:+.0f} MW ({off:+.0f})</b></div>'
        f'<div class="m"><span>Solar response</span><b style="color:{pv_col}">{pv_txt}</b></div>'
        "</div>"
    )
st.markdown(
    f'<div class="ov-ladder">{"".join(rungs)}</div>'
    f'<div class="ov-ref">Physics reference: Sundon draws about <b>{ac_imp:.0f} MW</b> from the '
    f"national grid on average, and its solar response is <b>{ac_pv:+.2f}</b>. The original "
    f"GENCO predicted <b>{zs_imp:+.0f} MW</b>, meaning Sundon would be sending power out: the "
    f"wrong direction in {zs_wrong * 100:.1f}&nbsp;% of real states. In brackets: the offset "
    f"from the physics value of {ac_imp:.0f} MW, shown as the import bias on the Scientific "
    "story page.</div>"
    + '<div class="c2g-note">Power drawn from the grid (grid import) is the average power '
    "Sundon takes from the national transmission grid at its grid supply point; a negative value "
    "means power flowing out. Every version is evaluated on the same held-out real states and "
    "trained only on synthetic ones. Full metrics per step are on the Model evolution page."
    "</div>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------- 3. the answer
eyebrow("The answer", "Half yes: it learned the response, but not the level", ALL_STATES)
ac_mean = float(evo.at["E5d", "ac_import_mean_mw"])
e5d_mean = float(evo.at["E5d", "genco_import_mean_mw"])
e5c_mean = float(evo.at["E5c", "genco_import_mean_mw"])
e5c_off, e5d_off = (float(evo.at[m, "import_bias_mw"]) for m in ("E5c", "E5d"))
# how constant step 4's offset is: per-state GENCO minus AC import over the same held-out states
_s1 = D.pv_response()
_e5d_err = _s1["import_E5d"] - _s1["import_AC"]
e5d_q25, e5d_q75 = (float(_e5d_err.quantile(q)) for q in (0.25, 0.75))
e5d_pos = float((_e5d_err > 0).mean())
scale_pv = max(abs(ac_pv), abs(e5d_pv), abs(e5c_pv)) * 1.08
scale_mw = max(ac_mean, e5c_mean, e5d_mean) * 1.08
learned = (
    '<div class="ov-card">'
    f'<span class="ov-chip" style="color:{OK}">✓ Learned</span>'
    "<h4>It reacts to sunshine like the physics does</h4>"
    '<div class="why">For every extra MW of solar, Sundon draws about 1 MW less from the grid. '
    "The first three fine-tuned versions barely noticed solar. Step 4, which trains GENCO on "
    "how the grid "
    "<i>responds</i>, fixed that.</div>"
    + bar("Physics (AC reference)", ac_pv, scale_pv, T.AC, f"{ac_pv:+.2f}")
    + bar("Step 3: Generator-aware", e5c_pv, scale_pv, T.colour("E5c"), f"{e5c_pv:+.2f}")
    + bar("Step 4: Response-aware", e5d_pv, scale_pv, T.colour("E5d"), f"{e5d_pv:+.2f}")
    + '<div class="ov-unit">MW change in power drawn from the grid, per MW of solar, '
    f"fitted over all {N_STATES} real half-hours</div></div>"
)
offset = (
    '<div class="ov-card">'
    f'<span class="ov-chip" style="color:{WARN}">! Not yet calibrated</span>'
    "<h4>But neither gets the level right</h4>"
    '<div class="why">Both versions predict Sundon draws more power than the physics says. '
    f"Step 4 learned the solar response, but its offset grew from {e5c_off:+.0f} to "
    f"{e5d_off:+.0f} MW, so the transfer verdict is only partial. The step 4 offset is almost "
    f"constant: between {e5d_q25:+.0f} and {e5d_q75:+.0f} MW in half of all states, and too "
    f"high in {e5d_pos * 100:.0f}&nbsp;% of them. The 15 June example below is typical.</div>"
    + bar("Physics (AC reference)", ac_mean, scale_mw, T.AC, f"{ac_mean:.0f} MW")
    + bar(
        "Step 3: Generator-aware",
        e5c_mean,
        scale_mw,
        T.colour("E5c"),
        f"{e5c_mean:.0f} MW ({e5c_off:+.0f})",
    )
    + bar(
        "Step 4: Response-aware",
        e5d_mean,
        scale_mw,
        T.colour("E5d"),
        f"{e5d_mean:.0f} MW ({e5d_off:+.0f})",
    )
    + f'<div class="ov-unit">Average power drawn from the grid over all {N_STATES} real '
    "half-hours</div></div>"
)
st.markdown(f'<div class="ov-answers">{learned}{offset}</div>', unsafe_allow_html=True)
st.markdown(
    f'<div class="c2g-note" style="margin-top:8px">Both cards cover the same {N_STATES} '
    "held-out half-hourly 2024 states. Sensitivities are slopes from the published regression "
    "of power drawn from the grid on solar, load and battery. The physics values are simulated "
    "references, not measurements.</div>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------- 4. one moment that shows it
eyebrow(
    "See it happen",
    "A cloud field clears: GENCO follows the drop, but stays above it",
    f"One example: 15 June 2024, {a:%H:%M} to {b:%H:%M} UTC",
)
ac_a, ac_b, md_a, md_b = imp.at[a, "AC"], imp.at[b, "AC"], imp.at[a, "E5d"], imp.at[b, "E5d"]
st.markdown(
    '<div class="ov-steps">'
    f'<div class="ov-step" style="border-top:3px solid {T.PV}">'
    '<div class="k">1 · Sun comes out</div>'
    f'<div class="v">{v["hv_a"]} → {v["hv_b"]} MW</div>'
    '<div class="s">solar injected into the grid</div></div>'
    f'<div class="ov-step" style="border-top:3px solid {T.AC}">'
    '<div class="k">2 · Physics responds</div>'
    f'<div class="v">{ac_a:.0f} → {ac_b:.0f} MW</div>'
    '<div class="s">power drawn from the grid, physics</div></div>'
    f'<div class="ov-step" style="border-top:3px solid {T.colour("E5d")}">'
    '<div class="k">3 · GENCO responds</div>'
    f'<div class="v">{md_a:.0f} → {md_b:.0f} MW</div>'
    f'<div class="s">a similar drop, about {md_b - ac_b:.0f} MW higher: its usual offset</div>'
    "</div></div>",
    unsafe_allow_html=True,
)
st.markdown(
    f'<div class="ov-ref" style="margin:-2px 0 12px 0">Read each arrow as <b>{a:%H:%M} UTC '
    f"→ {b:%H:%M} UTC</b>: the two half-hourly grid states either side of the clearing. Solar "
    f"rose by {v['dhv'].lstrip('+')} MW and the physics says Sundon's draw from the grid fell by "
    f"{ac_a - ac_b:.0f} MW. Solar accounts for only about {v['ac_pv_term'].lstrip('-')} MW of "
    "that fall (the published 1 MW per MW of solar); load and the battery changed at the same "
    f"time. GENCO predicts a fall of {md_a - md_b:.0f} MW and stays "
    f"{min(md_a - ac_a, md_b - ac_b):.0f} to {max(md_a - ac_a, md_b - ac_b):.0f} MW above the "
    "physics at both times.</div>",
    unsafe_allow_html=True,
)
c_sat, c_tl = st.columns([0.78, 2.3], gap="medium")
with c_sat:
    for t, note in ((a, "cloud over the study area"), (b, "the field has cleared")):
        frame = ev.frames[ev.frames.timestamp_utc == t].iloc[0]
        pv_now = ev.pv_generation[ev.pv_generation.timestamp_utc == t]
        st.markdown(
            f'<div class="ov-frame-cap"><b>{t:%H:%M} UTC</b> · {note}</div>',
            unsafe_allow_html=True,
        )
        st.html(SAT.render(frame, None, ev.nodes, ev.edges, ev.assets, pv_now, True))
    st.markdown(
        '<div class="c2g-note">Meteosat E-View, observed. Dashed box: Sundon study area.</div>',
        unsafe_allow_html=True,
    )
with c_tl:
    st.plotly_chart(
        F.timeline(ev.fleet_pv, ev.summary, "E5d", b, b, band=(a, b, "cloud field clears")),
        width="stretch",
        config={"displayModeBar": False},
        key="ov_tl",
    )

# ---------------------------------------------------------------- 5. where to go next
eyebrow("Go deeper", "Pick your route")
NEXT = [
    ("views/explorer.py", "Demo", ":material/satellite_alt:",
     "Scrub through three weather events: satellite, network and every model."),
    ("views/story.py", "Scientific story", ":material/explore:",
     "The full argument, from zero-shot failure to the response-aware loss."),
    ("views/pv_response.py", "PV response", ":material/wb_sunny:",
     "Where the sensitivity numbers above come from, state by state."),
    ("views/evolution.py", "Model evolution", ":material/trending_up:",
     "Each training step, what it fixed and what it left broken."),
]  # fmt: skip
for col, (page, label, icon, desc) in zip(st.columns(len(NEXT)), NEXT, strict=True):
    with col, st.container(border=True, height="stretch", key=f"ovnext{page[6:-3]}"):
        st.page_link(page, label=label, icon=icon)
        st.markdown(f'<div class="ov-sub" style="font-size:0.86rem">{desc}</div>',
                    unsafe_allow_html=True)  # fmt: skip
# ---------------------------------------------------------------- 6. open and reproducible
st.markdown('<div class="ov-eyebrow">Open and reproducible</div>', unsafe_allow_html=True)
OPEN = [
    (REPO, "Source code", "Pipeline, pre-registrations and this demo. Apache-2.0."),
    (f"{REPO}/releases/tag/cloud2grid-models-v1", "Frozen models",
     "Generator-aware and response-aware checkpoints, SHA256 hashes, synthetic test data."),
    (f"{REPO}/blob/cloud2grid-models-v1/reproduce/README.md", "Verify the models",
     "<code>uv sync --extra genco</code>, then "
     "<code>uv run python reproduce/verify_models.py</code>. CPU, about 2 to 3 minutes."),
]  # fmt: skip
cards = "".join(
    f'<a class="ov-open" href="{url}" target="_blank" rel="noopener">'
    f'<div class="n">{title}<span class="ext">↗</span></div><div class="d">{desc}</div></a>'
    for url, title, desc in OPEN
)
st.markdown(f'<div class="ov-opens">{cards}</div>', unsafe_allow_html=True)
T.footer()

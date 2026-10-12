"""Colours, labels and shared Streamlit styling for the Cloud2Grid Explorer.

Two palettes, chosen per session (header "Dark" toggle; light is the default):
  LIGHT  "daylight sky": white cards on a pale warm-to-blue gradient, dataviz LIGHT-mode series
         steps. E5 (2.7:1) and E5b (2.8:1) sit below 3:1 on white, so their charts always carry
         legends / direct labels / a table (relief rule). PV uses the deeper amber (3.1:1).
  DARK   "night sky": navy surfaces, dataviz DARK-mode series steps (every series >= 4.4:1).
Each model keeps ONE hue family in both modes (colour follows the entity). E5d (response-aware)
is a plum (OKLCH h 340: light #751e5f, dark #e39ecc), chosen by search as the hue that stays
furthest from every other series and PV / battery in both modes (worst simulated-CVD ΔE 11.7,
normal-vision ΔE >= 15). Model identity is never colour alone: every chart names its series.

Tokens are read as module attributes (T.SURFACE, T.INK, T.MODEL_COLOURS, ...) through a module
__getattr__ that looks up the CURRENT SESSION's palette, so concurrent viewers can use different
modes safely (no shared global is mutated)."""

from __future__ import annotations

import streamlit as st

_COMMON = {
    "ACCENT": "#f5a524",  # brand / UI accent ("sun"); never a model colour
    "ACCENT_INK": "#1a1205",  # text on ACCENT (9.1:1)
}
LIGHT = {
    **_COMMON,
    "MODE": "light",
    "SURFACE": "#ffffff",
    "PAGE": "#f5f7fb",
    "PAGE_2": "#eef3f9",
    "INK": "#0f172a",
    "INK_2": "#3b4659",
    "MUTED": "#5f6b84",
    "GRID": "#e7ecf3",
    "AXIS": "#c9d2df",
    "BORDER": "rgba(15,23,42,0.10)",
    "SHADOW": "0 8px 24px rgba(15,23,42,0.08)",
    "ACCENT_TEXT": "#b45309",  # amber used as text on white (5.0:1)
    "GLOW": "rgba(245,165,36,0.20)",
    "GLOW_2": "rgba(57,135,229,0.12)",
    "HEADER_BG": "rgba(248,250,253,0.82)",
    "BATTERY": "#4a3aa7",
    "PV": "#c98500",
    "MODEL_COLOURS": {
        "zero_shot": "#eb6834",
        "E5": "#e87ba4",
        "E5b": "#1baf7a",
        "E5c": "#2a78d6",
        "E5d": "#751e5f",
    },
    "LOADING_SCALE": [[0.0, "#f1e4cc"], [0.5, "#e09b2d"], [1.0, "#9a5800"]],
    "DIVERGING": [[0.0, "#2a78d6"], [0.5, "#d9dde5"], [1.0, "#e34948"]],
    "ARROW": "rgba(15,23,42,0.45)",
    "BAND_FILL": "rgba(15,23,42,0.035)",
    "HILITE": "rgba(15,23,42,0.07)",
    "HOVER_BG": "#ffffff",
    "BUSBAR": "#3b4659",
}
DARK = {
    **_COMMON,
    "MODE": "dark",
    "SURFACE": "#111a2b",
    "PAGE": "#070b14",
    "PAGE_2": "#0b1424",
    "INK": "#f4f6fb",
    "INK_2": "#b7c0d4",
    "MUTED": "#7f8aa3",
    "GRID": "#1c2740",
    "AXIS": "#2a3854",
    "BORDER": "rgba(148,180,255,0.12)",
    "SHADOW": "0 10px 28px rgba(0,0,0,0.32)",
    "ACCENT_TEXT": "#f5a524",
    "GLOW": "rgba(245,165,36,0.16)",
    "GLOW_2": "rgba(57,135,229,0.10)",
    "HEADER_BG": "rgba(7,11,20,0.72)",
    "BATTERY": "#9085e9",
    "PV": "#c98500",
    "MODEL_COLOURS": {
        "zero_shot": "#d95926",
        "E5": "#d55181",
        "E5b": "#199e70",
        "E5c": "#3987e5",
        "E5d": "#e39ecc",
    },
    "LOADING_SCALE": [[0.0, "#3a2c12"], [0.5, "#8a5a12"], [1.0, "#f5a524"]],
    "DIVERGING": [[0.0, "#3987e5"], [0.5, "#4b5163"], [1.0, "#e66767"]],
    "ARROW": "rgba(255,255,255,0.55)",
    "BAND_FILL": "rgba(255,255,255,0.035)",
    "HILITE": "rgba(255,255,255,0.10)",
    "HOVER_BG": "#16213a",
    "BUSBAR": "#b7c0d4",
}


def is_dark() -> bool:
    try:
        if "_dark" not in st.session_state:  # first run of a session: honour ?theme=dark
            st.session_state["_dark"] = st.query_params.get("theme") == "dark"
        return bool(st.session_state["_dark"])
    except Exception:  # outside a Streamlit session (tests, scripts): light
        return False


def palette() -> dict:
    return DARK if is_dark() else LIGHT


def __getattr__(name: str) -> object:  # PEP 562: per-session tokens, e.g. T.SURFACE
    p = palette()
    if name == "AC":  # the physical reference is drawn in primary ink, not a series hue
        return p["INK"]
    if name in p:
        return p[name]
    raise AttributeError(name)


# Display names: descriptive titles for visitors; the experiment code (E4, E5, ...) stays as a
# small tag so every number can be traced to its report. Rename here only.
NAMES = {
    "AC": "AC reference",
    "zero_shot": "Off-the-shelf",
    "E5": "Grid-tuned",
    "E5b": "Envelope-tuned",
    "E5c": "Generator-aware",
    "E5d": "Response-aware",
}
EXP = {"AC": "", "zero_shot": "E4", "E5": "E5", "E5b": "E5b", "E5c": "E5c", "E5d": "E5d"}
ABOUT = {
    "AC": "physics reference: full AC power flow on the reconstructed network",
    "zero_shot": "GENCO as published, never trained on this grid",
    "E5": "fine-tuned on standard synthetic states of the Sundon network",
    "E5b": "fine-tuned on synthetic states spanning the real operating range (public metadata)",
    "E5c": "envelope-tuned, with PV represented as explicit generators",
    "E5d": "generator-aware, also trained to match AC responses on paired synthetic states",
}
# one-line summaries of the frozen, pre-registered verdicts (Model evolution page has the detail)
VERDICT = {
    "AC": "the ground truth GENCO is compared against",
    "zero_shot": "fails: cannot transfer to a new grid",
    "E5": "fits synthetic states, poor on real operation",
    "E5b": "real-state error −99 %; import and voltage still off",
    "E5c": "better load and battery tracking; PV response ≈ 0",
    "E5d": "PV response learned and transferred; import ~13 MW high (partial)",
}
SHORT = {k: ("AC" if k == "AC" else v) for k, v in NAMES.items()}
LABELS = {k: (v if k == "AC" else f"{v} GENCO") for k, v in NAMES.items()}


def exp_tag(model: str) -> str:
    """Small grey experiment-code tag (empty for AC)."""
    return f'<span class="c2g-exp">{EXP[model]}</span>' if EXP.get(model) else ""


def named(model: str) -> str:
    """'Generator-aware <E5c>' as HTML."""
    return f"{NAMES[model]} {exp_tag(model)}"


PROVENANCE = {
    "OBSERVED": "Observed",
    "DERIVED": "Derived",
    "SIMULATED": "Simulated",
    "PREDICTED": "Predicted",
}


def colour(model: str) -> str:
    p = palette()
    return p["INK"] if model == "AC" else p["MODEL_COLOURS"][model]


def plotly_layout(**kw: object) -> dict:
    p = palette()
    SURFACE, INK, INK_2, AXIS = p["SURFACE"], p["INK"], p["INK_2"], p["AXIS"]  # noqa: N806
    base = dict(
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', color=INK_2, size=12),
        margin=dict(l=8, r=8, t=36, b=8),
        hoverlabel=dict(bgcolor=p["HOVER_BG"], bordercolor=AXIS, font=dict(color=INK)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(color=INK_2)),
    )
    base.update(kw)
    return base


def axis(**kw: object) -> dict:
    p = palette()
    a = dict(
        gridcolor=p["GRID"],
        zerolinecolor=p["AXIS"],
        linecolor=p["AXIS"],
        tickfont=dict(color=p["MUTED"]),
    )
    a.update(kw)
    return a


def css(p: dict) -> str:
    """Global stylesheet for palette p (plus native-widget overrides in dark mode)."""
    PAGE, PAGE_2, SURFACE, INK, INK_2, MUTED, AXIS = (  # noqa: N806
        p[k] for k in ("PAGE", "PAGE_2", "SURFACE", "INK", "INK_2", "MUTED", "AXIS")
    )
    BORDER, SHADOW, ACCENT, ACCENT_INK, ACCENT_TEXT = (  # noqa: N806
        p[k] for k in ("BORDER", "SHADOW", "ACCENT", "ACCENT_INK", "ACCENT_TEXT")
    )
    GLOW, GLOW_2, HEADER_BG, PV, BUSBAR = (  # noqa: N806
        p[k] for k in ("GLOW", "GLOW_2", "HEADER_BG", "PV", "BUSBAR")
    )
    LS0, LS1, LS2 = (c for _, c in p["LOADING_SCALE"])  # noqa: N806
    DV0, DV1, DV2 = (c for _, c in p["DIVERGING"])  # noqa: N806
    base = f"""
<style>
.stApp {{
  background:
    radial-gradient(1100px 520px at 12% -8%, {GLOW}, transparent 62%),
    radial-gradient(900px 600px at 95% 0%, {GLOW_2}, transparent 60%),
    linear-gradient(180deg, {PAGE} 0%, {PAGE_2} 100%);
  background-attachment: fixed;
}}
[data-testid="stHeader"] {{ background: {HEADER_BG}; backdrop-filter: blur(8px);
  border-bottom: 1px solid {BORDER}; }}
[data-testid="stPlotlyChart"] {{ border-radius: 12px; overflow: hidden; border: 1px solid {BORDER};
  box-shadow: {SHADOW}; }}
[data-testid="stBaseButton-primary"] {{ background: linear-gradient(180deg, #ffb83d, {ACCENT});
  color: {ACCENT_INK}; border: 0; font-weight: 600; box-shadow: 0 6px 20px rgba(245,165,36,0.28); }}
[data-testid="stBaseButton-primary"]:hover {{ background: #ffc24f; color: {ACCENT_INK}; }}
[data-testid="stBaseButton-primary"] * {{ color: {ACCENT_INK} !important; }}
[data-testid="stBaseButton-secondary"] {{ background: {SURFACE}; color: {INK};
  border: 1px solid {BORDER}; }}
.block-container {{ padding-top: 3.6rem; padding-bottom: 2rem; max-width: 1500px; }}
h1, h2, h3 {{ letter-spacing: -0.01em; }}
.c2g-sub {{ color: {INK_2}; font-size: 1.02rem; margin-top: -0.6rem; }}
.c2g-badge {{ display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 0.72rem;
  border: 1px solid {BORDER}; color: {INK_2}; margin-right: 6px;
  text-transform: uppercase; letter-spacing: 0.04em; }}
.c2g-panel-title {{ color: {INK}; font-weight: 600; font-size: 0.95rem; margin: 0 0 2px 0; }}
.c2g-chain {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: stretch;
  margin: 2px 0 8px 0; }}
.c2g-chip {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px;
  padding: 6px 12px; min-width: 120px; }}
.c2g-chip .k {{ color: {MUTED}; font-size: 0.70rem; text-transform: uppercase;
  letter-spacing: 0.05em; }}
.c2g-chip .v {{ color: {INK}; font-size: 1.15rem; font-weight: 600; }}
.c2g-chip .s {{ color: {INK_2}; font-size: 0.75rem; }}
.c2g-arrow {{ color: {MUTED}; align-self: center; font-size: 1.1rem; }}
.c2g-note {{ color: {MUTED}; font-size: 0.78rem; }}
.c2g-callout {{ border-left: 3px solid {INK_2}; padding: 8px 14px; background: {SURFACE};
  border-radius: 0 8px 8px 0; color: {INK}; margin: 6px 0 12px 0; }}
.c2g-tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 10px; margin: 4px 0 6px 0; }}
.c2g-tile {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
  padding: 12px 16px; }}
.c2g-tile .k {{ color: {INK_2}; font-size: 0.80rem; }}
.c2g-tile .v {{ color: {INK}; font-size: 2.0rem; font-weight: 600; line-height: 1.2; }}
.c2g-tile .s {{ color: {MUTED}; font-size: 0.80rem; }}
.c2g-hero-title {{ color: {INK}; font-size: 2.4rem; font-weight: 700; letter-spacing: -0.02em;
  line-height: 1.1; }}
.c2g-hero-tag {{ color: {INK_2}; font-size: 1.08rem; margin-top: 2px; }}
.c2g-story {{ background: {SURFACE}; border: 1px solid {BORDER};
  border-left: 4px solid {ACCENT}; border-radius: 0 12px 12px 0; padding: 12px 18px;
  margin: 4px 0 8px 0; min-height: 104px; }}
.c2g-story-head {{ display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }}
.c2g-story-step {{ color: {MUTED}; font-size: 0.8rem; margin-left: 6px; }}
.c2g-story-title {{ color: {INK}; font-weight: 700; font-size: 1.15rem; margin-left: 8px; }}
.c2g-story-cap {{ color: {INK}; font-size: 1.05rem; line-height: 1.5; }}
.c2g-dot {{ width: 9px; height: 9px; border-radius: 50%; background: {AXIS};
  display: inline-block; }}
.c2g-dot.on {{ background: {ACCENT}; }}
.c2g-focus {{ color: {ACCENT_TEXT} !important; }}
.c2g-watch {{ color: {ACCENT_TEXT}; font-size: 0.72rem; margin-left: 8px; text-transform: uppercase;
  letter-spacing: 0.06em; }}
.c2g-faceoff {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; position: relative;
  margin: 6px 0 4px 0; }}
.c2g-face {{ background: {SURFACE}; border-radius: 12px; padding: 14px 20px;
  border: 1px solid {BORDER}; }}
.c2g-face .k {{ color: {INK_2}; font-size: 0.95rem; }}
.c2g-face .v {{ color: {INK}; font-size: 3.2rem; font-weight: 700; line-height: 1.15; }}
.c2g-face .s {{ color: {MUTED}; font-size: 0.9rem; }}
.c2g-vs {{ position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
  background: {PAGE}; color: {MUTED}; border-radius: 999px; padding: 4px 10px;
  font-size: 0.8rem; text-transform: uppercase; }}
@media (max-width: 700px) {{ .c2g-faceoff {{ grid-template-columns: 1fr; }}
  .c2g-vs {{ display: none; }} }}
.c2g-sat {{ position: relative; width: 100%; overflow: hidden; border-radius: 10px;
  background: #000; }}
.c2g-sat-inner {{ position: absolute; inset: 0; }}
.c2g-sat-img, .c2g-sat-svg {{ position: absolute; inset: 0; width: 100%; height: 100%;
  display: block; }}
.c2g-sat-svg {{ overflow: visible; }}
.c2g-sat-stamp {{ position: absolute; right: 8px; bottom: 6px; background: rgba(7,11,20,0.72);
  color: #ffffff; padding: 2px 8px; border-radius: 6px; font-size: 0.8rem; }}
@keyframes c2gfade {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
.c2g-pill {{ color: {INK_2}; font-size: 0.78rem; margin-top: 4px; line-height: 1.45; }}
.c2g-pill b {{ color: {INK}; }}
.c2g-exp {{ display: inline-block; font-size: 0.68rem; color: {MUTED}; border: 1px solid {BORDER};
  border-radius: 4px; padding: 0 4px; margin-left: 2px; vertical-align: 1px; font-weight: 500; }}
.c2g-models {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px; margin: 6px 0 12px 0; }}
.c2g-model {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
  padding: 10px 14px; box-shadow: {SHADOW}; }}
.c2g-model .n {{ color: {INK}; font-weight: 700; font-size: 1.0rem; }}
.c2g-model .a {{ color: {INK_2}; font-size: 0.82rem; margin-top: 2px; }}
.c2g-model .v {{ color: {MUTED}; font-size: 0.8rem; margin-top: 6px; }}
.c2g-legend {{ display: flex; flex-wrap: wrap; gap: 6px 16px; color: {MUTED}; font-size: 0.76rem;
  margin-top: 2px; align-items: center; }}
.c2g-legend > span {{ display: inline-flex; align-items: center; gap: 5px; }}
.c2g-lg-line {{ display: inline-block; width: 16px; background: {LS1}; border-radius: 2px; }}
.c2g-lg-line.thin {{ height: 2px; }} .c2g-lg-line.thick {{ height: 6px; }}
.c2g-lg-grad {{ display: inline-block; width: 46px; height: 6px; border-radius: 3px;
  background: linear-gradient(90deg, {LS0}, {LS1}, {LS2}); }}
.c2g-lg-grad.err {{ background: linear-gradient(90deg, {DV0}, {DV1}, {DV2}); }}
.c2g-lg-dot {{ display: inline-block; width: 9px; height: 9px; border-radius: 50%; }}
.c2g-lg-dot.sq {{ border-radius: 2px; }}
.c2g-lg-bar {{ display: inline-block; width: 18px; height: 4px; background: {BUSBAR};
  border-radius: 1px; }}
.c2g-chip, .c2g-tile, .c2g-face, .c2g-story, .c2g-callout {{
  box-shadow: {SHADOW}; backdrop-filter: blur(6px); }}
.c2g-two {{ color: {ACCENT_TEXT}; }}
.c2g-table-wrap {{ overflow-x: auto; border: 1px solid {BORDER}; border-radius: 12px;
  background: {SURFACE}; box-shadow: {SHADOW}; margin: 4px 0 8px 0; }}
.c2g-table {{ border-collapse: collapse; width: 100%; font-size: 0.86rem; }}
.c2g-table th {{ text-align: left; color: {MUTED}; font-weight: 600; padding: 8px 12px;
  border-bottom: 1px solid {BORDER}; white-space: nowrap; }}
.c2g-table td {{ color: {INK}; padding: 7px 12px; border-bottom: 1px solid {BORDER};
  font-variant-numeric: tabular-nums; }}
.c2g-table tr:last-child td {{ border-bottom: 0; }}
.c2g-ladder {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 10px; margin: 6px 0 4px 0; }}
.c2g-step {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
  padding: 10px 14px; box-shadow: {SHADOW}; }}
.c2g-step .n {{ color: {INK}; font-weight: 700; font-size: 0.95rem; }}
.c2g-step .a {{ color: {MUTED}; font-size: 0.80rem; margin-top: 2px; }}
.c2g-step .o {{ color: {INK}; font-size: 0.92rem; font-weight: 600; margin: 6px 0 8px 0;
  min-height: 2.6em; line-height: 1.3; }}
.c2g-step .m {{ display: flex; justify-content: space-between; gap: 8px; font-size: 0.78rem;
  color: {INK_2}; border-top: 1px solid {BORDER}; padding: 3px 0; }}
.c2g-step .m b {{ color: {INK}; font-variant-numeric: tabular-nums; }}
.c2g-step .x {{ color: {MUTED}; font-size: 0.72rem; }}
.c2g-swatch {{ display:inline-block; width:10px; height:10px; border-radius:2px;
  margin-right:6px; vertical-align:middle; }}
</style>
"""
    if p["MODE"] != "dark":
        return base
    # base Streamlit theme is light (config.toml): restyle the native widgets for dark mode
    return (
        base
        + f"""
<style>
.stApp, .stApp p, .stApp li, .stApp label, .stApp h1, .stApp h2, .stApp h3, .stApp h4,
.stApp td, .stApp th, [data-testid="stMarkdownContainer"] {{ color: {INK}; }}
[data-testid="stWidgetLabel"] p, [data-testid="stCaptionContainer"] {{ color: {INK_2}; }}
[data-baseweb="select"] > div {{ background: {SURFACE} !important;
  border-color: {BORDER} !important; color: {INK} !important; }}
[data-baseweb="select"] svg {{ fill: {INK_2}; }}
[data-testid="stSelectbox"] [role="group"] {{ background: {SURFACE} !important;
  border-color: {BORDER} !important; }}
[data-testid="stSelectbox"] [role="group"] * {{ color: {INK} !important; }}
[data-testid="stSelectbox"] svg {{ fill: {INK_2} !important; color: {INK_2} !important; }}
[data-testid="stCheckbox"] label:has(input[role="switch"]:not(:checked)) > div:nth-child(2) {{
  background-color: rgba(255,255,255,0.22) !important; }}
[data-testid="stTooltipIcon"] svg, [data-testid="stTooltipHoverTarget"] svg {{
  color: {INK_2} !important; stroke: {INK_2}; }}
[data-baseweb="popover"] ul, [data-baseweb="popover"] li {{ background: {SURFACE}; color: {INK}; }}
[data-testid="stButtonGroup"] button {{ background: {SURFACE}; color: {INK_2};
  border-color: {BORDER}; }}
[data-testid="stButtonGroup"] button[aria-checked="true"] {{ color: {ACCENT};
  border-color: {ACCENT}; }}
[data-testid="stExpander"] details {{ background: {SURFACE}; border-color: {BORDER}; }}
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary * {{ color: {INK}; }}
[data-testid="stMetricValue"], [data-testid="stMetricLabel"] * {{ color: {INK}; }}
[data-testid="stSliderTickBarMin"], [data-testid="stSliderTickBarMax"],
[data-testid="stSliderThumbValue"] {{ color: {INK_2}; }}
[data-testid="stHeader"] a, [data-testid="stHeader"] span, [data-testid="stHeader"] button,
[data-testid="stHeader"] svg {{ color: {INK_2}; fill: {INK_2}; }}
.stApp code {{ background: {SURFACE}; color: {INK}; }}
.stApp a {{ color: #8ab4ff; }}
.stApp table th, .stApp table td {{ border-color: {BORDER} !important; }}
</style>
"""
    )


def _toggle_changed() -> None:
    st.session_state["_dark"] = bool(st.session_state.get("dark_w"))


def theme_toggle() -> None:
    """Light (default) / dark switch. Stored outside the widget key so it survives page changes."""
    st.toggle(
        "Dark",
        value=is_dark(),
        key="dark_w",
        on_change=_toggle_changed,
        help="Switch to the night-sky theme (e.g. dark room or projector).",
    )


def setup(title: str, toggle: bool = True) -> None:
    st.markdown(css(palette()), unsafe_allow_html=True)
    if toggle:  # pages without their own header: switch at the top right
        _, right = st.columns([8, 1])
        with right:
            theme_toggle()


def badge(kind: str) -> str:
    return f'<span class="c2g-badge">{PROVENANCE[kind]}</span>'


def panel_title(text: str, *kinds: str, focus: bool = False) -> None:
    cls = "c2g-panel-title c2g-focus" if focus else "c2g-panel-title"
    mark = '<span class="c2g-watch">● watch</span>' if focus else ""
    st.markdown(
        f'<div class="{cls}">{text} {"".join(badge(k) for k in kinds)}{mark}</div>',
        unsafe_allow_html=True,
    )


def faceoff(*cells: tuple[str, str, str, str]) -> None:
    """Large numbers side by side: (label, value, sub-text, accent colour) per cell."""
    html = "".join(
        f'<div class="c2g-face" style="border-top:4px solid {c}"><div class="k">{k}</div>'
        f'<div class="v">{v}</div><div class="s">{s}</div></div>'
        for k, v, s, c in cells
    )
    vs = '<div class="c2g-vs">vs</div>' if len(cells) == 2 else ""
    st.markdown(
        f'<div class="c2g-faceoff" style="grid-template-columns:repeat({len(cells)},1fr)">'
        f"{html}{vs}</div>",
        unsafe_allow_html=True,
    )


# "What did we learn?": one card per stage, frozen S1 numbers only (model_evolution.csv)
LADDER = [
    ("zero_shot", "Zero-shot", "Topology failure"),
    ("E5", "+ synthetic topology adaptation", "Synthetic success, real failure"),
    ("E5b", "+ broader operating envelope", "~99 % lower real-state error"),
    ("E5c", "+ explicit generators", "Better load and battery response; PV still blind"),
    ("E5d", "+ paired response supervision", "PV sensitivity transfers; calibration still off"),
]


def learned_ladder(evo: object, models: list[str]) -> None:
    """One card per listed stage, each fixing a different failure mode (evo indexed by id)."""
    ac = float(evo.iloc[0]["ac_slope_pv"])
    cells = []
    for i, (m, added, outcome) in enumerate(x for x in LADDER if x[0] in models):
        pv, pbe = float(evo.at[m, "genco_slope_pv"]), float(evo.at[m, "PBE_mean"])
        note = "PV slope not a usable response (import r 0.11)" if m == "E5" else ""
        cells.append(
            f'<div class="c2g-step" style="border-top:4px solid {colour(m)}">'
            f'<div class="n">{i + 1}. {named(m)}</div><div class="a">{added}</div>'
            f'<div class="o">{outcome}</div>'
            f'<div class="m"><span>Real-state error</span><b>{pbe:.2g} MVA</b></div>'
            f'<div class="m"><span>PV response (AC {ac:+.2f})</span><b>{pv:+.2f}</b></div>'
            f'<div class="m"><span>Import bias</span><b>{evo.at[m, "import_bias_mw"]:+.0f} MW</b>'
            f"</div>"
            f'<div class="x">{note}</div></div>'
        )
    st.markdown(
        '<div class="c2g-ladder">' + "".join(cells) + "</div>"
        '<div class="c2g-note">Frozen results on the same 2,829 real half-hourly 2024 states. '
        "Real-state error = mean power-balance error; PV response = MW of grid import per MW of "
        "PV. No stage passes the full pre-registered real-transfer gate, so the weather question "
        "stays unresolved.</div>",
        unsafe_allow_html=True,
    )


def tiles(items: list[tuple[str, str, str]]) -> None:
    """Hero numbers without delta arrows: (label, value, sub-text)."""
    cells = "".join(
        f'<div class="c2g-tile"><div class="k">{k}</div><div class="v">{v}</div>'
        f'<div class="s">{s}</div></div>'
        for k, v, s in items
    )
    st.markdown(f'<div class="c2g-tiles">{cells}</div>', unsafe_allow_html=True)


def network_legend(mode: str) -> str:
    """Compact visual legend for the schematic."""
    colour = (
        '<span class="c2g-lg-grad err"></span> error vs AC (blue: model lower · red: higher)'
        if mode == "error"
        else '<span class="c2g-lg-grad"></span> loading 0 → 100 %'
    )
    return (
        '<div class="c2g-legend">'
        '<span><span class="c2g-lg-line thin"></span><span class="c2g-lg-line thick"></span> '
        "active power</span>"
        f"<span>{colour}</span>"
        f'<span><span class="c2g-lg-dot" style="background:{palette()["PV"]}"></span> PV</span>'
        f'<span><span class="c2g-lg-dot sq" style="background:{palette()["BATTERY"]}"></span> '
        "battery</span>"
        f'<span><span class="c2g-lg-bar"></span> busbar</span>'
        "<span>schematic, not a map</span></div>"
    )


def html_table(df: object, index: bool = False) -> None:
    """Theme-aware HTML table (st.dataframe draws on a canvas that CSS cannot recolour)."""
    from html import escape

    import pandas as pd

    d = df.reset_index() if index else df
    head = "".join(f"<th>{escape(str(c))}</th>" for c in d.columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(v)) if pd.notna(v) else ''}</td>" for v in r) + "</tr>"
        for r in d.itertuples(index=False)
    )
    st.markdown(
        f'<div class="c2g-table-wrap"><table class="c2g-table"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True,
    )


def model_cards(models: list[str]) -> None:
    """'Meet the models': name, experiment code, what it is, what happened."""
    cells = "".join(
        f'<div class="c2g-model" style="border-top:4px solid {colour(m)}">'
        f'<div class="n">{named(m)}</div><div class="a">{ABOUT[m]}</div>'
        f'<div class="v">Result: {VERDICT[m]}</div></div>'
        for m in models
    )
    st.markdown(f'<div class="c2g-models">{cells}</div>', unsafe_allow_html=True)


def swatch(model: str) -> str:
    return f'<span class="c2g-swatch" style="background:{colour(model)}"></span>'


ATTRIBUTION_FOOTER = (
    "Contains modified EUMETSAT Meteosat data 2024 (E-View RGB, CC BY 4.0) · "
    "EUMETSAT LSA SAF [MDSSFTD, LSA-207] (CC BY 4.0) · Contains UK Power Networks data, licensed "
    "under CC BY 4.0; contains data from the Office for National Statistics (OGL v3.0) and OS data "
    "© Crown copyright · GENCO / gridfm (Apache-2.0). All data modified by Cloud2Grid — full "
    "credits on the Data & Attribution page."
)


def footer() -> None:
    st.markdown(
        f'<div class="c2g-note" style="margin-top:18px">{ATTRIBUTION_FOOTER}</div>',
        unsafe_allow_html=True,
    )

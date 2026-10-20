# ruff: noqa: E501
"""Cloud Impact: From Clouds to Grid to Value (one historical event, five connected stages).

Reads only frozen files: the 15 June 2024 Explorer bundle (data/demo/events/jun15_cloud_clearing),
the Cloud Impact bundle (data/demo/cloud_impact: AC counterfactuals, frozen E5c/E5d predictions and
Elexon BMRS prices, built by scripts/economic_impact/build_cloud_impact_bundle.py) and the published
model evolution table. No power flow, inference or API call runs here.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from c2g import data as D
from c2g import figures as F
from c2g import satellite as SAT
from c2g import theme as T
from plotly.subplots import make_subplots

T.setup("Cloud Impact")
BUNDLE = D.DATA / "cloud_impact"
EVENT = "jun15_cloud_clearing"
H = 0.5
ATTRIB = "Contains BMRS data © Elexon Limited copyright and database right 2024"
STAGES = ["Clouds", "Solar", "Grid", "GENCO", "Value"]
STAGE_TIME = {0: "10:45", 1: "11:30", 2: "11:00", 3: "11:00", 4: "11:00"}
CAPTIONS = [
    ("A cloud deck over a real solar area", "Meteosat watched this cloud deck over Bedfordshire on 15 June 2024. The dotted box is the Sundon study area; the yellow dots are its solar plants."),
    ("The cloud clears, and solar output jumps", "Between 11:00 and 11:30 UTC the sky opens: satellite-derived PV across the area rises from 2.38 MW to 8.86 MW."),
    ("Solar changes how much power the grid imports", "In our AC reconstruction of the real 38-bus Sundon network, more local solar means less power drawn from upstream, when everything else is held fixed."),
    ("Our adapted GENCO learns that response", "Response-aware adaptation lets GENCO reproduce how the import responds to solar (−1.07 MW per MW, physics −1.02). Its absolute level still needs validation."),
    ("Why it matters: the energy has a market value", "Valuing the extra import caused by clouds at the actual half-hourly market prices of that day gives an illustrative economic exposure."),
]


@st.cache_data(show_spinner=False)
def bundle() -> tuple[pd.DataFrame, dict, dict]:
    p = pd.read_parquet(BUNDLE / "periods_2024-06-15.parquet")
    return p, json.loads((BUNDLE / "season.json").read_text()), json.loads((BUNDLE / "provenance.json").read_text())


def badge(text: str, colour: str) -> str:
    return (f'<span style="display:inline-block;padding:1px 9px;margin:0 6px 4px 0;border-radius:999px;font-size:0.74rem;'
            f'font-weight:600;border:1px solid {colour};color:{colour}">{text}</span>')  # fmt: skip


def gbp(x: float, d: int = 0) -> str:
    return f"£{x:,.{d}f}"


ev = D.event(EVENT)
P, S, PROV = bundle()
evo = D.evolution()
layout = D.network_layout()
ss = st.session_state
ss.setdefault("ci_stage", 0)
ss.setdefault("ci_scenario", "Observed sky")
frames = ev.frames.reset_index(drop=True)
times = list(frames.timestamp_utc)
hhmm = [f"{t:%H:%M}" for t in times]

# ------------------------------------------------------------------ hero
st.markdown(
    f"""<div style="padding:2px 0 4px 0">
<div style="font-size:2.35rem;font-weight:800;color:{T.INK};line-height:1.1">From Clouds to Grid to Value</div>
<div style="font-size:1.08rem;color:{T.INK_2};margin-top:6px;max-width:1000px">Explore how satellite-observed cloud conditions affect estimated
solar generation, reconstructed electricity-grid behaviour and the illustrative economic value of energy, on one real day: 15 June 2024, Sundon (UK Power Networks).</div>
<div style="margin-top:8px">{badge("Observed: Meteosat imagery, market prices", T.PV)}{badge("Derived: satellite PV estimate", T.ACCENT_TEXT)}{badge("Simulated: AC power flow", T.INK)}{badge("Predicted: GENCO", T.colour("E5d"))}{badge("Hypothetical: clear-sky counterfactual", T.MUTED)}</div>
</div>""",
    unsafe_allow_html=True,
)

# ------------------------------------------------------------------ story stepper
st.markdown("<style>div[data-testid='stButtonGroup'] > div, div[data-testid='stButtonGroup'] {flex-wrap: wrap !important; row-gap: 6px;}</style>", unsafe_allow_html=True)
c_steps, c_nav = st.columns([5, 1.4], vertical_alignment="center")
with c_steps:
    pick = st.pills("Story", [f"{i + 1} · {s}" for i, s in enumerate(STAGES)], default=f"{ss.ci_stage + 1} · {STAGES[ss.ci_stage]}",
                    key=f"ci_seg_{ss.ci_stage}", label_visibility="collapsed")  # fmt: skip
    if pick and int(pick[0]) - 1 != ss.ci_stage:
        ss.ci_stage = int(pick[0]) - 1
        st.rerun()
with c_nav:
    b1, b2 = st.columns(2)
    if b1.button("Back", disabled=ss.ci_stage == 0, width="stretch"):
        ss.ci_stage -= 1
        st.rerun()
    if b2.button("Next", type="primary", disabled=ss.ci_stage == len(STAGES) - 1, width="stretch"):
        ss.ci_stage += 1
        st.rerun()
stage = ss.ci_stage
head, body = CAPTIONS[stage]
st.markdown(
    f'<div class="c2g-callout" style="border-left-color:{T.ACCENT};font-size:1.05rem"><b>{stage + 1} / 5 · {head}.</b> {body}</div>',
    unsafe_allow_html=True,
)

# ------------------------------------------------------------------ time
default_t = STAGE_TIME[stage]
t_label = st.select_slider("Time (UTC, real 15-minute satellite frames)", options=hhmm, value=default_t, key=f"ci_t_{stage}")  # one widget per stage: resets to the stage time
i = hhmm.index(t_label)
frame = frames.iloc[i]
t = frame.timestamp_utc
g = ev.grid_slot_for(t)
fleet = ev.fleet_pv.set_index("timestamp_utc").fleet_pv_mw
summ = ev.summary[ev.summary.model == "AC"].set_index("timestamp_utc")
per = P.set_index("slot_utc")
pg = per.loc[g]

# ------------------------------------------------------------------ main visual: satellite | network
left, right = st.columns([1.05, 1])
with left:
    T.panel_title(f"Meteosat E-View · {t:%d %b %Y %H:%M} UTC", "OBSERVED")
    pv_now = ev.pv_generation[ev.pv_generation.timestamp_utc == t]
    st.html(SAT.render(frame, None, ev.nodes, ev.edges, ev.assets, pv_now, zoom=True))
    st.markdown('<div class="c2g-note">Real 15-minute images, historical. Bright = cloud · dotted box = Sundon study area · yellow = PV plants (size: capacity, opacity: estimated output).</div>', unsafe_allow_html=True)
with right:
    held = f"grid state {g:%H:%M}" if g == t else f"grid state held since {g:%H:%M}"
    T.panel_title(f"Sundon network · AC reconstruction · {held}", "SIMULATED")
    br = ev.branch[ev.branch.timestamp_utc == g]
    bus = ev.bus[(ev.bus.timestamp_utc == g) & (ev.bus.model == "AC")]
    st.plotly_chart(F.network(ev.nodes, ev.edges, br[br.model == "AC"], br[br.model == "AC"], bus, "AC", "flow", layout),
                    width="stretch", config={"displayModeBar": False}, key="ci_net")  # fmt: skip
    st.markdown(T.network_legend("flow"), unsafe_allow_html=True)

# ------------------------------------------------------------------ readouts for the stage
f11, f1130 = float(fleet[pd.Timestamp("2024-06-15 11:00", tz="UTC")]), float(fleet[pd.Timestamp("2024-06-15 11:30", tz="UTC")])
ac_slope = float(evo.at["E5d", "ac_slope_pv"])
if stage == 0:
    irr = ev.irradiance[(ev.irradiance.timestamp_utc == t) & (ev.irradiance.asset_id == "ECR:955")]
    kc = float(irr.clearsky_index.mean()) if len(irr) else float("nan")
    sky = "clear" if kc >= 0.8 else "broken cloud" if kc >= 0.5 else "overcast"
    T.tiles([
        ("Sky over the 6 MW plant", sky, f"satellite clear-sky index {kc:.2f} at {t:%H:%M}"),
        ("Solar output, all local plants", f"{float(fleet.get(t, np.nan)):.2f} MW", "satellite-derived estimate (8.945 MW installed)"),
        ("Grid import", f"{float(summ.at[g, 'import_mw']):.1f} MW", f"AC reconstruction, {g:%H:%M} half-hour"),
    ])  # fmt: skip
elif stage == 1:
    now = float(fleet.get(t, np.nan))
    T.tiles([
        ("Solar output now", f"{now:.2f} MW", f"{t:%H:%M} UTC, satellite-derived"),
        ("All local PV: change since 11:00", f"{T.num(now - f11, '+.2f')} MW", f"15-min satellite estimate · 11:00: {f11:.2f} MW · 11:30: {f1130:.2f} MW"),
        ("The 6 MW plant (33 kV)", f"{float(per.at[g, 'plant_pv_mw']):.2f} MW", f"{g:%H:%M} half-hour; it reaches its 6 MW export limit at 11:30"),
    ])  # fmt: skip
    st.markdown('<div class="c2g-note">Estimated from EUMETSAT LSA SAF surface radiation with a documented pvlib model at every registered plant: an estimate, not a meter reading.</div>', unsafe_allow_html=True)
elif stage == 2:
    d_cf = float(pg.import_AC_observed_mw - pg.import_AC_clear_sky_mw)
    d_pv = float(pg.plant_pv_clear_mw - pg.plant_pv_mw)
    i11, i1130 = float(summ.at[pd.Timestamp("2024-06-15 11:00", tz="UTC"), "import_mw"]), float(summ.at[pd.Timestamp("2024-06-15 11:30", tz="UTC"), "import_mw"])
    T.faceoff(
        ("Historical trajectory, 11:00 → 11:30", f"{i11:.1f} → {i1130:.1f} MW", "AC import; loads, battery and solar all changed together", T.INK_2),
        (f"Solar-only effect at {g:%H:%M} (loads held fixed)", f"{T.num(-d_cf, '+.1f')} MW",
         f"if the plant had produced its clear-sky {float(pg.plant_pv_clear_mw):.2f} MW instead of {float(pg.plant_pv_mw):.2f} MW (+{d_pv:.2f} MW): AC import {float(pg.import_AC_observed_mw):.1f} → {float(pg.import_AC_clear_sky_mw):.1f} MW", T.PV),
    )  # fmt: skip
    st.markdown(f'<div class="c2g-note">The historical import change is not all due to solar. The solar-only effect comes from re-solving the same AC state with only the plant\'s output changed; about {abs(ac_slope):.2f} MW of import per MW of solar on this network.</div>', unsafe_allow_html=True)
elif stage == 3:
    g1, g2 = st.columns([1.05, 1])
    with g1:
        st.markdown("**Import response to solar** · 2,829 real 2024 states · MW of import per MW of PV")
        rows = [("E5c", "E5c ordinary"), ("E5d", "E5d response-aware"), ("AC", "AC physics")]
        vals = [float(evo.at["E5c", "genco_slope_pv"]), float(evo.at["E5d", "genco_slope_pv"]), ac_slope]
        fig = go.Figure(go.Bar(y=[r[1] for r in rows], x=vals, orientation="h", marker_color=[T.colour("E5c"), T.colour("E5d"), T.colour("AC")],
                               text=[T.num(v, "+.2f") for v in vals], textposition="outside"))  # fmt: skip
        fig.update_layout(**T.plotly_layout(height=220, xaxis=T.axis(range=[-1.45, 0.25]), yaxis=T.axis(autorange="reversed"), margin=dict(l=8, r=8, t=8, b=8)))  # fmt: skip
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    with g2:
        dac = float(pg.import_AC_observed_mw - pg.import_AC_clear_sky_mw)
        d5d = float(pg.import_E5d_observed_mw - pg.import_E5d_clear_sky_mw)
        d5c = float(pg.import_E5c_observed_mw - pg.import_E5c_clear_sky_mw)
        T.tiles([
            (f"AC: import change at {g:%H:%M}", f"{T.num(-dac, '+.2f')} MW", f"if the plant had its clear-sky output (+{float(pg.plant_pv_clear_mw - pg.plant_pv_mw):.2f} MW), loads fixed"),
            ("E5d: predicted change, same counterfactual", f"{T.num(-d5d, '+.2f')} MW", "learned from paired synthetic AC states"),
            ("E5c: predicted change, same counterfactual", f"{T.num(-d5c, '+.2f')} MW", "ordinary adaptation responds only weakly"),
        ])  # fmt: skip
    bias_now = float(pg.import_E5d_observed_mw - pg.import_AC_observed_mw)
    st.markdown(
        f'<div class="c2g-callout"><b>Response learned; absolute level still needs validation.</b> E5d reproduces the <i>change</i> in import, but its '
        f'<i>absolute</i> import is about {float(evo.at["E5d", "import_bias_mw"]):.1f} MW too high across 2,829 real states ({T.num(bias_now, "+.1f")} MW at {g:%H:%M}). '
        "It is a research model, not a validated operational state estimator. Simple physical accounting already gives this change on a known network; "
        "GENCO's achievement is learning it from synthetic data.</div>",
        unsafe_allow_html=True,
    )

# ------------------------------------------------------------------ synchronized timeline
full = stage == 4
clear = full and ss.ci_scenario.startswith("Clear")
fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.11, row_heights=[0.38, 0.34, 0.28],
                    subplot_titles=("Solar (MW)", "Grid import, AC reconstruction (MW)", "Historical APX market price (£/MWh)"))  # fmt: skip
fig.add_trace(go.Scatter(x=ev.fleet_pv.timestamp_utc, y=ev.fleet_pv.fleet_pv_mw, name="all local PV, 15-min (derived)", line=dict(color=T.PV, width=2.6)), 1, 1)
fig.add_trace(go.Scatter(x=P.slot_utc, y=P.plant_pv_mw, name="6 MW plant (derived)", mode="lines+markers", line=dict(color=T.ACCENT_TEXT, width=1.8), marker=dict(size=5)), 1, 1)
fig.add_trace(go.Scatter(x=P.slot_utc, y=P.plant_pv_clear_mw, name="6 MW plant, clear sky (hypothetical)", line=dict(color=T.MUTED, dash="dash", width=1.6 + clear)), 1, 1)
fig.add_trace(go.Scatter(x=P.slot_utc, y=P.import_AC_observed_mw, name="import, observed sky", mode="lines+markers", line=dict(color=T.colour("AC"), width=2.4), marker=dict(size=5)), 2, 1)
fig.add_trace(go.Scatter(x=P.slot_utc, y=P.import_AC_clear_sky_mw, name="import, clear-sky plant (hypothetical)", line=dict(color=T.MUTED, dash="dash", width=1.6 + clear),
                         fill="tonexty" if clear else None, fillcolor="rgba(201,133,0,0.18)"), 2, 1)  # fmt: skip
fig.add_trace(go.Scatter(x=P.slot_utc, y=P.apx_gbp_per_mwh, name="APX price (historical)", line=dict(color=T.INK_2, width=1.8, shape="hv")), 3, 1)
fig.add_vrect(x0=pd.Timestamp("2024-06-15 11:00", tz="UTC"), x1=pd.Timestamp("2024-06-15 11:30", tz="UTC"), fillcolor=T.GLOW, line_width=0, row="all", col=1)
if not full:
    fig.add_vline(x=t, line=dict(color=T.ACCENT, width=2))
x0 = pd.Timestamp("2024-06-15 05:00" if full else "2024-06-15 08:30", tz="UTC")
x1 = pd.Timestamp("2024-06-15 17:00" if full else "2024-06-15 12:30", tz="UTC")
fig.update_layout(**T.plotly_layout(height=520, legend=dict(orientation="h", y=-0.12, x=0, font=dict(color=T.INK_2)), margin=dict(l=8, r=8, t=30, b=8)))
fig.update_annotations(font=dict(color=T.INK_2, size=13))
fig.update_xaxes(range=[x0, x1], **T.axis())
fig.update_yaxes(**T.axis())
st.plotly_chart(fig, width="stretch", config={"displayModeBar": False}, key="ci_timeline")
st.markdown('<div class="c2g-note">Shaded: the 11:00–11:30 clearing. Grid states and prices are half-hourly (settlement periods); satellite PV is 15-minute. '
            + ("Full day shown: every half-hour that has an AC-reconstructed state (05:00–16:30 UTC)." if full else "Satellite imagery exists for 08:45–12:15 UTC.") + "</div>",
            unsafe_allow_html=True)  # fmt: skip

# ------------------------------------------------------------------ stage 5: value
if stage == 4:
    ev_ac = S["event_2024-06-15"]["AC"]
    d = P.import_AC_observed_mw - P.import_AC_clear_sky_mw
    e_day, v_day = float((d * H).sum()), float((d * H * P.apx_gbp_per_mwh).sum())
    one = P[P.slot_utc.dt.strftime("%H:%M") == "11:00"].iloc[0]
    e_one = float((one.import_AC_observed_mw - one.import_AC_clear_sky_mw) * H)
    st.markdown(f"#### Observed sky vs clear sky {badge('Hypothetical counterfactual · retrospective, not a forecast', T.MUTED)}", unsafe_allow_html=True)
    st.radio("Scenario", ["Observed sky", "Clear sky (hypothetical)"], key="ci_scenario", horizontal=True, label_visibility="collapsed")
    gen_obs, gen_clr = float((P.plant_pv_mw * H).sum()), float((P.plant_pv_clear_mw * H).sum())
    imp_obs, imp_clr = float((P.import_AC_observed_mw * H).sum()), float((P.import_AC_clear_sky_mw * H).sum())
    sel = ss.ci_scenario.startswith("Clear")
    T.tiles([
        ("6 MW plant generation, 05:00–16:30", f"{(gen_clr if sel else gen_obs):.1f} MWh", "clear sky (hypothetical)" if sel else "observed sky (satellite-derived)"),
        ("Grid import, same half-hours", f"{(imp_clr if sel else imp_obs):,.1f} MWh", "AC reconstruction" + (", plant at clear sky" if sel else "")),
        ("Extra import caused by clouds", f"{e_day:.1f} MWh", "observed − clear sky, 24 half-hours"),
        ("Illustrative value at historical prices", gbp(v_day), "extra import × APX price, per half-hour, summed"),
    ])  # fmt: skip
    c1, c2 = st.columns([1.35, 1])
    with c1:
        st.markdown("**Cloud-attributed import value per half-hour (£)** · 15 June 2024 · AC reconstructions × APX price")
        vals = d * H * P.apx_gbp_per_mwh
        fig = go.Figure(go.Bar(x=P.slot_utc, y=vals, marker_color=np.where(vals >= 0, T.PV, T.MUTED), name="£ per half-hour"))
        fig.update_layout(**T.plotly_layout(height=260, margin=dict(l=8, r=8, t=8, b=8), xaxis=T.axis(), yaxis=T.axis(title="£ per half-hour")))
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    with c2:
        st.markdown(
            f'<div class="c2g-callout"><b>Day total ≠ one cloud ramp.</b> {gbp(v_day)} is the sum over <b>all 24 half-hours, 05:00–16:30 UTC</b> '
            f"(settlement periods {int(P.settlement_period.min())}–{int(P.settlement_period.max())}): {e_day:.1f} MWh of extra import, each half-hour priced at its own APX price "
            f"(£{P.apx_gbp_per_mwh.min():.0f}–{P.apx_gbp_per_mwh.max():.0f}/MWh that day). The 11:00 half-hour alone, just before the clearing: "
            f"{e_one:.2f} MWh × £{one.apx_gbp_per_mwh:.2f}/MWh ≈ <b>{gbp(e_one * one.apx_gbp_per_mwh)}</b>.</div>",
            unsafe_allow_html=True,
        )
    sp, sc = S["pv_attributed"]["AC"], S["cloud_attributed"]["AC"]
    st.markdown(f"**Across the season** · {S['periods_valued']:,} AC-reconstructed half-hours of April–September 2024 (not every daylight hour). One of them, 13 Apr 07:00 UTC, has no APX price at source; its value (≤ £4) is omitted.")
    T.tiles([
        ("Import displaced by the 6 MW plant", f"{sp['energy_mwh']:,.0f} MWh", f"{gbp(sp['value_apx_gbp'])} at APX prices (illustrative)"),
        ("Extra import caused by clouds", f"{sc['energy_mwh']:,.0f} MWh", f"{gbp(sc['value_apx_gbp'])} at APX prices (illustrative)"),
    ])  # fmt: skip
    st.markdown("**Four numbers, four different things**")
    i11 = float(summ.at[pd.Timestamp("2024-06-15 11:00", tz="UTC"), "import_mw"])
    i1130 = float(summ.at[pd.Timestamp("2024-06-15 11:30", tz="UTC"), "import_mw"])
    p11 = P.set_index(P.slot_utc.dt.strftime("%H:%M")).loc["11:00"]
    T.html_table(pd.DataFrame([
        {"Number": f"{T.num(f1130 - f11, '+.2f')} MW", "What it measures": "change in satellite-derived PV, all local plants", "Interval": "11:00 → 11:30 UTC (15-min estimates)", "Source": "derived"},
        {"Number": f"{i11:.1f} → {i1130:.1f} MW", "What it measures": "historical AC import; loads, battery and solar all changed", "Interval": "11:00 and 11:30 half-hours", "Source": "simulated (AC reconstruction)"},
        {"Number": f"{T.num(-float(p11.import_E5d_observed_mw - p11.import_E5d_clear_sky_mw), '+.2f')} MW (AC {T.num(-float(p11.import_AC_observed_mw - p11.import_AC_clear_sky_mw), '+.2f')} MW)",
         "What it measures": f"E5d-predicted import change if the 6 MW plant had its clear-sky output (+{float(p11.plant_pv_clear_mw - p11.plant_pv_mw):.2f} MW), loads fixed", "Interval": "11:00 half-hour only", "Source": "predicted (counterfactual)"},
        {"Number": gbp(v_day), "What it measures": "illustrative value of the extra import caused by clouds (observed − clear sky), at APX prices", "Interval": "24 half-hours, 05:00–16:30 UTC", "Source": "AC counterfactual × historical price"},
    ]))  # fmt: skip
    st.markdown(
        '<div class="c2g-callout" style="border-left-color:#e34948"><b>What these numbers are, and are not.</b> '
        "Historical prices are authentic (Elexon APX Market Index). PV is satellite-derived; electrical states are AC reconstructions; clear sky is a counterfactual. "
        "The amounts are indicative valuations of energy, <b>not</b> realised savings, costs, bills or revenues. "
        "GENCO does not predict electricity prices. A national market price is not a local nodal price. Nothing here forecasts future weather or prices. "
        f"Only the 6 MW plant is varied; smaller plants inside the metered loads are not. {ATTRIB}.</div>",
        unsafe_allow_html=True,
    )
    with st.expander("How accurately do the models reproduce this valuation? (accuracy of an energy valuation, not price prediction)"):
        pa = S["pv_attributed"]
        tab = pd.DataFrame([
            {"Method": "AC reference", "Season value (import displaced)": gbp(pa["AC"]["value_apx_gbp"]), "Error vs AC": "—", "Per-half-hour error (MW)": "—"},
            {"Method": "Simple injection accounting (lossless)", "Season value (import displaced)": gbp(pa["accounting"]["value_apx_gbp"]), "Error vs AC": f"{T.num(pa['accounting']['value_apx_error_pct'], '+.1f')} %", "Per-half-hour error (MW)": f"{pa['accounting']['period_mae_mw']:.3f}"},
            {"Method": "Response-aware GENCO (E5d)", "Season value (import displaced)": gbp(pa["E5d"]["value_apx_gbp"]), "Error vs AC": f"{T.num(pa['E5d']['value_apx_error_pct'], '+.1f')} %", "Per-half-hour error (MW)": f"{pa['E5d']['period_mae_mw']:.3f}"},
            {"Method": "Generator-aware GENCO (E5c)", "Season value (import displaced)": gbp(pa["E5c"]["value_apx_gbp"]), "Error vs AC": f"{T.num(pa['E5c']['value_apx_error_pct'], '+.1f')} %", "Per-half-hour error (MW)": f"{pa['E5c']['period_mae_mw']:.2f}"},
        ])  # fmt: skip
        T.html_table(tab)
        absd = S["absolute_mode_diagnostic"]
        st.markdown(
            '<div class="c2g-note">Signed season totals. E5d\'s small total error partly comes from errors cancelling: <b>per half-hour, simple accounting is slightly more accurate</b>, '
            "and the AC calculation itself is exact and cheap on this network. The learned response matters: ordinary adaptation (E5c) would miss almost all of the value. "
            f"Never price GENCO's absolute import: E5d's bias would overstate the value of all imported energy by {gbp(absd['E5d']['error_vs_ac_gbp'])} "
            f"({100 * absd['E5d']['error_vs_ac_gbp'] / absd['AC']['import_value_apx_gbp']:.0f} %).</div>",
            unsafe_allow_html=True,
        )

with st.expander("Sources, methods and limitations"):
    st.markdown(
        "- **Satellite:** EUMETSAT Meteosat E-View imagery (observed) and LSA SAF surface radiation → pvlib (derived PV estimate, not metered).\n"
        "- **Grid:** AC power flow on the Sundon network rebuilt from UK Power Networks open data, validated against metered circuits; states reconstructed from metered half-hourly loads plus satellite PV.\n"
        "- **Counterfactual:** the same AC state re-solved with only the 6 MW plant's output changed (clear sky: same pvlib chain under the Ineichen clear-sky model).\n"
        "- **Prices:** Elexon Insights APX Market Index Data per settlement period (BST: period 1 starts 23:00 UTC); frozen in the app, no runtime API call.\n"
        "- **Models:** frozen E5c and E5d checkpoints (release cloud2grid-models-v1); E5d is not a validated operational model.\n"
        f"- **Method:** pre-registered (configs/economic_impact/prereg.yaml); scripts/economic_impact/verify_economic.py re-checks the 15 June numbers from this page's frozen bundle and the season totals from the released per-half-hour table; re-solving the AC counterfactuals and re-running GENCO needs local research data that is not redistributed. {ATTRIB}."
    )
T.footer()

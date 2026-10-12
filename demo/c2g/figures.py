"""Plotly figures for the Cloud2Grid Explorer (render only — every number comes from a bundle)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from c2g import theme as T


# --------------------------------------------------------------------------- network
def network(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    br: pd.DataFrame,
    br_ac: pd.DataFrame,
    bus: pd.DataFrame,
    model: str,
    mode: str,
    layout: dict | None = None,
) -> go.Figure:
    """Manual electrical schematic (NOT geographic; configs/app/network_layout.yaml).
    mode='flow': width ∝ |P|, colour = loading %.
    mode='error': colour = signed branch-flow error vs AC (model − AC, MW)."""
    pos = nodes.set_index("bus")[["schematic_x", "schematic_y"]]
    key_of = nodes.set_index("bus").node_key
    bars = {b: (layout or {}).get("busbars", {}).get(k) for b, k in key_of.items()}
    bars = {b: v["y"] for b, v in bars.items() if v}
    s = br.set_index("branch_id")
    a = br_ac.set_index("branch_id")
    fig = go.Figure()
    mid_x, mid_y, mid_text, mid_val = [], [], [], []
    emax = 10.0
    bar_x: dict[int, list[float]] = {b: [float(pos.at[b, "schematic_x"])] for b in bars}

    def ends(e: object) -> tuple[float, float, float, float]:
        """Branch end points; a busbar end sits on the bar above/below the other end."""
        xa, ya = pos.loc[e.bus_a]
        xb, yb = pos.loc[e.bus_b]
        if e.bus_a in bars:
            xa, ya = xb, bars[e.bus_a]
            bar_x[e.bus_a].append(xb)
        if e.bus_b in bars:
            xb, yb = xa, bars[e.bus_b]
            bar_x[e.bus_b].append(xa)
        return xa, ya, xb, yb

    for e in edges.itertuples():
        x0, y0, x1, y1 = ends(e)
        if e.branch_id not in s.index:  # out of service in this state
            fig.add_trace(
                go.Scatter(
                    x=[x0, x1],
                    y=[y0, y1],
                    mode="lines",
                    hoverinfo="skip",
                    line=dict(color=T.AXIS, width=1, dash="dot"),
                    showlegend=False,
                )
            )
            continue
        p = float(s.at[e.branch_id, "p_ab_mw"])
        load = float(s.at[e.branch_id, "loading_pct"])
        p_ac = float(a.at[e.branch_id, "p_ab_mw"])
        err = p - p_ac
        if mode == "flow":
            c = _sample(T.LOADING_SCALE, np.clip(load / 100.0, 0, 1))
        else:
            c = _sample(T.DIVERGING, 0.5 + 0.5 * np.clip(err / emax, -1, 1))
        w = 1.5 + 7.0 * np.sqrt(min(abs(p), 120) / 120)
        fig.add_trace(
            go.Scatter(
                x=[x0, x1],
                y=[y0, y1],
                mode="lines",
                hoverinfo="skip",
                line=dict(color=c, width=w),
                showlegend=False,
            )
        )
        mid_x.append((x0 + x1) / 2)
        mid_y.append((y0 + y1) / 2)
        mid_val.append(load if mode == "flow" else err)
        mid_text.append(
            f"<b>{e.from_node.split(':')[1]} – {e.to_node.split(':')[1]}</b> ({e.kind})<br>"
            f"{T.SHORT[model]} P = {p:+.1f} MW, loading {load:.0f} %<br>"
            f"AC P = {p_ac:+.1f} MW<br>error = {err:+.1f} MW<br>"
            f"<span style='color:{T.MUTED}'>{e.elements}</span>"
        )
        # flow-direction arrow (sending end → receiving end) for material flows
        if abs(p) > 0.5:
            sx, sy, ex, ey = (x0, y0, x1, y1) if p > 0 else (x1, y1, x0, y0)
            fig.add_annotation(
                x=sx + 0.58 * (ex - sx),
                y=sy + 0.58 * (ey - sy),
                ax=sx + 0.42 * (ex - sx),
                ay=sy + 0.42 * (ey - sy),
                xref="x",
                yref="y",
                axref="x",
                ayref="y",
                showarrow=True,
                arrowhead=2,
                arrowsize=1.1,
                arrowwidth=1.2,
                arrowcolor=T.ARROW,
                text="",
            )
    scale = T.LOADING_SCALE if mode == "flow" else T.DIVERGING
    cmin, cmax = (0, 100) if mode == "flow" else (-emax, emax)
    fig.add_trace(
        go.Scatter(
            x=mid_x,
            y=mid_y,
            mode="markers",
            text=mid_text,
            hovertemplate="%{text}<extra></extra>",
            marker=dict(
                size=14,
                color=mid_val,
                colorscale=scale,
                cmin=cmin,
                cmax=cmax,
                opacity=0.01,
                colorbar=dict(
                    title=dict(
                        text="loading %" if mode == "flow" else "ΔP MW",
                        font=dict(color=T.INK_2, size=11),
                    ),
                    thickness=10,
                    len=0.55,
                    x=1.01,
                    xpad=4,
                    tickfont=dict(color=T.MUTED, size=10),
                    outlinewidth=0,
                ),
            ),
            showlegend=False,
        )
    )
    b = bus.set_index("bus")
    n = nodes.set_index("bus")
    for k, y in bars.items():
        x_lo, x_hi = min(bar_x[k]) - 0.12, max(bar_x[k]) + 0.12
        vm = float(b.at[k, "vm_pu"]) if k in b.index else float("nan")
        fig.add_trace(
            go.Scatter(
                x=[x_lo, x_hi],
                y=[y, y],
                mode="lines",
                line=dict(color=T.BUSBAR, width=6),
                hoverinfo="text",
                showlegend=False,
                text=f"{n.at[k, 'label']} busbar ({n.at[k, 'vn_kv']:.0f} kV) · Vm {vm:.3f} pu",
            )
        )
    n = n.drop(index=list(bars))
    role_style = {
        "pv_33kv": (T.PV, "circle", "PV connection"),
        "battery_33kv": (T.BATTERY, "square", "battery customer"),
        "load_11kv": (T.INK_2, "circle", "11 kV primary load"),
    }
    for role, g in n.groupby("role"):
        colr, sym, desc = role_style.get(role, (T.MUTED, "circle", "33/132 kV busbar"))
        sub = g.join(b[["vm_pu", "p_inj_mw"]], how="left")
        size = 9 if role != "pv_33kv" else 9 + 3 * np.sqrt(np.clip(sub.p_inj_mw, 0, 6))
        fig.add_trace(
            go.Scatter(
                x=sub.schematic_x,
                y=sub.schematic_y,
                mode="markers",
                marker=dict(
                    size=size, color=colr, symbol=sym, line=dict(color=T.SURFACE, width=1.5)
                ),
                customdata=np.c_[sub.vm_pu, sub.p_inj_mw],
                text=sub.label + f" · {desc}",
                hovertemplate="%{text}<br>Vm %{customdata[0]:.3f} pu<br>"
                "net injection %{customdata[1]:+.2f} MW<extra></extra>",
                showlegend=False,
            )
        )
    for band in (layout or {}).get("bands", []):  # voltage hierarchy, drawn behind everything
        fig.add_shape(
            type="rect",
            x0=-7.25,
            x1=6.0,
            y0=band["y0"],
            y1=band["y1"],
            layer="below",
            line_width=0,
            fillcolor=T.BAND_FILL if band["label"] != "33 kV" else "rgba(255,255,255,0.0)",
        )
        fig.add_annotation(
            x=-7.2,
            y=(band["y0"] + band["y1"]) / 2,
            text=f"<b>{band['label']}</b>",
            showarrow=False,
            xanchor="left",
            font=dict(color=T.MUTED, size=11),
        )
    for g in (layout or {}).get("groups", []):
        fig.add_annotation(
            x=g["x"],
            y=g["y"],
            text=g["label"],
            showarrow=False,
            xanchor=g.get("anchor", "center"),
            font=dict(color=T.INK_2, size=10),
        )
    for _, r in n[n.role == "pv_33kv"].iterrows():
        fig.add_annotation(
            x=r.schematic_x,
            y=r.schematic_y,
            text="PV",
            showarrow=False,
            yshift=-15,
            font=dict(color=T.PV, size=10),
        )
    fig.update_xaxes(visible=False, range=[-7.3, 5.8], fixedrange=True)
    fig.update_yaxes(visible=False, range=[-1.66, 4.5], fixedrange=True)
    fig.update_layout(
        **T.plotly_layout(
            height=390, margin=dict(l=0, r=48, t=0, b=0), dragmode=False, uirevision="network"
        )
    )
    return fig


def _sample(scale: list, v: float) -> str:
    """Linear interpolation in a 3-stop hex colourscale."""
    stops = [s for s, _ in scale]
    cols = [np.array([int(c[i : i + 2], 16) for i in (1, 3, 5)]) for _, c in scale]
    v = float(np.clip(v, 0, 1))
    for i in range(len(stops) - 1):
        if v <= stops[i + 1]:
            f = (v - stops[i]) / (stops[i + 1] - stops[i])
            c = cols[i] + f * (cols[i + 1] - cols[i])
            return "#" + "".join(f"{int(round(x)):02x}" for x in c)
    return scale[-1][1]


# --------------------------------------------------------------------------- timeline
def timeline(
    fleet: pd.DataFrame,
    summ: pd.DataFrame,
    model: str,
    t_now: pd.Timestamp,
    grid_now: pd.Timestamp,
    band: tuple | None = None,
) -> go.Figure:
    """Three stacked panels on one time axis: PV, grid import, model error. One y-axis each."""
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.07,
        row_heights=[0.3, 0.42, 0.28],
        subplot_titles=(
            "Satellite-derived PV (MW)",
            "Grid import at Sundon (MW)",
            f"{T.SHORT[model]} import error vs AC (MW)"
            if model != "AC"
            else "Model error (select a model)",
        ),
    )
    ac = summ[summ.model == "AC"].sort_values("timestamp_utc")
    fig.add_trace(
        go.Scatter(
            x=fleet.timestamp_utc,
            y=fleet.fleet_pv_mw,
            mode="lines",
            line=dict(color=T.PV, width=2, shape="spline", smoothing=0.4),
            fill="tozeroy",
            fillcolor="rgba(201,133,0,0.18)",
            name="PV fleet (15 min)",
            hovertemplate="%{y:.2f} MW<extra>PV fleet</extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=ac.timestamp_utc,
            y=ac.p_hv_injected_mw,
            mode="markers",
            marker=dict(
                color=T.PV, size=8, symbol="diamond", line=dict(color=T.SURFACE, width=1.5)
            ),
            name="HV PV injected in grid state",
            hovertemplate="%{y:.2f} MW<extra>HV PV in grid state</extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=ac.timestamp_utc,
            y=ac.import_mw,
            mode="lines+markers",
            line=dict(color=T.AC, width=2),
            marker=dict(size=8),
            name="AC reference",
            hovertemplate="%{y:.1f} MW<extra>AC reference</extra>",
        ),
        row=2,
        col=1,
    )
    if model != "AC":
        m = summ[summ.model == model].sort_values("timestamp_utc")
        fig.add_trace(
            go.Scatter(
                x=m.timestamp_utc,
                y=m.import_mw,
                mode="lines+markers",
                line=dict(color=T.colour(model), width=2),
                marker=dict(size=8, line=dict(color=T.SURFACE, width=1.5)),
                name=T.LABELS[model],
                hovertemplate="%{y:.1f} MW<extra>" + T.SHORT[model] + "</extra>",
            ),
            row=2,
            col=1,
        )
        err = m.import_mw.to_numpy() - ac.import_mw.to_numpy()
        fig.add_trace(
            go.Bar(
                x=m.timestamp_utc,
                y=err,
                marker_color=T.colour(model),
                marker_line_width=0,
                width=1000 * 60 * 18,
                name="import error",
                showlegend=False,
                hovertemplate="%{y:+.1f} MW<extra>error</extra>",
            ),
            row=3,
            col=1,
        )
    for r in (1, 2, 3):
        fig.add_vline(x=t_now, line=dict(color=T.INK, width=1), row=r, col=1)
    if band is not None:  # story highlight over an interval (label only)
        b0, b1, lab = band
        for r in (1, 2, 3):
            fig.add_vrect(
                x0=b0, x1=b1, fillcolor="rgba(201,133,0,0.13)", line_width=0, row=r, col=1
            )
    fig.add_vrect(
        x0=grid_now - pd.Timedelta(minutes=2),
        x1=grid_now + pd.Timedelta(minutes=2),
        fillcolor=T.HILITE,
        line_width=0,
        row=2,
        col=1,
    )
    fig.update_xaxes(**T.axis(), tickformat="%H:%M")
    fig.update_yaxes(**T.axis())
    fig.update_annotations(font=dict(color=T.INK_2, size=12), x=0, xanchor="left")
    if band is not None:  # after update_annotations, which left-aligns the subplot titles
        b0, b1, lab = band
        fig.add_annotation(
            x=b0 + (b1 - b0) / 2,
            y=0.97,
            yref="y domain",  # inside the PV panel, clear of the subplot titles
            text=lab,
            showarrow=False,
            yanchor="top",
            bgcolor="rgba(26,26,25,0.8)",
            font=dict(color=T.PV, size=11),
        )
    fig.update_layout(
        **T.plotly_layout(
            height=450,
            hovermode="x unified",
            margin=dict(l=8, r=8, t=64, b=8),
            legend=dict(orientation="h", yanchor="bottom", y=1.07, x=0, font=dict(color=T.INK_2)),
        )
    )
    return fig


# --------------------------------------------------------------------------- PV response
def decomposition(rows: pd.DataFrame, model: str) -> go.Figure:
    """Import change over one step, split into the published S1-regression terms."""
    fig = go.Figure()
    for lab, col in (("AC", T.AC), (model, T.colour(model))):
        r = rows[rows.who == lab]
        fig.add_trace(
            go.Bar(
                y=r.driver,
                x=r.mw,
                orientation="h",
                name=T.LABELS[lab],
                marker_color=col,
                marker_line_width=0,
                text=[f"{v:+.1f}" for v in r.mw],
                textposition="outside",
                textfont=dict(color=T.INK_2),
                hovertemplate="%{y}: %{x:+.2f} MW<extra>" + T.SHORT[lab] + "</extra>",
            )
        )
    lo, hi = min(rows.mw.min(), 0), max(rows.mw.max(), 0)
    pad = 0.28 * (hi - lo or 1)
    fig.update_layout(**T.plotly_layout(height=300, barmode="group", bargap=0.35, bargroupgap=0.12))
    fig.update_xaxes(
        **T.axis(
            range=[lo - pad, hi + pad],
            title=dict(text="change in grid import (MW)", font=dict(color=T.MUTED)),
        )
    )
    fig.update_yaxes(**T.axis(autorange="reversed"))
    return fig


def partial_residuals(
    resp: pd.DataFrame, models: list[str], coefs: dict, height: int = 330
) -> go.Figure:
    """Small multiples: import with load and battery effects removed, against PV injection.
    The fitted line is the published PV slope."""
    panels = ["AC", *models]
    fig = make_subplots(
        rows=1,
        cols=len(panels),
        shared_yaxes=True,
        horizontal_spacing=0.025,
        subplot_titles=[f"{T.SHORT[p]}  ·  slope {coefs[p]['pv']:+.2f}" for p in panels],
    )
    x = resp.pv_injection_mw.to_numpy()
    xs = np.linspace(0, 6, 20)
    ylo, yhi = -12, 8
    for i, p in enumerate(panels, start=1):
        y = resp[f"partial_{p}"].to_numpy()  # = slope·PV + OLS residual (zero-mean)
        col = T.colour(p)
        clipped = int(((y < ylo) | (y > yhi)).sum())
        fig.add_trace(
            go.Scattergl(
                x=x,
                y=np.clip(y, ylo, yhi),
                mode="markers",
                marker=dict(size=3, color=col, opacity=0.28),
                showlegend=False,
                hoverinfo="skip",
            ),
            row=1,
            col=i,
        )
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=coefs[p]["pv"] * xs,
                mode="lines",
                line=dict(color=T.INK if p != "AC" else T.PV, width=2.5),
                showlegend=False,
                hoverinfo="skip",
            ),
            row=1,
            col=i,
        )
        if p != "AC":
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=coefs["AC"]["pv"] * xs,
                    mode="lines",
                    line=dict(color=T.PV, width=1.5, dash="dot"),
                    showlegend=False,
                    hoverinfo="skip",
                ),
                row=1,
                col=i,
            )
        if clipped:
            fig.add_annotation(
                text=f"{clipped} pts beyond axis",
                x=0.2,
                y=ylo + 0.6,
                xanchor="left",
                showarrow=False,
                row=1,
                col=i,
                font=dict(color=T.MUTED, size=9),
            )
    fig.update_xaxes(
        **T.axis(
            range=[-0.2, 6.3],
            title=dict(text="HV PV injection (MW)", font=dict(color=T.MUTED, size=10)),
        )
    )
    fig.update_yaxes(**T.axis(range=[ylo, yhi]))
    fig.update_yaxes(
        title=dict(text="import, load & battery removed (MW)", font=dict(color=T.MUTED, size=10)),
        row=1,
        col=1,
    )
    fig.update_annotations(font=dict(color=T.INK_2, size=11))
    fig.update_layout(**T.plotly_layout(height=height, margin=dict(l=8, r=8, t=40, b=8)))
    return fig


def slopes_bars(evo: pd.DataFrame, models: list[str]) -> go.Figure:
    """Import response per MW of each driver: AC vs each model (published S1 OLS)."""
    drivers = [
        ("load", "Load (+1 MW demand)"),
        ("chap31", "Battery (+1 MW CHAP31)"),
        ("pv", "PV (+1 MW injection)"),
    ]
    fig = make_subplots(
        rows=1,
        cols=3,
        shared_yaxes=True,
        horizontal_spacing=0.04,
        subplot_titles=[d for _, d in drivers],
    )
    names = ["AC", *models]
    for i, (k, _) in enumerate(drivers, start=1):
        vals = [evo.iloc[0][f"ac_slope_{k}"]] + [evo.at[m, f"genco_slope_{k}"] for m in models]
        fig.add_trace(
            go.Bar(
                y=[T.SHORT[n] for n in names],
                x=vals,
                orientation="h",
                marker_color=[T.colour(n) for n in names],
                marker_line_width=0,
                text=[f"{v:+.2f}" for v in vals],
                textposition="outside",
                textfont=dict(color=T.INK_2),
                showlegend=False,
                hovertemplate="%{y}: %{x:+.3f} MW per MW<extra></extra>",
            ),
            row=1,
            col=i,
        )
        fig.add_vline(x=vals[0], line=dict(color=T.INK, width=1, dash="dot"), row=1, col=i)
    fig.update_xaxes(**T.axis(range=[-1.6, 2.9]))
    fig.update_yaxes(**T.axis(autorange="reversed"))
    fig.update_annotations(font=dict(color=T.INK_2, size=12))
    fig.update_layout(**T.plotly_layout(height=270, margin=dict(l=8, r=8, t=40, b=8)))
    return fig


def metric_bars(
    evo: pd.DataFrame,
    models: list[str],
    col: str,
    title: str,
    log: bool = False,
    ref: float | None = None,
    fmt: str = ".2f",
) -> go.Figure:
    vals = [float(evo.at[m, col]) for m in models]
    fig = go.Figure(
        go.Bar(
            x=[T.SHORT[m] for m in models],
            y=vals,
            marker_color=[T.colour(m) for m in models],
            marker_line_width=0,
            text=[format(v, fmt) for v in vals],
            textposition="outside",
            textfont=dict(color=T.INK_2),
            hovertemplate="%{x}: %{y:" + fmt + "}<extra></extra>",
            cliponaxis=False,
        )
    )
    if ref is not None:
        fig.add_hline(
            y=ref,
            line=dict(color=T.INK, width=1, dash="dot"),
            annotation_text="AC",
            annotation_font_color=T.INK_2,
            annotation_position="top left",
        )
    fig.update_yaxes(**T.axis(type="log" if log else "linear", **({"dtick": 1} if log else {})))
    fig.update_xaxes(**T.axis())
    fig.update_layout(
        **T.plotly_layout(
            height=240,
            title=dict(text=title, font=dict(color=T.INK, size=13), x=0, xanchor="left"),
            margin=dict(l=8, r=8, t=44, b=8),
        )
    )
    return fig

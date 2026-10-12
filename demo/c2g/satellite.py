"""Satellite panel as plain HTML/CSS: the previous frame underneath, the current frame fading in
on top, and an SVG overlay in the frame's own lon/lat coordinates.

Why HTML instead of Plotly: a Plotly chart remounts on every update, so playback stepped from
image to image. Here each update mounts two stacked images and a CSS cross-fade, so consecutive
15-minute observations dissolve into one another. The cross-fade is a DISPLAY TRANSITION between
two real frames; no intermediate image is synthesised or stored."""

from __future__ import annotations

import base64
from html import escape

import numpy as np
import pandas as pd

from c2g import theme as T

TOWNS = {
    "London": (51.507, -0.128),
    "Leighton Buzzard": (51.917, -0.661),
    "Oxford": (51.752, -1.258),
    "Cambridge": (52.205, 0.122),
    "Birmingham": (52.486, -1.890),
}
STUDY_BOX = {"lat_min": 51.65, "lat_max": 52.25, "lon_min": -1.05, "lon_max": -0.15}
ZOOM_PAD = (0.35, 0.22)
# overlay sits on satellite imagery, not on the page: fixed white marks with a dark halo
OVER_INK = "#ffffff"
OVER_HALO = "#070b14"  # lon, lat margin around the study box when zoomed


def _zoom_transform(bbox: list[float]) -> str:
    """CSS transform that fills the panel with the study box (frame aspect is preserved)."""
    lon0, lat0, lon1, lat1 = bbox
    b, (px, py) = STUDY_BOX, ZOOM_PAD
    zx0, zx1 = b["lon_min"] - px, b["lon_max"] + px
    zy0, zy1 = b["lat_min"] - py, b["lat_max"] + py
    s = min((lon1 - lon0) / (zx1 - zx0), (lat1 - lat0) / (zy1 - zy0))
    cx = ((zx0 + zx1) / 2 - lon0) / (lon1 - lon0) * 100
    cy = (lat1 - (zy0 + zy1) / 2) / (lat1 - lat0) * 100
    return (
        f"transform-origin: {cx:.2f}% {cy:.2f}%; "
        f"transform: translate({50 - cx:.2f}%, {50 - cy:.2f}%) scale({s:.3f});"
    )


def render(
    frame: pd.Series,
    prev: pd.Series | None,
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    assets: pd.DataFrame,
    pv_now: pd.DataFrame | None,
    zoom: bool,
    fade_ms: int = 900,
) -> str:
    lon0, lat0, lon1, lat1 = frame.bbox_wgs84
    w, h = lon1 - lon0, lat1 - lat0
    k = 0.42 if zoom else 1.0  # keep overlay marks the same on-screen size when zoomed
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{lon0} {-lat1} {w} {h}" '
        'preserveAspectRatio="none" font-family="system-ui, sans-serif">'
    ]
    b = STUDY_BOX
    svg.append(
        f'<rect x="{b["lon_min"]}" y="{-b["lat_max"]}" width="{b["lon_max"] - b["lon_min"]}" '
        f'height="{b["lat_max"] - b["lat_min"]}" fill="none" stroke="{OVER_INK}" '
        'stroke-width="1.4" '
        'stroke-dasharray="4 3" vector-effect="non-scaling-stroke"><title>Sundon study area'
        "</title></rect>"
    )
    loc = nodes[nodes.geolocation_status == "resolved"].set_index("bus")
    for e in edges.itertuples():
        if e.bus_a in loc.index and e.bus_b in loc.index:
            a, c = loc.loc[e.bus_a], loc.loc[e.bus_b]
            svg.append(
                f'<line x1="{a.lon}" y1="{-a.lat}" x2="{c.lon}" y2="{-c.lat}" '
                'stroke="rgba(255,255,255,0.8)" stroke-width="1.3" '
                'vector-effect="non-scaling-stroke"/>'
            )
    for r in loc.itertuples():
        svg.append(
            f'<circle cx="{r.lon}" cy="{-r.lat}" r="{0.016 * k}" fill="{OVER_INK}" '
            f'stroke="{OVER_HALO}" stroke-width="0.8" vector-effect="non-scaling-stroke">'
            f"<title>{escape(r.label)} ({r.vn_kv:.0f} kV)</title></circle>"
        )
    if pv_now is not None and len(pv_now):
        a = assets[["asset_id", "lat", "lon"]].merge(pv_now, on="asset_id", how="inner")
        a = a[a.capacity_mw > 0].sort_values("capacity_mw", ascending=False)
        for r in a.itertuples():
            rad = float(np.clip(0.018 + 0.022 * np.sqrt(r.capacity_mw), 0.018, 0.075)) * k
            op = float(
                np.clip(0.25 + (r.capacity_factor if pd.notna(r.capacity_factor) else 0), 0.25, 1)
            )
            svg.append(
                f'<circle cx="{r.lon}" cy="{-r.lat}" r="{rad:.4f}" fill="{T.PV}" '
                f'fill-opacity="{op:.2f}" stroke="{OVER_HALO}" stroke-width="0.8" '
                f'vector-effect="non-scaling-stroke"><title>{escape(r.asset_id)} · '
                f"{r.capacity_mw:.2f} MW installed · est. {r.p_mw:.2f} MW</title></circle>"
            )
    if not zoom:
        for name, (lat, lon) in TOWNS.items():
            svg.append(
                f'<circle cx="{lon}" cy="{-lat}" r="0.018" fill="{OVER_INK}"/>'
                f'<text x="{lon}" y="{-lat - 0.07}" font-size="0.13" text-anchor="middle" '
                f'fill="{OVER_INK}" stroke="{OVER_HALO}" stroke-width="0.035" paint-order="stroke" '
                f'stroke-opacity="0.75">{escape(name)}</text>'
            )
    svg.append("</svg>")
    fade = prev is not None and prev.image_file != frame.image_file
    under = prev.data_uri if fade else frame.data_uri
    top_style = f"animation: c2gfade {fade_ms}ms ease-in-out both;" if fade else ""
    zoom_css = _zoom_transform(frame.bbox_wgs84) if zoom else ""
    return (
        f'<div class="c2g-sat" style="aspect-ratio: {w} / {h};">'
        f'<div class="c2g-sat-inner" style="{zoom_css}">'
        f'<img src="{under}" alt="" class="c2g-sat-img"/>'
        f'<img src="{frame.data_uri}" '
        f'alt="Meteosat E-View {frame.timestamp_utc:%d %b %Y %H:%M} UTC" '
        f'class="c2g-sat-img" style="{top_style}"/>'
        # overlay as an SVG image: st.html's sanitiser drops inline <svg> (no hover titles)
        '<img class="c2g-sat-img" alt="" src="data:image/svg+xml;base64,'
        + base64.b64encode("".join(svg).encode()).decode()
        + '"/></div>'
        f'<div class="c2g-sat-stamp">{frame.timestamp_utc:%H:%M} UTC</div>'
        "</div>"
    )

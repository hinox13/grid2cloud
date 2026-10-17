# ruff: noqa: E501  (figure layout code: long label strings are kept on one line for readability)
"""Build the six submission figures from FROZEN Cloud2Grid outputs only.

    uv run python submission/make_figures.py          # → submission/figures/0*.png

Inputs (read-only): data/demo/ (frozen Explorer bundles: Meteosat E-View frames, satellite-derived
PV, AC reference and GENCO predictions, network schematic, S1 regression partial residuals),
reports/tables/e5d_real_transfer.csv, e5d_response_transfer.csv, e4_family_summary.csv,
docs/screenshots/. Nothing is re-fitted, re-simulated or predicted here. Sources per figure:
submission/FIGURE_SOURCES.md.

Typeface: the Explorer's Source Sans, if static TTFs are provided in $C2G_FONT_DIR (otherwise
DejaVu Sans). Colours: the Explorer's light palette (demo/c2g/theme.py).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates  # noqa: E402
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager as fm  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "submission/figures"
DEMO = ROOT / "data/demo"
EV = DEMO / "events/jun15_cloud_clearing"
TABLES = ROOT / "reports/tables"
DPI = 200

# ---------------------------------------------------------------- style (Explorer light palette)
INK, INK_2, MUTED = "#0f172a", "#3b4659", "#5f6b84"
GRID, AXIS, BORDER = "#e7ecf3", "#c9d2df", "#d5dbe5"
PAGE, SURFACE = "#f5f7fb", "#ffffff"
ACCENT, ACCENT_TEXT = "#f5a524", "#b45309"
PV, BATT = "#c98500", "#4a3aa7"
COL = {
    "AC": INK,
    "zero_shot": "#eb6834",
    "E5": "#e87ba4",
    "E5b": "#1baf7a",
    "E5c": "#2a78d6",
    "E5d": "#751e5f",
}
NAME = {
    "AC": "AC reference",
    "zero_shot": "Off-the-shelf",
    "E5": "Grid-tuned",
    "E5b": "Envelope-tuned",
    "E5c": "Generator-aware",
    "E5d": "Response-aware",
}
EXP = {"zero_shot": "E4", "E5": "E5", "E5b": "E5b", "E5c": "E5c", "E5d": "E5d"}
ROW = {"zero-shot (E4)": "zero_shot", "E5": "E5", "E5b": "E5b", "E5c": "E5c", "E5d": "E5d"}
MODELS = ["zero_shot", "E5", "E5b", "E5c", "E5d"]
LOADING = LinearSegmentedColormap.from_list("loading", ["#f1e4cc", "#e09b2d", "#9a5800"])
STUDY_BOX = (-1.05, 51.65, -0.15, 52.25)  # demo/c2g/satellite.py STUDY_BOX (lon0, lat0, lon1, lat1)
TOWNS = {"London": (51.507, -0.128), "Oxford": (51.752, -1.258), "Cambridge": (52.205, 0.122)}


def setup_fonts() -> None:
    d = os.environ.get("C2G_FONT_DIR")
    family = "DejaVu Sans"
    if d and Path(d).is_dir():
        for f in sorted(Path(d).glob("*.ttf")):
            fm.fontManager.addfont(str(f))
        family = fm.FontProperties(fname=str(next(Path(d).glob("*Regular.ttf")))).get_name()
    plt.rcParams.update(
        {
            "axes.unicode_minus": True,
            "font.family": family,
            "font.size": 13,
            "axes.edgecolor": AXIS,
            "axes.labelcolor": INK_2,
            "axes.titlecolor": INK,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 1.0,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
        }
    )


def um(text: str) -> str:
    """Typographic minus for numbers in text ("-0.04" → "−0.04")."""
    return re.sub(r"(?<![\w.])-(?=\d)", "−", text)


def badge(ax: plt.Axes, x: float, y: float, text: str, fc: str = SURFACE, ec: str = AXIS,
          color: str = INK_2, size: float = 10.5, ha: str = "left") -> None:  # fmt: skip
    ax.text(
        x, y, text, transform=ax.transAxes, ha=ha, va="center", fontsize=size, color=color,
        fontweight="semibold",
        bbox=dict(boxstyle="round,pad=0.32,rounding_size=0.6", fc=fc, ec=ec, lw=1),
    )  # fmt: skip


def title_block(fig: plt.Figure, title: str, subtitle: str, y: float = 0.955) -> None:
    fig.text(0.035, y, title, fontsize=24, fontweight="bold", color=INK, va="top")
    fig.text(0.035, y - 0.062, subtitle, fontsize=14, color=INK_2, va="top")


def save(fig: plt.Figure, name: str, dpi: int = DPI) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    fig.savefig(p, dpi=dpi)
    plt.close(fig)
    return p


def real_transfer() -> pd.DataFrame:
    t = pd.read_csv(TABLES / "e5d_real_transfer.csv")
    t["model"] = t.model.map(ROW)
    r = pd.read_csv(TABLES / "e5d_response_transfer.csv")
    r["model"] = r.model.map(ROW)
    t = t.set_index("model")
    r = r.set_index("model").reindex(t.index)
    for c in ("pv_response_error_mw", "ac_slope_load", "genco_slope_load"):  # equal in both tables
        assert np.allclose(t[c], r[c]), c
    return t


def frames() -> pd.DataFrame:
    return pd.read_parquet(EV / "satellite/frames.parquet")


def show_frame(ax: plt.Axes, row: pd.Series, crop: tuple, label: str | None = None) -> None:
    """A real E-View frame in its own plate carrée extent (as served by EUMETView WMS)."""
    img = Image.open(EV / row.image_file)
    lon0, lat0, lon1, lat1 = row.bbox_wgs84
    ax.imshow(img, extent=[lon0, lon1, lat0, lat1], interpolation="lanczos")
    x0, y0, x1, y1 = crop
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect(1 / np.cos(np.radians((y0 + y1) / 2)))
    b = STUDY_BOX
    ax.plot([b[0], b[2], b[2], b[0], b[0]], [b[1], b[1], b[3], b[3], b[1]], color="white",
            lw=1.6, ls=(0, (4, 3)))  # fmt: skip
    halo = [pe.withStroke(linewidth=3, foreground="#070b14")]
    for name, (la, lo) in TOWNS.items():
        if x0 < lo < x1 and y0 < la < y1:
            ax.plot(lo, la, "o", ms=4, color="white", mec="#070b14", mew=0.8)
            ax.text(lo, la + 0.07, name, color="white", fontsize=10, ha="center",
                    path_effects=halo)  # fmt: skip
    if label:
        ax.text(0.03, 0.06, label, transform=ax.transAxes, color="white", fontsize=11.5,
                fontweight="semibold",
                bbox=dict(boxstyle="round,pad=0.25", fc="#070b14", ec="none", alpha=0.75))  # fmt: skip
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(True)
        s.set_color(BORDER)


def schematic(ax: plt.Axes, t: pd.Timestamp) -> None:
    """The Explorer's manual network schematic (configs/app/network_layout.yaml), AC state at t:
    width ∝ |P|, colour = loading %. NOT a map."""
    nodes = pd.read_parquet(EV / "network_nodes.parquet").set_index("bus")
    edges = pd.read_parquet(EV / "network_edges.parquet")
    br = pd.read_parquet(EV / "ac_reference_branches.parquet")
    br = br[br.timestamp_utc == t].set_index("branch_id")
    lay = json.loads((DEMO / "network_layout.json").read_text())
    bars = {b: lay["busbars"][k]["y"] for b, k in nodes.node_key.items() if k in lay["busbars"]}
    for band in lay["bands"]:
        ax.axhspan(band["y0"], band["y1"], color=GRID if band["label"] != "33 kV" else SURFACE,
                   alpha=0.55, lw=0, zorder=0)  # fmt: skip
        ax.text(-8.25, (band["y0"] + band["y1"]) / 2, band["label"], fontsize=10, color=MUTED,
                ha="left", va="center", fontweight="semibold")  # fmt: skip
    xs = {b: [nodes.at[b, "schematic_x"]] for b in bars}
    for e in edges.itertuples():
        xa, ya = nodes.loc[e.bus_a, ["schematic_x", "schematic_y"]]
        xb, yb = nodes.loc[e.bus_b, ["schematic_x", "schematic_y"]]
        if e.bus_a in bars:
            xa, ya = xb, bars[e.bus_a]
            xs[e.bus_a].append(xb)
        if e.bus_b in bars:
            xb, yb = xa, bars[e.bus_b]
            xs[e.bus_b].append(xa)
        if e.branch_id not in br.index:
            ax.plot([xa, xb], [ya, yb], color=AXIS, lw=1, ls=":", zorder=1)
            continue
        p, load = float(br.at[e.branch_id, "p_ab_mw"]), float(br.at[e.branch_id, "loading_pct"])
        w = 1.2 + 5.0 * np.sqrt(min(abs(p), 120) / 120)
        ax.plot([xa, xb], [ya, yb], color=LOADING(np.clip(load / 100, 0, 1)), lw=w,
                solid_capstyle="round", zorder=2)  # fmt: skip
    for b, y in bars.items():
        ax.plot([min(xs[b]) - 0.15, max(xs[b]) + 0.15], [y, y], color=INK_2, lw=4, zorder=3,
                solid_capstyle="butt")  # fmt: skip
    for b, r in nodes.iterrows():
        if b in bars:
            continue
        if r.role == "battery_33kv":
            ax.plot(r.schematic_x, r.schematic_y, "s", ms=7, color=BATT, zorder=4)
        elif "LBUZ3" in r.node_key and r.vn_kv == 33 and r.node_key[-1] in "123":
            ax.plot(r.schematic_x, r.schematic_y, "o", ms=7.5, color=PV, mec="white", mew=1,
                    zorder=4)  # fmt: skip
        else:
            ax.plot(r.schematic_x, r.schematic_y, "o", ms=4.2, color="#5a6680", zorder=4)
    ax.set_xlim(-8.35, 4.4)
    ax.set_ylim(-1.5, 4.55)
    ax.plot([], [], "o", ms=7.5, color=PV, mec="white", label="PV (33 kV)")
    ax.plot([], [], "s", ms=7, color=BATT, label="battery")
    ax.plot([], [], color=INK_2, lw=4, label="busbar")
    ax.legend(
        loc="upper right",
        bbox_to_anchor=(1.0, 1.0),
        fontsize=9.5,
        frameon=False,
        handlelength=1.2,
        borderaxespad=0.2,
    )
    ax.axis("off")


# ---------------------------------------------------------------- Figure 1
def fig1() -> Path:
    fr = frames().set_index("timestamp_utc")
    t_a, t_b = pd.Timestamp("2024-06-15 09:00Z"), pd.Timestamp("2024-06-15 11:30Z")
    fleet = pd.read_parquet(EV / "fleet_pv.parquet")
    summ = pd.read_parquet(EV / "summary.parquet")
    meta = json.loads((EV / "metadata.json").read_text())
    cap = float(meta["active_pv_capacity_mw"])

    fig = plt.figure(figsize=(16, 8.2))
    title_block(
        fig,
        "Cloud2Grid",
        "Real clouds → solar power → a real power grid → GENCO.   15 June 2024: a cloud deck "
        "clears over Sundon (UK Power Networks).",
    )
    lefts = [0.035, 0.285, 0.525, 0.765]
    w, bottom, h = 0.205, 0.17, 0.60
    heads = [
        ("1  Real clouds", "OBSERVED"),
        ("2  Solar power", "DERIVED"),
        ("3  Power grid", "SIMULATED"),
        ("4  GENCO", "PREDICTED"),
    ]
    for i, (x, (head, kind)) in enumerate(zip(lefts, heads, strict=True)):
        fig.text(x, 0.815, head, fontsize=17, fontweight="bold", color=INK, va="center")
        fig.text(x + w, 0.815, kind, fontsize=10, fontweight="semibold", color=INK_2,
                 ha="right", va="center",
                 bbox=dict(boxstyle="round,pad=0.35,rounding_size=0.7", fc=SURFACE, ec=AXIS))  # fmt: skip
        if i < 3:
            fig.patches.append(
                FancyArrowPatch(
                    (x + w + 0.008, bottom + h / 2),
                    (lefts[i + 1] - 0.012, bottom + h / 2),
                    transform=fig.transFigure,
                    arrowstyle="-|>",
                    mutation_scale=22,
                    color=ACCENT,
                    lw=2.4,
                )  # fmt: skip
            )
    # 1 — two real frames, before / after
    crop = (-2.25, 50.95, 1.15, 52.95)
    a1 = fig.add_axes([lefts[0], bottom + h / 2 + 0.01, w, h / 2 - 0.01])
    a2 = fig.add_axes([lefts[0], bottom, w, h / 2 - 0.01])
    show_frame(a1, fr.loc[t_a], crop, f"{t_a:%H:%M} UTC")
    show_frame(a2, fr.loc[t_b], crop, f"{t_b:%H:%M} UTC")
    fig.text(lefts[0], bottom - 0.045, "Meteosat E-View imagery (EUMETSAT).\nDashed box: Sundon "
             "study area. Bright = cloud.", fontsize=10.5, color=MUTED, va="top")  # fmt: skip
    # 2 — satellite-derived PV
    a = fig.add_axes([lefts[1] + 0.03, bottom + 0.02, w - 0.03, h - 0.04])
    x = fleet.timestamp_utc
    a.fill_between(x, fleet.fleet_pv_mw, color=PV, alpha=0.18, lw=0)
    a.plot(x, fleet.fleet_pv_mw, color=PV, lw=2.6, marker="o", ms=4.5)
    a.axhline(cap, color=MUTED, lw=1, ls=(0, (4, 3)))
    a.text(x.iloc[0], cap + 0.25, f"2024 PV fleet capacity {cap:.1f} MW", fontsize=10,
           color=MUTED)  # fmt: skip
    a.set_ylim(0, 10.5)
    a.set_ylabel("Estimated PV output (MW)")
    a.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%H:%M"))
    a.set_xticks(pd.to_datetime(["2024-06-15 09:00Z", "2024-06-15 10:30Z", "2024-06-15 12:00Z"]))
    fig.text(lefts[1], bottom - 0.045, "LSA SAF surface radiation at every PV asset → pvlib.\n"
             "Every 15 min. An estimate, not metered.", fontsize=10.5, color=MUTED, va="top")  # fmt: skip
    # 3 — AC power flow on the schematic
    a = fig.add_axes([lefts[2] - 0.012, bottom, w + 0.024, h])
    schematic(a, t_b)
    fig.text(lefts[2], bottom - 0.045, f"Full AC power flow, {t_b:%H:%M} grid state. Line colour =\n"
             "loading, width = flow. Schematic, not a map.", fontsize=10.5, color=MUTED, va="top")  # fmt: skip
    # 4 — GENCO vs AC grid import
    a = fig.add_axes([lefts[3] + 0.035, bottom + 0.02, w - 0.035, h - 0.04])
    for m, lw in (("AC", 3.0), ("E5c", 2.2), ("E5d", 2.2)):
        s = summ[summ.model == m].sort_values("timestamp_utc")
        a.plot(s.timestamp_utc, s.import_mw, color=COL[m], lw=lw, marker="o", ms=5,
               label=NAME[m], zorder=3 if m == "AC" else 2)  # fmt: skip
    a.set_ylabel("Grid import at Sundon (MW)")
    a.set_ylim(25, 80)
    a.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%H:%M"))
    a.set_xticks(pd.to_datetime(["2024-06-15 09:00Z", "2024-06-15 10:30Z", "2024-06-15 12:00Z"]))
    a.legend(loc="upper right", fontsize=10, frameon=False, handlelength=1.4)
    fig.text(lefts[3], bottom - 0.045, "Frozen GENCO checkpoints on the same\nhalf-hourly grid "
             "states as the AC reference.", fontsize=10.5, color=MUTED, va="top")  # fmt: skip
    fig.text(0.035, 0.03, "All panels: frozen Cloud2Grid Explorer bundle (event B02/D01). AC = "
             "simulated physical reference, not a measurement. Contains modified EUMETSAT data "
             "and UK Power Networks data (CC BY 4.0).", fontsize=10, color=MUTED)  # fmt: skip
    return save(fig, "01_cloud2grid_overview.png")


# ---------------------------------------------------------------- Figure 2
JOURNEY = [  # (model, label, what changed, key result, remaining limitation) — frozen reports
    ("zero_shot", "Zero-shot", "Published GENCO checkpoint on conventional synthetic Sundon states",
     "Fails before weather: active residual {s0:.1f} MW vs {s0dc:.3f} MW for DC power flow "
     "({s0x:.0f}×)",
     "Topology transfer"),
    ("E5", "Standard synthetic fine-tuning", "Official recipe on standard synthetic Sundon states",
     "Held-out synthetic error 44.8 → 0.47 MVA",
     "Real states stay at {pbe_E5:.1f} MVA: outside the synthetic support"),
    ("E5b", "Broader operating envelope", "Synthetic states spanning the physical range, from "
     "published metadata only",
     "Real-state error {pbe_E5:.1f} → {pbe_E5b:.3f} MVA (−99.0 %)",
     "Import and voltage tracking fail; PV slope {pv_E5b:+.2f}"),
    ("E5c", "Explicit generators", "PV as explicit generator nodes in GENCO's graph",
     "Import r {r_E5c:.2f}; battery slope {bat_E5c:.2f} (AC {bat_AC:.2f})",
     "Almost blind to PV: slope {pv_E5c:+.2f} vs AC {pv_AC:+.2f}"),
    ("E5d", "Physics-response-aware training", "New loss on paired synthetic AC states (one "
     "input changed)",
     "PV slope {pv_E5d:+.2f} vs AC {pv_AC:+.2f}; load {load_E5d:.2f} (AC {load_AC:.2f})",
     "Import bias {bias_E5d:+.1f} MW, Vm MAE {vm_E5d:.4f} pu (> 0.010), battery {bat_E5d:.2f}: "
     "partial (E5D-D)"),
]  # fmt: skip


def journey_values() -> dict:
    t = real_transfer()
    s0 = (
        pd.read_csv(TABLES / "e4_family_summary.csv")
        .set_index("family")
        .loc["S0_STANDARD_SYNTHETIC"]
    )
    v = {"s0": s0.P_residual, "s0dc": s0.dc_P_residual, "s0x": s0.genco_vs_dc_active_ratio,
         "pv_AC": t.iloc[0].ac_slope_pv, "bat_AC": t.iloc[0].ac_slope_chap31,
         "load_AC": t.iloc[0].ac_slope_load}  # fmt: skip
    for m in MODELS:
        r = t.loc[m]
        v |= {f"pbe_{m}": r.PBE_mean, f"pv_{m}": r.genco_slope_pv, f"r_{m}": r.import_corr,
              f"bat_{m}": r.genco_slope_chap31, f"load_{m}": r.genco_slope_load,
              f"bias_{m}": r.import_bias_mw, f"vm_{m}": r.V_error}  # fmt: skip
    return v


def fig2() -> Path:
    v = journey_values()
    t = real_transfer()
    fig = plt.figure(figsize=(16, 10.9))
    title_block(fig, "Five experiments, five different failure modes",
                "Each stage fixed one limitation and exposed the next. Real-state numbers: the same "
                "2,829 held-out 2024 operating states for every model.")  # fmt: skip
    top, row_h, gap = 0.80, 0.132, 0.016
    x_card, w_card = 0.035, 0.60
    x_pbe, w_pbe = 0.665, 0.145
    x_pv, w_pv = 0.835, 0.135
    fig.text(x_card + 0.012, top + 0.022, "Stage  ·  key result  ·  remaining limitation",
             fontsize=12, color=MUTED, fontweight="semibold")  # fmt: skip
    fig.text(x_pbe + w_pbe / 2, top + 0.022, "Real-state error\n(PBE, MVA, log)", fontsize=11.5,
             color=MUTED, fontweight="semibold", ha="center", va="bottom")  # fmt: skip
    fig.text(x_pv + w_pv / 2, top + 0.022, "PV → import response\n(MW per MW)", fontsize=11.5,
             color=MUTED, fontweight="semibold", ha="center", va="bottom")  # fmt: skip
    for i, (m, label, changed, key, limit) in enumerate(JOURNEY):
        y = top - (i + 1) * row_h - i * gap
        ax = fig.add_axes([x_card, y, w_card, row_h])
        ax.set_axis_off()
        ax.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0,rounding_size=0.06",
                                    transform=ax.transAxes, fc=SURFACE, ec=BORDER, lw=1.2))  # fmt: skip
        ax.add_patch(
            FancyBboxPatch(
                (0.0, 0.0),
                0.012,
                1,
                boxstyle="round,pad=0,rounding_size=0.01",
                transform=ax.transAxes,
                fc=COL[m],
                ec="none",
            )
        )
        ax.text(0.03, 0.80, f"{EXP[m]}", fontsize=11, color=MUTED, fontweight="semibold",
                transform=ax.transAxes, va="center")  # fmt: skip
        ax.text(0.085, 0.80, f"{label}", fontsize=15.5, color=INK, fontweight="bold",
                transform=ax.transAxes, va="center")  # fmt: skip
        ax.text(0.99, 0.80, f"{NAME[m]} GENCO", fontsize=11, color=MUTED, ha="right",
                transform=ax.transAxes, va="center")  # fmt: skip
        ax.text(0.085, 0.555, changed, fontsize=11.5, color=INK_2, transform=ax.transAxes,
                va="center", style="italic")  # fmt: skip
        ax.text(0.085, 0.33, "✓  " + um(key.format(**v)), fontsize=12.5, color=INK,
                transform=ax.transAxes, va="center")  # fmt: skip
        ax.text(0.085, 0.115, "✗  " + um(limit.format(**v)), fontsize=12.5, color=ACCENT_TEXT,
                transform=ax.transAxes, va="center")  # fmt: skip
        # PBE on a shared log axis (non-monotonic on purpose: it is the data)
        a = fig.add_axes([x_pbe, y + 0.02, w_pbe, row_h - 0.04])
        a.set_xscale("log")
        a.set_xlim(0.2, 80)
        a.set_ylim(-1, 1)
        a.set_yticks([])
        a.grid(axis="y", visible=False)
        a.axhline(0, color=GRID, lw=6, solid_capstyle="round", zorder=0)
        pbe = t.at[m, "PBE_mean"]
        a.plot(pbe, 0, "o", ms=13, color=COL[m], mec="white", mew=1.8, zorder=3)
        a.text(
            pbe,
            0.62,
            f"{pbe:.3g}",
            ha="center",
            fontsize=12,
            color=INK,
            fontweight="semibold",
            bbox=dict(fc=SURFACE, ec="none", pad=0.6),
        )
        a.set_xticks([0.3, 1, 3, 10, 30])
        a.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{x:g}"))
        a.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())
        a.spines["left"].set_visible(False)
        a.tick_params(axis="x", labelsize=10)
        if i < len(JOURNEY) - 1:
            a.set_xticklabels([])
        # PV slope with the AC reference
        b = fig.add_axes([x_pv, y + 0.02, w_pv, row_h - 0.04])
        b.set_xlim(-1.35, 0.25)
        b.set_ylim(-1, 1)
        b.set_yticks([])
        b.grid(axis="y", visible=False)
        b.axhline(0, color=GRID, lw=6, solid_capstyle="round", zorder=0)
        ac = t.iloc[0].ac_slope_pv
        b.axvline(ac, color=INK, lw=1.4, ls=(0, (3, 2)), zorder=1)
        pv = t.at[m, "genco_slope_pv"]
        b.plot(pv, 0, "o", ms=13, color=COL[m], mec="white", mew=1.8, zorder=3)
        b.text(
            pv,
            0.62,
            um(f"{pv:+.2f}"),
            ha="center",
            fontsize=12,
            color=INK,
            fontweight="semibold",
            bbox=dict(fc=SURFACE, ec="none", pad=0.6),
            zorder=4,
        )
        b.spines["left"].set_visible(False)
        b.tick_params(axis="x", labelsize=10)
        if i == 0:
            b.text(ac, -0.95, "AC −1.02", fontsize=10, color=INK, ha="center", va="bottom",
                   bbox=dict(fc=SURFACE, ec="none", pad=1))  # fmt: skip
        if i < len(JOURNEY) - 1:
            b.set_xticklabels([])
    fig.text(0.035, 0.012,
             "E4 result on conventional synthetic Sundon states (S0, 2,297 states); all other numbers "
             "on the real states. E5's PV slope (−0.66) comes with import r 0.11: not a usable "
             "response. No stage passes the full pre-registered real-transfer gate.",
             fontsize=10.5, color=MUTED)  # fmt: skip
    return save(fig, "02_transfer_learning_journey.png")


# ---------------------------------------------------------------- Figure 3
def fig3() -> Path:
    resp = pd.read_parquet(DEMO / "pv_response_s1.parquet")
    co = json.loads((DEMO / "catalog.json").read_text())["ols_coefficients_s1"]
    t = real_transfer()
    fig = plt.figure(figsize=(16, 8.6))
    title_block(fig, "PV response on real states: GENCO learns how the grid responds to solar power",
                "One extra MW of PV should lower the grid import by about one MW. Each dot is one of "
                "2,829 held-out 2024 operating states; load and battery effects removed.")  # fmt: skip
    panels = [("AC", "Physics reference (AC power flow)"), ("E5c", "Generator-aware GENCO (E5c)"),
              ("E5d", "Response-aware GENCO (E5d)")]  # fmt: skip
    x = resp.pv_injection_mw.to_numpy()
    xs = np.linspace(0, 6, 20)
    lo, hi = -12, 8
    w, gap, left, bottom, h = 0.275, 0.032, 0.09, 0.27, 0.50
    for i, (m, title) in enumerate(panels):
        a = fig.add_axes([left + i * (w + gap), bottom, w, h])
        y = resp[f"partial_{m}"].to_numpy()
        a.scatter(x, np.clip(y, lo, hi), s=7, color=COL[m], alpha=0.28, lw=0, rasterized=True)
        if m != "AC":
            a.plot(xs, co["AC"]["pv"] * xs, color=PV, lw=2, ls=(0, (4, 3)), label="AC slope")
        a.plot(xs, co[m]["pv"] * xs, color=INK if m != "AC" else PV, lw=3,
               label="model slope" if m != "AC" else "AC slope")  # fmt: skip
        a.set_ylim(lo, hi)
        a.set_xlim(-0.2, 6.3)
        a.set_xlabel("HV PV injection (MW)")
        if i == 0:
            a.set_ylabel("Grid import, load & battery\neffects removed (MW)")
        else:
            a.set_yticklabels([])
        a.set_title(title, fontsize=14, fontweight="semibold", loc="left", color=INK, pad=30)
        a.text(0.0, 1.035, um(f"slope {co[m]['pv']:+.2f} MW per MW"), transform=a.transAxes,
               fontsize=13, color=COL[m] if m != "AC" else INK, fontweight="bold")  # fmt: skip
        n_out = int(((y < lo) | (y > hi)).sum())
        a.text(0.02, 0.03, f"{n_out} states beyond the axis", transform=a.transAxes, fontsize=10,
               color=MUTED)  # fmt: skip
        if m != "AC":
            a.legend(loc="upper right", fontsize=10.5, frameon=False, handlelength=1.8)
    # metric strip
    ax = fig.add_axes([0.06, 0.035, 0.92, 0.12])
    ax.set_axis_off()
    e5c, e5d = t.loc["E5c"], t.loc["E5d"]
    cells = [
        ("PV → import slope", um(f"{e5c.genco_slope_pv:+.2f}  →  {e5d.genco_slope_pv:+.2f}"),
         um(f"MW per MW · AC {e5d.ac_slope_pv:+.2f}")),
        ("PV-attributed import error", f"{e5c.pv_response_error_mw:.2f}  →  {e5d.pv_response_error_mw:.2f} MW",
         "|slope error| × mean PV injection"),
        ("Load → import slope", f"{e5c.genco_slope_load:.2f}  →  {e5d.genco_slope_load:.2f}",
         f"MW per MW · AC {e5d.ac_slope_load:.2f}"),
    ]  # fmt: skip
    cw = 0.235
    for k, (lab, val, sub) in enumerate(cells):
        x0 = k * (cw + 0.012)
        ax.add_patch(FancyBboxPatch((x0, 0), cw, 1, boxstyle="round,pad=0,rounding_size=0.08",
                                    transform=ax.transAxes, fc=SURFACE, ec=BORDER, lw=1.2))  # fmt: skip
        ax.text(x0 + 0.012, 0.78, lab + "  (E5c → E5d)", fontsize=11, color=INK_2,
                transform=ax.transAxes, va="center")  # fmt: skip
        ax.text(x0 + 0.012, 0.45, val, fontsize=19, color=INK, fontweight="bold",
                transform=ax.transAxes, va="center")  # fmt: skip
        ax.text(x0 + 0.012, 0.14, sub, fontsize=10.5, color=MUTED, transform=ax.transAxes,
                va="center")  # fmt: skip
    x0 = 3 * (cw + 0.012)
    ax.add_patch(FancyBboxPatch((x0, 0), 1 - x0, 1, boxstyle="round,pad=0,rounding_size=0.08",
                                transform=ax.transAxes, fc="#fff7ea", ec=ACCENT, lw=1.6))  # fmt: skip
    ax.text(x0 + 0.012, 0.72, "Physical sensitivity recovered;", fontsize=12.5, color=ACCENT_TEXT,
            fontweight="bold", transform=ax.transAxes, va="center")  # fmt: skip
    ax.text(x0 + 0.012, 0.47, "full real-grid calibration incomplete.", fontsize=12.5,
            color=ACCENT_TEXT, fontweight="bold", transform=ax.transAxes, va="center")  # fmt: skip
    ax.text(x0 + 0.012, 0.18, um(f"E5d import bias {e5d.import_bias_mw:+.1f} MW · verdict E5D-D (partial)"),
            fontsize=10.5, color=INK_2, transform=ax.transAxes, va="center")  # fmt: skip
    return save(fig, "03_pv_response_real_states.png")


# ---------------------------------------------------------------- Figure 4
def fig4() -> Path:
    t = real_transfer()
    dc = float(t.iloc[0].dc_P_residual)
    fig = plt.figure(figsize=(16, 8.4))
    title_block(fig, "Real-state transfer: different stages fix different things",
                "Frozen checkpoints on the same 2,829 held-out 2024 operating states. Lower is better "
                "except correlation. Log scales where values span orders of magnitude.")  # fmt: skip
    specs = [
        ("PBE_mean", "Power-balance error (MVA)", True, None, "{:.3g}"),
        ("P_residual", "Active-power residual (MW)", True, (dc, f"DC power flow {dc:.3f}"), "{:.3g}"),
        ("import_mae_mw", "Grid-import error, MAE (MW)", True, (5.0, "gate ≤ 5"), "{:.3g}"),
        ("import_corr", "Grid-import correlation with AC", False, (0.9, "gate ≥ 0.9"), "{:.2f}"),
    ]  # fmt: skip
    ys = np.arange(len(MODELS))[::-1]
    for k, (col, title, log, ref, fmt) in enumerate(specs):
        a = fig.add_axes([0.13 + k * 0.218, 0.20, 0.17, 0.58])
        vals = [float(t.at[m, col]) for m in MODELS]
        base = 0.05 if log else 0
        a.barh(ys, [v - base for v in vals], left=base, height=0.62,
               color=[COL[m] for m in MODELS], zorder=2)  # fmt: skip
        if log:
            a.set_xscale("log")
            a.set_xlim(0.05, 2000)
            a.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{x:g}"))
        else:
            a.set_xlim(0, 1.18)
        for yv, v in zip(ys, vals, strict=True):
            xt = (
                v * 1.18
                if log
                else (ref[0] + 0.02 if ref and ref[0] - 0.06 < v < ref[0] else v + 0.02)
            )
            a.text(xt, yv, fmt.format(v),
                   va="center", fontsize=12, color=INK, fontweight="semibold", zorder=4,
                   bbox=dict(fc=SURFACE, ec="none", pad=0.8, alpha=0.9))  # fmt: skip
        if ref:
            a.axvline(ref[0], color=INK_2, lw=1.4, ls=(0, (3, 2)), zorder=3)
            a.text(ref[0], len(MODELS) - 0.45, ref[1], fontsize=10, color=INK_2, ha="center",
                   bbox=dict(fc=SURFACE, ec="none", pad=1))  # fmt: skip
        a.set_title(title, fontsize=13, fontweight="semibold", loc="left", color=INK, pad=14)
        a.set_yticks(ys)
        a.set_yticklabels([f"{NAME[m]} ({EXP[m]})" for m in MODELS] if k == 0 else [], fontsize=12)
        a.grid(axis="y", visible=False)
        a.set_ylim(-0.6, len(MODELS) - 0.2)
        if log:
            a.set_xlabel("log scale", fontsize=10, color=MUTED)
    fig.text(0.035, 0.085,
             "E5b has the lowest power-balance error; E5c the best import spread and battery "
             "response; E5d the only physical PV and load sensitivity, but a +13.1 MW import bias.",
             fontsize=12.5, color=INK)  # fmt: skip
    fig.text(0.035, 0.045,
             "No stage passes the full pre-registered real-transfer gate (E5d fails the import, "
             "voltage and battery criteria: verdict E5D-D, partial). AC = simulated reference.",
             fontsize=11, color=MUTED)  # fmt: skip
    return save(fig, "04_real_transfer_performance.png")


# ---------------------------------------------------------------- Figure 5
# Explorer captures (light theme, 2x pixel density); see FIGURE_SOURCES.md
SHOTS = ROOT / "submission/screenshots"


def fig5() -> Path:
    """The Explorer as it is deployed: three screenshots, no data drawn here."""
    W, H = 16.0, 10.9  # inches
    fig = plt.figure(figsize=(W, H))
    title_block(fig, "Try it: the Cloud2Grid Explorer",
                "cloud2grid.streamlit.app · a guided tour of the 15 June 2024 cloud clearing, the "
                "four fine-tuning steps, and every model on three real weather events.",
                y=0.962)  # fmt: skip
    m, gap, top, cap = 0.55, 0.35, 1.55, 0.42  # margins / gaps / title band / caption band (in)
    shots = {k: Image.open(SHOTS / f).convert("RGB") for k, f in (
        ("A", "explorer_guided_tour_slide6.png"), ("B", "explorer_overview_top.png"),
        ("C", "explorer_story_steps.png"))}  # fmt: skip
    asp = {k: im.size[1] / im.size[0] for k, im in shots.items()}
    # both columns end level: L·aA = R·(aB + aC) + cap + 0.05, with L + R = W − 2m − gap
    T = W - 2 * m - gap
    R = (T * asp["A"] - cap - 0.05) / (asp["A"] + asp["B"] + asp["C"])
    L = T - R
    hA = L * asp["A"]

    def panel(k: str, x: float, y_top: float, w: float, label: str) -> float:
        h = w * asp[k]
        fig.text(x / W, 1 - (y_top + 0.06) / H, f"{k}  {label}", fontsize=12.5, color=INK,
                 fontweight="semibold", va="top")  # fmt: skip
        ax = fig.add_axes([x / W, 1 - (y_top + cap + h) / H, w / W, h / H])
        ax.imshow(shots[k], interpolation="lanczos")
        ax.set_axis_off()
        ax.add_patch(Rectangle((0, 0), shots[k].size[0] - 1, shots[k].size[1] - 1, fill=False,
                               ec=BORDER, lw=1.2))  # fmt: skip
        return y_top + cap + h

    panel("A", m, top, L, "Guided tour: six captioned slides, here the last one (11:30 UTC)")
    yb = panel("B", m + L + gap, top, R, "Overview: the question and the four steps")
    panel("C", m + L + gap, yb + 0.05, R, "Scientific story: step cards and solar response")
    fig.text(m / W, 1 - (top + cap + hA + 0.22) / H,
             "Screenshots of the deployed app (light theme). The app replays frozen results only: "
             "no power flow, inference or download runs in it. AC = simulated reference.",
             fontsize=10.5, color=MUTED, va="top")  # fmt: skip
    return save(fig, "05_explorer_hero_event.png", dpi=160)  # photographic content: smaller file


# ---------------------------------------------------------------- Figure 6 (E6 diagnostic)
def fig6() -> Path:
    """Post-hoc E6 diagnostic, held-out SYNTHETIC only (reports/e6_feasibility_diagnostic.md).
    Inputs: reports/tables/e6_import_states_e5d.csv, e6_pv_pairs_e5d.csv,
    e6_pair_level_cancellation.csv, e6_model_comparison.csv and
    reports/experiments/e6_feasibility/diagnostic.json. Every annotation is computed here."""
    S = pd.read_csv(TABLES / "e6_import_states_e5d.csv")
    P = pd.read_csv(TABLES / "e6_pv_pairs_e5d.csv")
    pc = pd.read_csv(TABLES / "e6_pair_level_cancellation.csv")
    cmp_ = pd.read_csv(TABLES / "e6_model_comparison.csv")
    diag = json.loads((ROOT / "reports/experiments/e6_feasibility/diagnostic.json").read_text())
    row = cmp_[(cmp_.population == "E5c held-out synthetic test") & (cmp_.model == "E5d λ1 s0 (frozen)")].iloc[0]
    pv = pc[(pc.model == "E5d λ1 s0 (frozen)") & (pc.probe_type == "pv")].iloc[0]
    b, a = np.polyfit(S.ac_import, S.pred_import, 1)
    fixed = a / (1 - b)
    train_mean = diag["train_coverage"]["import_mean_mw"]
    mae = (S.pred_import - S.ac_import).abs().mean()
    r_pair = np.corrcoef(P.err_A, P.err_B)[0, 1]
    lvl, dch, dac = pv.level_mae_member_A_mw, pv.delta_err_mae_mw, pv.mean_abs_delta_ac_mw

    fig = plt.figure(figsize=(16, 8.6))
    title_block(fig, "Why response supervision is not enough",
                "Held-out synthetic diagnostic of the frozen response-aware model (E5d): 2,804 states and "
                "500 paired PV states. Post-hoc analysis; no model was trained for this diagnostic.")  # fmt: skip

    # A: absolute import compression
    axA = fig.add_axes([0.065, 0.27, 0.40, 0.50])
    lo_, hi_ = -40, 170
    axA.axvspan(lo_, 0, color="#fdf1e3", zorder=0, lw=0)
    axA.text(-37, 160, "export\n(AC import < 0)", fontsize=10.5, color=ACCENT_TEXT, va="top")
    axA.scatter(S.ac_import, S.pred_import, s=7, color=COL["E5d"], alpha=0.30, lw=0, rasterized=True, zorder=2)
    xs = np.array([lo_, hi_])
    axA.plot(xs, xs, color=MUTED, lw=1.6, ls=(0, (5, 4)), zorder=3, label="perfect prediction")
    axA.plot(xs, a + b * xs, color=INK, lw=2.4, zorder=4,
             label=um(f"fit: predicted = {a:.1f} + {b:.3f} × AC"))  # fmt: skip
    axA.scatter([fixed], [fixed], s=60, color=SURFACE, edgecolor=INK, lw=1.8, zorder=5)
    axA.annotate(f"predictions pulled toward ≈ {fixed:.0f} MW\n(training mean {train_mean:.0f} MW)",
                 xy=(fixed, fixed), xytext=(70, 8), textcoords="data", fontsize=11, color=INK_2,
                 arrowprops=dict(arrowstyle="-", color=MUTED, lw=1))  # fmt: skip
    axA.set_xlim(lo_, hi_)
    axA.set_ylim(lo_, hi_)
    axA.set_xlabel("AC reference grid import (MW)")
    axA.set_ylabel("GENCO-predicted grid import (MW)")
    axA.legend(loc="upper left", bbox_to_anchor=(0.16, 1.0), fontsize=10.5, frameon=False)
    axA.set_title("A   Absolute import: compressed toward the training mean", fontsize=14,
                  fontweight="semibold", loc="left", color=INK, pad=12)  # fmt: skip
    badge(axA, 0.98, 0.06, f"import MAE {mae:.1f} MW · exports detected {row.export_recall:.0%}",
          ha="right", size=10.5)  # fmt: skip

    # B1: paired errors lie on the diagonal
    axS = fig.add_axes([0.555, 0.53, 0.17, 0.24])
    e = np.r_[P.err_A, P.err_B]
    lim = (np.floor(e.min()) - 1, np.ceil(e.max()) + 1)
    axS.plot(lim, lim, color=MUTED, lw=1.2, ls=(0, (5, 4)))
    axS.scatter(P.err_A, P.err_B, s=8, color=COL["E5d"], alpha=0.35, lw=0, rasterized=True)
    axS.set_xlim(lim)
    axS.set_ylim(lim)
    axS.set_xlabel("error, state A (MW)", fontsize=11)
    axS.set_ylabel("error, state B (MW)", fontsize=11)
    axS.tick_params(labelsize=10)
    axS.set_title("B   Paired PV states: the error is shared", fontsize=14, fontweight="semibold",
                  loc="left", color=INK, pad=12)  # fmt: skip
    axS.text(1.08, 0.80, f"r = {r_pair:.3f}", transform=axS.transAxes, fontsize=19, fontweight="bold", color=INK)
    axS.text(1.08, 0.58, "State B = state A with only\nthe PV output changed.", transform=axS.transAxes,
             fontsize=11, color=INK_2, va="top")  # fmt: skip
    axS.text(1.08, 0.22, "The shared error cancels in B − A,\nthe only quantity the response\nloss supervises.",
             transform=axS.transAxes, fontsize=11, color=INK_2, va="top")  # fmt: skip

    # B2: level error vs error of the change (log scale)
    axB = fig.add_axes([0.555, 0.27, 0.40, 0.19])
    labels = ["absolute import error, per state", "typical PV-induced change (AC)",
              "error of the predicted PV-induced change"]  # fmt: skip
    vals = [lvl, dac, dch]
    cols = [COL["E5d"], PV, COL["E5d"]]
    ys = np.arange(3)[::-1]
    axB.set_axisbelow(True)
    axB.barh(ys, vals, height=0.42, color=cols, alpha=0.95)
    axB.set_xscale("log")
    axB.set_xlim(0.02, 60)
    axB.set_ylim(-0.45, 2.75)
    axB.set_yticks([])
    axB.grid(axis="y", visible=False)
    for y, v, lab in zip(ys, vals, labels, strict=True):
        axB.text(0.021, y + 0.38, lab, va="center", fontsize=11, color=INK_2)
        axB.text(v * 1.15, y, f"{v:.2f} MW" if v >= 0.1 else f"{v:.3f} MW", va="center", fontsize=12,
                 fontweight="bold", color=INK)  # fmt: skip
    axB.set_xlabel("mean absolute value over 500 held-out PV pairs (MW, log scale)", fontsize=11)

    # identity strip
    ax = fig.add_axes([0.06, 0.035, 0.90, 0.12])
    ax.set_axis_off()
    ax.add_patch(FancyBboxPatch((0, 0), 0.58, 1, boxstyle="round,pad=0,rounding_size=0.08",
                                transform=ax.transAxes, fc=SURFACE, ec=BORDER, lw=1.2))  # fmt: skip
    ax.text(0.012, 0.74, "Power-balance identity (every state, within "
            f"{row.identity_max_abs_dev_mw:.2f} MW)", fontsize=11, color=INK_2, transform=ax.transAxes,
            va="center")  # fmt: skip
    ax.text(0.012, 0.40, "GENCO import error = Σ signed power mismatch at the 36 other buses + loss difference",
            fontsize=13.5, color=INK, fontweight="bold", transform=ax.transAxes, va="center")  # fmt: skip
    ax.text(0.012, 0.12, "Small per-bus mismatches share a sign and add up. The loss penalises each bus, "
            "not explicitly their sum.", fontsize=10.5, color=MUTED, transform=ax.transAxes,
            va="center")  # fmt: skip
    ax.add_patch(FancyBboxPatch((0.595, 0), 0.405, 1, boxstyle="round,pad=0,rounding_size=0.08",
                                transform=ax.transAxes, fc="#fff7ea", ec=ACCENT, lw=1.6))  # fmt: skip
    ax.text(0.607, 0.70, "Accurate states, accurate sensitivities and", fontsize=12.5,
            color=ACCENT_TEXT, fontweight="bold", transform=ax.transAxes, va="center")  # fmt: skip
    ax.text(0.607, 0.44, "global conservation are distinct properties.", fontsize=12.5,
            color=ACCENT_TEXT, fontweight="bold", transform=ax.transAxes, va="center")  # fmt: skip
    ax.text(0.607, 0.15, "Held-out synthetic diagnostic · no real-data claim", fontsize=10.5,
            color=INK_2, transform=ax.transAxes, va="center")  # fmt: skip
    return save(fig, "06_why_response_is_not_enough.png")


if __name__ == "__main__":
    import sys

    setup_fonts()
    figs = {"1": fig1, "2": fig2, "3": fig3, "4": fig4, "5": fig5, "6": fig6}
    for k in sys.argv[1:] or figs:  # e.g. `make_figures.py 6` builds only figure 6
        print(figs[k]())

"""Diagnostic figures for E1/E2 (matplotlib, static PNG). Not the Streamlit UI.

Geography rule: real coordinates are drawn only for geolocated nodes; unlocated junctions are
shown only in the schematic panel, with a distinct hollow marker, and never given invented
coordinates.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402
import numpy as np  # noqa: E402
import pandapower as pp  # noqa: E402
import pandas as pd  # noqa: E402

KV_COLOURS = {132.0: "#7b3294", 33.0: "#0571b0", 11.0: "#4dac26"}
MEAS_COLOURS = {"active_power": "#0571b0", "current_only": "#e66101", "none": "#bababa"}


def _graph(net: pp.pandapowerNet) -> nx.Graph:
    g = nx.Graph()
    names = net.bus["name"]
    for b in net.bus.index:
        g.add_node(names.at[b])
    for i, r in net.line.iterrows():
        g.add_edge(names.at[r.from_bus], names.at[r.to_bus], kind="line", name=r["name"], idx=i)
    for i, r in net.trafo.iterrows():
        g.add_edge(names.at[r.hv_bus], names.at[r.lv_bus], kind="trafo", name=r["name"], idx=i)
    for _, r in net.switch[net.switch.et == "b"].iterrows():
        g.add_edge(names.at[r.bus], names.at[r.element], kind="switch", name=r["name"])
    return g


def schematic_layout(net: pp.pandapowerNet) -> dict[str, np.ndarray]:
    return nx.kamada_kawai_layout(_graph(net))


def plot_topology(
    net: pp.pandapowerNet, path: Path, edge_class: dict[str, str] | None = None, title: str = ""
) -> None:
    """Two panels: (a) schematic (all nodes), (b) geographic (geolocated nodes only).

    edge_class maps line names to a measurement class (active_power / current_only / none);
    if given, line colours show measurement coverage instead of voltage level.
    """
    g = _graph(net)
    pos = nx.kamada_kawai_layout(g)
    bus = net.bus.set_index("name")
    located = bus["geolocation_status"] == "resolved"
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 7.2), gridspec_kw={"width_ratios": [1.2, 1]})

    for u, v, d in g.edges(data=True):
        x, y = zip(pos[u], pos[v], strict=True)
        if d["kind"] == "trafo":
            ax1.plot(x, y, color="#444", lw=1.2, ls="--", zorder=1)
        elif d["kind"] == "switch":
            ax1.plot(x, y, color="#444", lw=1, ls=":", zorder=1)
        else:
            colour = (
                MEAS_COLOURS[edge_class.get(d["name"], "none")]
                if edge_class
                else KV_COLOURS.get(float(bus.at[u, "vn_kv"]), "#444")
            )
            ax1.plot(x, y, color=colour, lw=2.6 if edge_class else 1.8, zorder=1)
    for n, (x, y) in pos.items():
        kv = float(bus.at[n, "vn_kv"])
        if located[n]:
            ax1.scatter(x, y, s=55, color=KV_COLOURS.get(kv, "#444"), edgecolor="white", zorder=3)
        else:
            ax1.scatter(
                x, y, s=70, facecolor="white", edgecolor="#d7191c", marker="D", lw=1.6, zorder=3
            )
        ax1.annotate(
            n.split(":")[1],
            (x, y),
            fontsize=6.5,
            xytext=(3, 3),
            textcoords="offset points",
            color="#222",
        )
    ax1.set_title("(a) Electrical schematic (layout is NOT geographic)", fontsize=10)
    ax1.axis("off")

    handles = [
        plt.Line2D(
            [],
            [],
            marker="o",
            ls="",
            color=c,
            label=f"{int(k) if k > 11 else 11} kV bus (geolocated)",
        )
        for k, c in KV_COLOURS.items()
    ]
    handles.append(
        plt.Line2D(
            [],
            [],
            marker="D",
            ls="",
            markerfacecolor="white",
            markeredgecolor="#d7191c",
            label="junction, geolocation unresolved",
        )
    )
    handles.append(plt.Line2D([], [], color="#444", ls="--", label="transformer"))
    if edge_class:
        handles += [
            plt.Line2D([], [], color=c, lw=2.6, label=f"circuit: {k.replace('_', ' ')}")
            for k, c in MEAS_COLOURS.items()
        ]
    ax1.legend(handles=handles, loc="lower left", fontsize=7, frameon=False)

    drawn = skipped = 0
    for u, v in g.edges():
        if located[u] and located[v]:
            ax2.plot(
                [bus.at[u, "geo_lon"], bus.at[v, "geo_lon"]],
                [bus.at[u, "geo_lat"], bus.at[v, "geo_lat"]],
                color="#888",
                lw=1,
                zorder=1,
            )
            drawn += 1
        else:
            skipped += 1
    loc = bus[located]
    ax2.scatter(
        loc["geo_lon"],
        loc["geo_lat"],
        c=[KV_COLOURS.get(float(k), "#444") for k in loc["vn_kv"]],
        s=40,
        zorder=2,
    )
    ax2.set_xlabel("longitude")
    ax2.set_ylabel("latitude")
    ax2.set_aspect(1 / np.cos(np.deg2rad(loc["geo_lat"].mean())))
    ax2.set_title(
        f"(b) Geolocated nodes only ({len(loc)}/{len(bus)}); "
        f"{skipped} branch(es) touching unlocated nodes not drawn",
        fontsize=10,
    )
    ax2.grid(alpha=0.3)
    fig.suptitle(title, fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_solar_geometry(assets: pd.DataFrame, sites: pd.DataFrame, path: Path, title: str) -> None:
    fig, ax = plt.subplots(figsize=(8, 6.5))
    ax.scatter(
        sites["lon"], sites["lat"], marker="s", s=60, color="#444", label="UKPN Grid/Primary site"
    )
    for _, s in sites.iterrows():
        ax.annotate(
            str(s["sitename"]).title(),
            (s["lon"], s["lat"]),
            fontsize=7,
            xytext=(4, -9),
            textcoords="offset points",
            color="#444",
        )
    sol = assets[assets["is_solar"]]
    ax.scatter(
        sol["lon"],
        sol["lat"],
        s=sol["capacity_mw"].clip(lower=0.3) * 18,
        color="#f1a340",
        edgecolor="#b35806",
        alpha=0.85,
        label="connected solar (area ∝ MW)",
    )
    for _, a in sol[sol["capacity_mw"] >= 1].iterrows():
        ax.annotate(
            f"{a['capacity_mw']:.0f} MW",
            (a["lon"], a["lat"]),
            fontsize=8,
            xytext=(6, 4),
            textcoords="offset points",
        )
    other = assets[~assets["is_solar"] & (assets["capacity_mw"] >= 1)]
    ax.scatter(
        other["lon"],
        other["lat"],
        marker="^",
        s=other["capacity_mw"] * 10,
        color="#998ec3",
        edgecolor="#542788",
        label="other ≥1 MW (storage, gas, wind…)",
    )
    ax.set_aspect(1 / np.cos(np.deg2rad(sites["lat"].mean())))
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.legend(fontsize=8, loc="lower left")
    ax.grid(alpha=0.3)
    ax.set_title(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_obs_vs_sim(results: pd.DataFrame, path: Path, title: str) -> None:
    """results: columns line, obs, sim (one row per timestamp × line)."""
    lines = list(dict.fromkeys(results["line"]))
    n = len(lines) + 1
    cols = 4
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(3.4 * cols, 3.1 * rows))
    axes = np.atleast_1d(axes).ravel()
    for ax, line in zip(axes, lines + ["ALL"], strict=False):
        d = results if line == "ALL" else results[results["line"] == line]
        d = d.dropna(subset=["obs", "sim"])
        if d.empty:
            ax.set_title(f"{line}\n(no data)", fontsize=8)
            ax.axis("off")
            continue
        lo = float(min(d["obs"].min(), d["sim"].min()))
        hi = float(max(d["obs"].max(), d["sim"].max()))
        ax.plot([lo, hi], [lo, hi], color="#999", lw=0.8, zorder=1)
        ax.scatter(d["obs"], d["sim"], s=6, alpha=0.5, color="#0571b0", zorder=2)
        r = np.corrcoef(d["obs"], d["sim"])[0, 1] if len(d) > 2 else np.nan
        mae = (d["sim"] - d["obs"]).abs().mean()
        ax.set_title(f"{line}\nr={r:.3f}  MAE={mae:.2f}  n={len(d)}", fontsize=8)
        ax.tick_params(labelsize=7)
        ax.set_xlabel("observed", fontsize=7)
        ax.set_ylabel("simulated", fontsize=7)
    for ax in axes[n:]:
        ax.axis("off")
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)

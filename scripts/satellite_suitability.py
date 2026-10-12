"""SATELLITE EXPERIMENT SUITABILITY ANALYSIS — Sundon vs Canterbury South vs Histon Grid.

    uv run python scripts/satellite_suitability.py

NOT a new E0 ranking (E0 is unchanged). Uses only already-downloaded UKPN metadata (ECR, sites,
LTDS, operational coverage). No satellite, weather or GENCO data. The pixel model is an
APPROXIMATION (see configs/experiments/e3_satellite_suitability.yaml).

Outputs
    reports/tables/e3_region_solar_geometry.csv          per asset
    reports/tables/e3_region_satellite_suitability.csv   per region (metrics + H2 class)
    reports/experiments/e3_satellite_readiness/suitability.json
    reports/figures/e3_region_solar_geometry.png
"""

from __future__ import annotations

import json
import math
import sys
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from cloud2grid.evaluation import spatial as sp  # noqa: E402
from cloud2grid.licensing.registry import REPO_ROOT  # noqa: E402
from cloud2grid.network import ukpn_audit as ua  # noqa: E402
from cloud2grid.network import ukpn_regions as ur  # noqa: E402

CFG = REPO_ROOT / "configs" / "experiments" / "e3_satellite_suitability.yaml"
RAW = REPO_ROOT / "data" / "raw" / "ukpn"
TABLES = REPO_ROOT / "reports" / "tables"
OUT = REPO_ROOT / "reports" / "experiments" / "e3_satellite_readiness"
FIGS = REPO_ROOT / "reports" / "figures"


def region_assets() -> tuple[dict[str, ur.Region], pd.DataFrame, pd.DataFrame]:
    """Rebuild E0 regions and identifier-based asset attribution (same functions as E0-D)."""
    t = {
        n: pd.read_parquet(RAW / f"{n}.parquet")
        for n in [
            "ltds_circuits",
            "ltds_transformers_2w",
            "ltds_transformers_3w",
            "grid_and_primary_sites",
            "ecr_1mw_and_above",
            "ecr_under_1mw",
        ]
    }
    branches, _ = ur.build_branches(
        t["ltds_circuits"], t["ltds_transformers_2w"], t["ltds_transformers_3w"]
    )
    sites = ua.add_lat_lon(t["grid_and_primary_sites"], "spatial_coordinates")
    floc_index = ur.substation_floc_index(
        t["ltds_circuits"], t["ltds_transformers_2w"], t["ltds_transformers_3w"], sites
    )
    nodes = ur.node_table(branches, floc_index, sites)
    ecr = pd.concat(
        [
            t["ecr_1mw_and_above"].assign(register=">=1MW"),
            t["ecr_under_1mw"].assign(register="<1MW"),
        ],
        ignore_index=True,
    )
    solar = ua.solar_assets(ecr)
    idx = ur.site_node_index(t["ltds_circuits"], t["ltds_transformers_2w"], set(nodes.index))
    attr = ur.attribute_solar(solar, nodes["kv"].to_dict(), *idx)
    bsp, _ = ur.bsp_subtrees(branches)
    return {r.region_id: r for r in bsp}, attr, sites


def main() -> int:
    cfg = yaml.safe_load(CFG.read_text())
    for d in (OUT, TABLES, FIGS):
        d.mkdir(parents=True, exist_ok=True)
    regions, attr, _ = region_assets()
    cand = pd.read_csv(TABLES / "e0_ukpn_candidate_regions.csv").set_index("candidate_region")
    status = pd.read_csv(TABLES / "e0_ukpn_line_status.csv")
    sundon_e2 = json.loads(
        (REPO_ROOT / "reports/experiments/e2_validation/summary.json").read_text()
    )

    rows, asset_rows = [], []
    pm, pr = cfg["pixel_model"], cfg["propagation"]
    for rid in cfg["regions"]:
        reg = regions[rid]
        a = attr[
            attr["connected"]
            & attr["route"].notna()
            & attr["nodes"].map(lambda ns, rn=reg.node_keys: bool(ns) and ns <= rn)
        ]
        a = a[a["capacity_mw"].notna() & a["latitude"].notna()].sort_values(
            "capacity_mw", ascending=False
        )
        cap = a["capacity_mw"].to_numpy()
        lat, lon = a["latitude"].to_numpy(float), a["longitude"].to_numpy(float)
        cum = np.cumsum(cap) / cap.sum()
        major = np.r_[True, cum[:-1] < cfg["assets"]["major_share"]]
        d_major = sp.pairwise_km(lat[major], lon[major])
        fp = sp.pixel_footprint(
            float(lat.mean()), float(lon.mean()), pm["nominal_km"], pm["sub_satellite_lon_deg"]
        )
        occ = sp.pixel_occupancy(
            lat[major],
            lon[major],
            cap[major],
            fp["dx_km"],
            fp["dy_km"],
            pm["grid_offset_draws"],
            pm["seed"],
        )
        span = sp.ew_span_km(lat[major], lon[major])
        iu = np.triu_indices(major.sum(), 1)

        # observability from E0 operational coverage (same basis for all three regions)
        lines = status[(status["area"] == reg.area)]
        cand_row = cand.loc[rid]
        region_status = lines[lines["line_name"].isin(_region_line_names(reg))]
        p_cap = int(region_status["usable_active_power"].sum())
        any_flow = int(region_status["usable"].sum())
        first = pd.to_datetime(region_status.loc[region_status.usable, "hh_first_timestamp"]).min()
        last = pd.to_datetime(region_status.loc[region_status.usable, "hh_last_timestamp"]).max()

        m: dict[str, Any] = {
            "region": rid,
            "analysis": "SATELLITE EXPERIMENT SUITABILITY (not an E0 ranking)",
            "connected_solar_mw": float(cap.sum()),
            "n_solar_assets": int(len(cap)),
            **{
                f"n_assets_{int(s * 100)}pct": sp.assets_for_share(cap, s)
                for s in cfg["assets"]["share_levels"]
            },
            **sp.hhi(cap),
            "major_assets": int(major.sum()),
            "major_mw": float(cap[major].sum()),
            "major_capacities_mw": "; ".join(f"{c:g}" for c in cap[major]),
            "min_pairwise_km": float(d_major[iu].min()) if len(iu[0]) else 0.0,
            "max_pairwise_km": float(d_major[iu].max()) if len(iu[0]) else 0.0,
            "weighted_mean_pairwise_km": sp.weighted_mean_pairwise_km(cap[major], d_major),
            "effective_extent_km": sp.effective_extent_km(lat, lon, cap),
            "major_ew_span_km": span,
            "bbox": f"{lat.min():.4f},{lon.min():.4f} — {lat.max():.4f},{lon.max():.4f}",
            "pixel_dx_km_approx": fp["dx_km"],
            "pixel_dy_km_approx": fp["dy_km"],
            "viewing_zenith_deg_approx": fp["viewing_zenith_deg"],
            **{f"major_{k}": v for k, v in occ.items()},
            "effective_independent_pixels": occ["effective_independent_pixels"],
            "major_ew_span_pixels": span / fp["dx_km"],
            **{f"transit_min_at_{v}ms": span * 1000 / v / 60 for v in pr["speeds_ms"]},
            "p_capable_circuits": p_cap,
            "current_only_circuits": any_flow - p_cap,
            "operational_history": (f"{first:%Y-%m}..{last:%Y-%m}" if pd.notna(first) else "none"),
            "network_nodes": int(cand_row["n_nodes"]),
            "network_circuits": int(cand_row["n_circuits"]),
            "reconstruction_status": "E1/E2 done — verdict B (usable with limitations)"
            if "Sundon" in rid
            else "E0 audit only (not reconstructed)",
        }
        level, detail = sp.classify_h2(m, cfg["h2_criteria"])
        m["h2_class"] = level
        m["h2_failed_checks_for_next_level"] = "; ".join(
            k
            for lvl in ("STRONG", "PLAUSIBLE")
            for k, ok in detail[lvl].items()
            if not ok and lvl == ("PLAUSIBLE" if level == "WEAK" else "STRONG")
        )
        rows.append(m)
        for i, rec in enumerate(a.itertuples()):
            asset_rows.append(
                {
                    "region": rid,
                    "ecr_register": rec.register,
                    "capacity_mw": cap[i],
                    "share": cap[i] / cap.sum(),
                    "cum_share": cum[i],
                    "major": bool(major[i]),
                    "lat": lat[i],
                    "lon": lon[i],
                    "connection_voltage_kv": rec.point_of_connection_poc_voltage_kv,
                    "site_floc": rec.floc,
                    "attribution_route": rec.route,
                }
            )
    table = pd.DataFrame(rows)
    table.to_csv(TABLES / "e3_region_satellite_suitability.csv", index=False)
    assets = pd.DataFrame(asset_rows)
    assets.to_csv(TABLES / "e3_region_solar_geometry.csv", index=False)

    classes = dict(zip(table.region, table.h2_class, strict=True))
    order = {"WEAK": 0, "PLAUSIBLE": 1, "STRONG": 2}
    sundon = next(r for r in cfg["regions"] if "Sundon" in r)
    others = [r for r in cfg["regions"] if r != sundon]
    best_other = max(
        others,
        key=lambda r: (
            order[classes[r]],
            float(table.set_index("region").at[r, "effective_independent_pixels"]),
        ),
    )
    s_lvl, o_lvl = order[classes[sundon]], order[classes[best_other]]
    o_p = int(table.set_index("region").at[best_other, "p_capable_circuits"])
    if s_lvl >= 1:
        option = "A"
    elif classes[best_other] == "STRONG" and o_p >= 3 and o_lvl - s_lvl >= 2:
        option = "C"
    else:
        option = "B"
    decision = {
        "option": option,
        "sundon_h2": classes[sundon],
        "best_other_region": best_other,
        "best_other_h2": classes[best_other],
        "best_other_p_capable_circuits": o_p,
        "rule": cfg["decision_rule"],
        "sundon_e2_verdict": sundon_e2["verdict"]["level"],
    }
    (OUT / "suitability.json").write_text(
        json.dumps({"regions": rows, "decision": decision}, indent=2, default=str)
    )

    fig, axes = plt.subplots(1, len(rows), figsize=(5.2 * len(rows), 5))
    for ax, m in zip(np.atleast_1d(axes), rows, strict=True):
        a = assets[assets.region == m["region"]]
        lat0 = a.lat.mean()
        x = np.radians(a.lon - a.lon.mean()) * sp.EARTH_R_KM * math.cos(math.radians(lat0))
        y = np.radians(a.lat - lat0) * sp.EARTH_R_KM
        dx, dy = m["pixel_dx_km_approx"], m["pixel_dy_km_approx"]
        for gx in np.arange(math.floor(x.min() / dx) * dx, x.max() + dx, dx):
            ax.axvline(gx, color="#ddd", lw=0.7, zorder=0)
        for gy in np.arange(math.floor(y.min() / dy) * dy, y.max() + dy, dy):
            ax.axhline(gy, color="#ddd", lw=0.7, zorder=0)
        ax.scatter(x[~a.major], y[~a.major], s=12, color="#bbb", label="minor (<5% tail)")
        ax.scatter(
            x[a.major],
            y[a.major],
            s=a.capacity_mw[a.major] * 12,
            color="#f1a340",
            edgecolor="#b35806",
            alpha=0.85,
            label="major (95% of MW), area ∝ MW",
        )
        for xi, yi, c in zip(x[a.major], y[a.major], a.capacity_mw[a.major], strict=True):
            ax.annotate(f"{c:.0f}", (xi, yi), fontsize=7, xytext=(4, 3), textcoords="offset points")
        ax.set_aspect("equal")
        ax.set_xlabel("km east (local)")
        ax.set_ylabel("km north (local)")
        ax.set_title(
            f"{m['region'].split(':', 2)[2]} — H2 {m['h2_class']}\n"
            f"{m['connected_solar_mw']:.1f} MW, {m['major_assets']} major, "
            f"eff. pixels ≈ {m['effective_independent_pixels']:.1f}",
            fontsize=9,
        )
        ax.legend(fontsize=7, loc="lower left")
    fig.suptitle(
        "Satellite experiment suitability — connected solar with an APPROXIMATE "
        f"{pm['nominal_km']:.0f} km-nominal MSG pixel grid (one grid phase shown)",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(FIGS / "e3_region_solar_geometry.png", dpi=150)
    plt.close(fig)

    cols = [
        "region",
        "connected_solar_mw",
        "n_solar_assets",
        "n_assets_50pct",
        "n_assets_80pct",
        "n_assets_90pct",
        "n_assets_95pct",
        "normalised_hhi",
        "effective_n_assets",
        "weighted_mean_pairwise_km",
        "max_pairwise_km",
        "effective_extent_km",
        "major_ew_span_km",
        "effective_independent_pixels",
        "major_distinct_pixels_mean",
        "p_capable_circuits",
        "current_only_circuits",
        "h2_class",
    ]
    with pd.option_context("display.width", 250, "display.max_columns", None):
        print(table[cols].round(3).T.to_string())
    print(json.dumps(decision, indent=1))
    return 0


def _region_line_names(reg: ur.Region) -> set[str]:
    """LTDS line names of the region's circuits (from LTDS T1 via branch ids)."""
    t1 = pd.read_parquet(RAW / "ltds_circuits.parquet").set_index("id")
    ids = [int(b.split(":")[1]) for b in reg.branch_ids if b.startswith("T1:")]
    return set(t1.loc[ids, "linename"])


if __name__ == "__main__":
    sys.exit(main())

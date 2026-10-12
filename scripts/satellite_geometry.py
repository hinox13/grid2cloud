"""Real MDSSFTD pixel geometry for Sundon and Canterbury South PV assets (E3).

    uv run python scripts/satellite_geometry.py

Uses the PUBLIC LSA SAF static files fetched by scripts/download_satellite_sample.py:
  * native MSG-disk latitude/longitude (HDF5) → validates the CGMS projection used here;
  * the regular-grid NetCDF land/water mask → the exact 0.05° grid of the MDSSFTD NetCDF files.
No credentials and no MDSSFTD radiation data are needed. Replaces the approximate pixel model
of reports/e3_satellite_readiness.md §3.

Outputs
    reports/tables/e3_asset_pixel_mapping.csv
    reports/experiments/e3_satellite/geometry.json
    reports/figures/e3_asset_pixels.png
"""

from __future__ import annotations

import bz2
import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import Any

import h5py
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import xarray as xr  # noqa: E402
import yaml  # noqa: E402

from cloud2grid.evaluation import spatial as sp  # noqa: E402
from cloud2grid.licensing.registry import REPO_ROOT  # noqa: E402
from cloud2grid.satellite import geometry as geo  # noqa: E402
from cloud2grid.solar import capacity as capm  # noqa: E402
from cloud2grid.solar import inventory  # noqa: E402

LSA = yaml.safe_load((REPO_ROOT / "configs/data/lsasaf.yaml").read_text())
PVM = yaml.safe_load((REPO_ROOT / "configs/experiments/e3_pv_model.yaml").read_text())
SUIT = yaml.safe_load((REPO_ROOT / "configs/experiments/e3_satellite_suitability.yaml").read_text())
STATIC = REPO_ROOT / LSA["storage"]["raw_dir"] / "static"
OUT = REPO_ROOT / "reports/experiments/e3_satellite"
TABLES = REPO_ROOT / "reports/tables"
FIGS = REPO_ROOT / "reports/figures"
REF_2024 = pd.Timestamp("2024-06-15T12:00:00Z")  # inside the pre-registered search period
GEOREF_UNCERTAINTY_PX = LSA["native_grid"]["georeference_uncertainty_pixels"]


def native_arrays() -> tuple[np.ndarray, np.ndarray]:
    out = []
    for v in ("lat", "lon"):
        raw = bz2.decompress((STATIC / LSA["static_geometry"][f"native_{v}"]).read_bytes())
        with h5py.File(io.BytesIO(raw), "r") as h:
            d = h[v.upper()]
            a = d[:].astype(float)
            a[a == d.attrs["MISSING_VALUE"]] = np.nan
            out.append(a / d.attrs["SCALING_FACTOR"])
    return out[0], out[1]


def validate_projection(lat_a: np.ndarray, lon_a: np.ndarray, bbox: dict) -> dict[str, Any]:
    """CGMS centres vs official native lat/lon (0.01° stored precision) over the context box."""
    inside = (
        (lat_a >= bbox["lat_min"])
        & (lat_a <= bbox["lat_max"])
        & (lon_a >= bbox["lon_min"])
        & (lon_a <= bbox["lon_max"])
    )
    r, c = np.nonzero(inside)
    glat, glon = geo.native_to_geo(c + 1, r + 1)  # 1-based ncol, nlin
    dlat, dlon = np.abs(glat - lat_a[r, c]), np.abs(glon - lon_a[r, c])
    return {
        "pixels_compared": int(len(r)),
        "max_abs_dlat_deg": float(dlat.max()),
        "max_abs_dlon_deg": float(dlon.max()),
        "official_precision_deg": 0.01,
        "pass": bool(dlat.max() <= 0.006 and dlon.max() <= 0.006),
    }


def edge_distance(
    lat: np.ndarray, lon: np.ndarray, grid: geo.RegularGrid
) -> tuple[np.ndarray, np.ndarray]:
    """Distance (in pixel units) from each asset to the nearest edge of its pixel: native grid
    and regular grid. < 1/3 ⇒ the PUM georeference uncertainty could move it across."""
    c, l_ = geo.native_index(lat, lon)
    nat = 0.5 - np.maximum(np.abs(c - np.rint(c)), np.abs(l_ - np.rint(l_)))
    fr = (lat - grid.lat0) / grid.dlat
    fc = (lon - grid.lon0) / grid.dlon
    reg = 0.5 - np.maximum(np.abs(fr - np.rint(fr)), np.abs(fc - np.rint(fc)))
    return nat, reg


def summarise(m: pd.DataFrame, region: str, fleet: str) -> dict[str, Any]:
    nat = geo.pixel_summary(m, "native_pixel_id")
    smp = geo.pixel_summary(m, "sampled_native_pixel_id")
    reg = geo.pixel_summary(m, "pixel_id")
    sep = geo.pixel_separations(m, "native_nlin", "native_ncol")
    cols = m["native_ncol"]
    span_km = sp.ew_span_km(m["lat"].to_numpy(), m["lon"].to_numpy()) if len(m) > 1 else 0.0
    fp = geo.native_footprint_km(float(m["lat"].mean()), float(m["lon"].mean()))
    transit = {f"{v}ms": span_km * 1000 / v / 60 for v in SUIT["propagation"]["speeds_ms"]}
    return {
        "region": region,
        "fleet": fleet,
        "n_assets": int(len(m)),
        "capacity_mw": float(m["capacity_mw"].sum()),
        "native_distinct_pixels": nat["distinct_pixels"],
        "native_effective_independent_pixels": nat["effective_independent_pixels"],
        "native_shared_pixels": nat["shared_pixels"],
        "sampled_distinct_native_pixels": smp["distinct_pixels"],
        "sampled_effective_independent_pixels": smp["effective_independent_pixels"],
        "regular_distinct_cells": reg["distinct_pixels"],
        "regular_effective_independent_cells": reg["effective_independent_pixels"],
        "regular_shared_cells": reg["shared_pixels"],
        "pairs_same_native_pixel": int((sep["chebyshev"] == 0).sum()) if len(sep) else 0,
        "pairs_adjacent_native_pixel": int((sep["chebyshev"] == 1).sum()) if len(sep) else 0,
        "pairs_separated_ge2_native_pixels": int((sep["chebyshev"] >= 2).sum()) if len(sep) else 0,
        "assets_within_georef_uncertainty_of_edge": int(
            (m["native_edge_distance_px"] < GEOREF_UNCERTAINTY_PX).sum()
        ),
        "ew_span_native_columns": int(cols.max() - cols.min()) if len(m) else 0,
        "ew_span_km": span_km,
        "transit_min": transit,
        "frames_to_cross_at_10ms": span_km * 1000 / 10 / (15 * 60),
        "native_footprint_km": {k: fp[k] for k in ("dx_km", "dy_km", "area_km2")},
        "acquisition_offset_min": float(m["acquisition_offset_min"].mean()),
        "pair_separations": sep.round(3).to_dict("records"),
    }


def sundon_sets() -> dict[str, pd.DataFrame]:
    inv = inventory.load(PVM)
    ev, _ = inventory.ltds_evidence(inv, PVM)
    conn = inv[inv["status"] == "Connected"].copy()
    conn = conn.sort_values("capacity_mw", ascending=False)
    cum = conn["capacity_mw"].cumsum() / conn["capacity_mw"].sum()
    major = conn[np.r_[True, cum.to_numpy()[:-1] < SUIT["assets"]["major_share"]]]
    act = capm.active_capacity(conn, REF_2024, ev).set_index("asset_id")
    active = conn[conn["asset_id"].map(act["active_capacity_mw"]) > 0]
    major_active = active[active["capacity_mw"] >= 1.0]
    return {
        "current_major_95pct": major,
        "active_2024": active,
        "active_2024_ge1mw": major_active,
    }


def canterbury_sets() -> dict[str, pd.DataFrame]:
    spec = importlib.util.spec_from_file_location(
        "satellite_suitability", REPO_ROOT / "scripts/satellite_suitability.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    regions, attr, _ = mod.region_assets()
    reg = regions["BSP:SPN:Canterbury South 33kV"]
    a = attr[
        attr["connected"]
        & attr["route"].notna()
        & attr["nodes"].map(lambda ns: bool(ns) and ns <= reg.node_keys)
    ]
    a = a[a["capacity_mw"].notna() & a["latitude"].notna()].sort_values(
        "capacity_mw", ascending=False
    )
    a = pd.DataFrame(
        {
            "asset_id": [f"ECR:{i}" for i in a.index],
            "capacity_mw": a["capacity_mw"].to_numpy(float),
            "lat": a["latitude"].to_numpy(float),
            "lon": a["longitude"].to_numpy(float),
            "date_connected": a["date_connected"].to_numpy(),
            "status": a["connection_status"].to_numpy(),
            "connection_voltage_kv": a["point_of_connection_poc_voltage_kv"].to_numpy(),
        }
    )
    cum = a["capacity_mw"].cumsum() / a["capacity_mw"].sum()
    major = a[np.r_[True, cum.to_numpy()[:-1] < SUIT["assets"]["major_share"]]]
    act = capm.active_capacity(major, REF_2024, {}).set_index("asset_id")
    major = major.assign(activity_2024=major["asset_id"].map(act["activity"]))
    return {"current_major_95pct": major}


def map_set(df: pd.DataFrame, grid: geo.RegularGrid, mask: xr.DataArray) -> pd.DataFrame:
    m = geo.map_assets(df[["asset_id", "capacity_mw", "lat", "lon"]].reset_index(drop=True), grid)
    nat, reg = edge_distance(m["lat"].to_numpy(), m["lon"].to_numpy(), grid)
    m["native_edge_distance_px"], m["regular_edge_distance_px"] = nat, reg
    m["lwmask_value"] = [
        float(mask.isel(lat=int(r), lon=int(c)))
        for r, c in zip(m.pixel_row, m.pixel_col, strict=True)
    ]
    return m


def h2_with_real_pixels(region: str, eff_pixels: float) -> tuple[str, dict]:
    prev = json.loads(
        (REPO_ROOT / "reports/experiments/e3_satellite_readiness/suitability.json").read_text()
    )
    row = next(r for r in prev["regions"] if r["region"] == region)
    m = dict(row, effective_independent_pixels=eff_pixels)
    return sp.classify_h2(m, SUIT["h2_criteria"])


def figure(mapped: dict[str, pd.DataFrame], path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    for ax, (title, m) in zip(axes, mapped.items(), strict=True):
        lat0, lat1 = m.lat.min() - 0.06, m.lat.max() + 0.06
        lon0, lon1 = m.lon.min() - 0.08, m.lon.max() + 0.08
        for x in np.arange(np.floor(lon0 / 0.05) * 0.05 - 0.025, lon1 + 0.05, 0.05):
            ax.axvline(x, color="0.85", lw=0.6)
        for y in np.arange(np.floor(lat0 / 0.05) * 0.05 - 0.025, lat1 + 0.05, 0.05):
            ax.axhline(y, color="0.85", lw=0.6)
        c0, l0 = geo.native_index(np.array([lat1]), np.array([lon0]))
        c1, l1 = geo.native_index(np.array([lat0]), np.array([lon1]))
        for nc in range(int(c0[0]) - 1, int(c1[0]) + 2):
            for nl in range(int(l0[0]) - 1, int(l1[0]) + 2):
                cc = np.array([nc - 0.5, nc + 0.5, nc + 0.5, nc - 0.5, nc - 0.5])
                ll = np.array([nl - 0.5, nl - 0.5, nl + 0.5, nl + 0.5, nl - 0.5])
                plat, plon = geo.native_to_geo(cc, ll)
                ax.plot(plon, plat, color="tab:blue", lw=0.5, alpha=0.6)
        colours = np.where(
            m.get("active_2024", pd.Series(True, index=m.index)), "tab:orange", "0.5"
        )
        ax.scatter(m.lon, m.lat, s=40 + 12 * m.capacity_mw, c=colours, edgecolor="k", zorder=3)
        for r in m.itertuples():
            ax.annotate(
                f"{r.capacity_mw:g} MW",
                (r.lon, r.lat),
                xytext=(4, 4),
                textcoords="offset points",
                fontsize=8,
            )
        ax.set_xlim(lon0, lon1)
        ax.set_ylim(lat0, lat1)
        ax.set_aspect(1 / np.cos(np.radians((lat0 + lat1) / 2)))
        ax.xaxis.set_major_locator(plt.MaxNLocator(5))
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("longitude (°)")
        ax.set_ylabel("latitude (°)")
    fig.suptitle(
        "Real MDSSFTD geometry: 0.05° NetCDF cells (grey) and native SEVIRI pixels (blue). "
        "Orange = active in 2024; grey = not active in 2024.",
        fontsize=9,
    )
    fig.text(
        0.01,
        0.01,
        "Geometry: EUMETSAT LSA SAF static MSG grid. "
        "Asset locations: UK Power Networks ECR (CC BY 4.0).",
        fontsize=7,
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> int:
    missing = [
        f
        for f in (
            LSA["static_geometry"]["native_lat"],
            LSA["static_geometry"]["native_lon"],
            LSA["static_geometry"]["regular_grid_mask"],
        )
        if not (STATIC / f).exists()
    ]
    if missing:
        print(
            f"static geometry files missing ({missing}); "
            "run scripts/download_satellite_sample.py first"
        )
        return 2
    for d in (OUT, TABLES, FIGS):
        d.mkdir(parents=True, exist_ok=True)
    lat_a, lon_a = native_arrays()
    validation = validate_projection(lat_a, lon_a, LSA["study_area"]["context_bbox"])
    mask_ds = xr.open_dataset(STATIC / LSA["static_geometry"]["regular_grid_mask"])
    grid = geo.RegularGrid.from_coords(mask_ds["lat"].values, mask_ds["lon"].values)
    exp = LSA["expected"]["grid"]
    grid_check = {
        "lat_first": grid.lat0,
        "lat_step": grid.dlat,
        "lon_first": grid.lon0,
        "lon_step": grid.dlon,
        "n": [grid.nlat, grid.nlon],
        "matches_expected": bool(
            abs(grid.lat0 - exp["lat_first"]) < 1e-4
            and abs(grid.dlat - exp["lat_step"]) < 1e-4
            and abs(grid.lon0 - exp["lon_first"]) < 1e-4
            and abs(grid.dlon - exp["lon_step"]) < 1e-4
            and grid.nlat == exp["n"]
            and grid.nlon == exp["n"]
        ),
        "history": mask_ds.attrs.get("history"),
        "license_attribute": mask_ds.attrs.get("license"),
    }
    mask = mask_ds["LWMASK"].isel(time=0)

    rows, summaries = [], []
    sund = sundon_sets()
    cant = canterbury_sets()
    sets = [("BSP:EPN:Sundon 33kV", k, v) for k, v in sund.items()] + [
        ("BSP:SPN:Canterbury South 33kV", k, v) for k, v in cant.items()
    ]
    mapped_fig = {}
    active_ids = set(sund["active_2024"]["asset_id"])
    for region, fleet, df in sets:
        m = map_set(df, grid, mask)
        m.insert(0, "fleet", fleet)
        m.insert(0, "region", region)
        if "activity_2024" in df:
            m["activity_2024"] = df["activity_2024"].to_numpy()
        elif region.startswith("BSP:EPN:Sundon"):
            m["activity_2024"] = np.where(m["asset_id"].isin(active_ids), "ACTIVE", "NOT_ACTIVE")
        rows.append(m)
        summaries.append(summarise(m, region, fleet))
        if fleet == "current_major_95pct":
            short = "Sundon 33 kV" if "Sundon" in region else "Canterbury South 33 kV"
            mapped_fig[f"{short}: major PV (95% of connected MW)"] = m.assign(
                active_2024=m["activity_2024"].eq("ACTIVE")
            )
    table = pd.concat(rows, ignore_index=True)
    cols = [
        "region",
        "fleet",
        "asset_id",
        "capacity_mw",
        "lat",
        "lon",
        "pixel_row",
        "pixel_col",
        "pixel_center_lat",
        "pixel_center_lon",
        "dist_to_pixel_center_km",
        "pixel_id",
        "regular_edge_distance_px",
        "native_ncol",
        "native_nlin",
        "native_center_lat",
        "native_center_lon",
        "dist_to_native_center_km",
        "native_pixel_id",
        "native_edge_distance_px",
        "sampled_native_pixel_id",
        "acquisition_offset_min",
        "lwmask_value",
        "activity_2024",
    ]
    table[cols].round(5).to_csv(TABLES / "e3_asset_pixel_mapping.csv", index=False)

    h2 = {}
    for s in summaries:
        if s["fleet"] == "current_major_95pct":
            level, detail = h2_with_real_pixels(
                s["region"], s["native_effective_independent_pixels"]
            )
            h2[s["region"]] = {
                "h2_class_real_geometry": level,
                "checks": detail,
                "effective_independent_pixels_real": s["native_effective_independent_pixels"],
                "note": "same pre-declared criteria "
                "(configs/experiments/e3_satellite_suitability.yaml); only the pixel count "
                "is replaced by real native geometry",
            }
    out = {
        "projection_validation": validation,
        "regular_grid": grid_check,
        "reference_time_2024": str(REF_2024),
        "summaries": summaries,
        "h2_update": h2,
        "georeference_uncertainty_px": GEOREF_UNCERTAINTY_PX,
    }
    (OUT / "geometry.json").write_text(json.dumps(out, indent=2, default=str))
    figure(mapped_fig, FIGS / "e3_asset_pixels.png")
    print(
        json.dumps(
            {"projection_validation": validation, "grid": grid_check["matches_expected"]}, indent=1
        )
    )
    for s in summaries:
        print(
            f"{s['region']:32s} {s['fleet']:22s} n={s['n_assets']:2d} {s['capacity_mw']:6.2f} MW "
            f"native distinct={s['native_distinct_pixels']} "
            f"eff={s['native_effective_independent_pixels']:.2f} "
            f"regular distinct={s['regular_distinct_cells']} "
            f"eff={s['regular_effective_independent_cells']:.2f} "
            f"pairs same/adj/>=2: {s['pairs_same_native_pixel']}/"
            f"{s['pairs_adjacent_native_pixel']}/{s['pairs_separated_ge2_native_pixels']} "
            f"edge-sensitive={s['assets_within_georef_uncertainty_of_edge']} "
            f"EW cols={s['ew_span_native_columns']}"
        )
    print(json.dumps({k: v["h2_class_real_geometry"] for k, v in h2.items()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

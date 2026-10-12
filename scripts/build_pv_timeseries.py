"""Satellite irradiance → Sundon PV assets → estimated PV → per-bus injections (E3).

    uv run python scripts/build_pv_timeseries.py                 # inventory + model checks;
                                                                 # PV series from existing crops
    uv run --env-file .env python scripts/build_pv_timeseries.py --acquire   # fetch the
                                                                 # pre-registered search period
                                                                 # (analysis box only; needs
                                                                 # LSASAF_USERNAME/PASSWORD)

Always written (no satellite data needed):
    reports/tables/e3_pv_assets.csv          inventory, historical activity, injection nodes
    reports/tables/e3_pv_model_checks.csv    PV-chain sanity on pvlib clear-sky inputs
                                             (MODEL CHECK — not satellite-driven)
Written when MDSSFTD crops exist (data/interim/satellite/lsasaf/analysis/):
    data/processed/satellite/sundon/{irradiance_by_asset,pv_by_asset,pv_by_bus,field_stats}.parquet
    reports/tables/e3_pv_satellite_checks.csv
Status of every run: reports/experiments/e3_satellite/pv_timeseries.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Any

import numpy as np
import pandas as pd
import pvlib
import requests
import xarray as xr
import yaml

from cloud2grid.licensing import gate
from cloud2grid.licensing.registry import REPO_ROOT, Registry
from cloud2grid.network import scenarios as scn
from cloud2grid.satellite import credentials, lsasaf
from cloud2grid.satellite import geometry as geo
from cloud2grid.solar import aggregate, capacity, forcing, inventory, irradiance, pv
from cloud2grid.utils import provenance

LSA = yaml.safe_load((REPO_ROOT / "configs/data/lsasaf.yaml").read_text())
PVM = yaml.safe_load((REPO_ROOT / "configs/experiments/e3_pv_model.yaml").read_text())
EVT = yaml.safe_load((REPO_ROOT / "configs/experiments/e3_event_discovery.yaml").read_text())
OUT = REPO_ROOT / "reports/experiments/e3_satellite"
TABLES = REPO_ROOT / "reports/tables"
CROPS = REPO_ROOT / LSA["storage"]["crop_dir"] / "analysis"
PROC = REPO_ROOT / "data/processed/satellite/sundon"
STATIC = REPO_ROOT / LSA["storage"]["raw_dir"] / "static"
NAMES = LSA["expected"]["variables"]


def site_load_nodes() -> dict[str, list[str]]:
    cfg = scn.load_config(REPO_ROOT / PVM["network_config"])
    out: dict[str, list[str]] = {}
    for spec in cfg["loads"]:
        out.setdefault(spec["pf_site_floc"], []).append(spec["node"])
    return out


def regular_grid() -> geo.RegularGrid:
    ds = xr.open_dataset(STATIC / LSA["static_geometry"]["regular_grid_mask"])
    return geo.RegularGrid.from_coords(ds["lat"].values, ds["lon"].values)


def build_inventory() -> tuple[pd.DataFrame, dict, list[dict], pd.DataFrame, dict[str, list[str]]]:
    inv = inventory.load(PVM)
    ev, recon = inventory.ltds_evidence(inv, PVM)
    nodes = aggregate.bus_rules(inv, site_load_nodes(), PVM["buses"])
    start = pd.Timestamp(EVT["search_period"]["start"])
    end = pd.Timestamp(EVT["search_period"]["end"])
    a0 = capacity.active_capacity(inv, start, ev, PVM["capacity"]["include_undated"]).set_index(
        "asset_id"
    )
    a1 = capacity.active_capacity(inv, end, ev, PVM["capacity"]["include_undated"]).set_index(
        "asset_id"
    )
    located = inv[inv["lat"].notna()]
    mapped = geo.map_assets(
        located[["asset_id", "capacity_mw", "lat", "lon"]].fillna({"capacity_mw": 0.0}),
        regular_grid(),
    )
    table = inv.assign(
        injection_nodes=inv["asset_id"].map(lambda a: "; ".join(nodes[a])),
        attributed_nodes=inv["attributed_nodes"].map(lambda ns: "; ".join(ns)),
        activity_search_start=inv["asset_id"].map(a0["activity"]),
        activity_search_end=inv["asset_id"].map(a1["activity"]),
        active_capacity_search_mw=inv["asset_id"].map(a0["active_capacity_mw"]),
        activity_reason=inv["asset_id"].map(a0["reason"]),
        pixel_id=inv["asset_id"].map(mapped.set_index("asset_id")["pixel_id"]),
        native_pixel_id=inv["asset_id"].map(mapped.set_index("asset_id")["native_pixel_id"]),
    )
    return table, ev, recon, mapped, nodes


def model_checks(pvm: dict[str, Any]) -> pd.DataFrame:
    """PV-chain sanity with pvlib clear-sky inputs at the 6 MW Sundon asset (NOT satellite data)."""
    lat, lon = 51.925, -0.611
    loc = pvlib.location.Location(lat, lon)
    cases = [
        ("night", "2024-06-15T00:00Z", 1.0, None),
        ("clear_noon_june", "2024-06-15T12:00Z", 1.0, None),
        ("cloudy_noon_june_kc0.3", "2024-06-15T12:00Z", 0.3, 1.0),
        ("clear_morning_june", "2024-06-15T06:00Z", 1.0, None),
        ("clear_low_sun_evening", "2024-06-15T19:30Z", 1.0, None),
        ("clear_noon_december", "2024-12-21T12:00Z", 1.0, None),
    ]
    rows = []
    for name, t, kc, fd_override in cases:
        ti = pd.DatetimeIndex([pd.Timestamp(t)])
        cs = loc.get_clearsky(ti, model="ineichen")
        ghi = cs["ghi"].to_numpy() * kc
        fd = (
            (cs["dhi"] / cs["ghi"]).fillna(1.0).to_numpy()
            if fd_override is None
            else np.array([fd_override])
        )
        comp = irradiance.components(ti, ghi, fd, lat, lon, pvm["irradiance"])
        for temp in (5.0, 15.0, 25.0):
            p = dict(pvm["pv"], temp_air_c=temp)
            cf = float(pv.capacity_factor(comp, p).iloc[0])
            rows.append(
                {
                    "case": name,
                    "time_utc": t,
                    "input": "pvlib Ineichen clear-sky × kc (MODEL CHECK, not satellite)",
                    "kc": kc,
                    "ghi": float(ghi[0]),
                    "dhi": float(comp["dhi"].iloc[0]),
                    "dni": float(comp["dni"].iloc[0]),
                    "elevation_deg": float(comp["elevation"].iloc[0]),
                    "temp_air_c": temp,
                    "capacity_factor": cf,
                    "p_mw_6mw_asset": cf * 6.0,
                }
            )
    df = pd.DataFrame(rows)
    base = df[df.temp_air_c == pvm["pv"]["temp_air_c"]].set_index("case")
    checks = {
        "night_is_zero": base.loc["night", "capacity_factor"] == 0.0,
        "bounded_0_1": bool(df.capacity_factor.between(0, 1).all()),
        "clear_noon_high": 0.6 <= base.loc["clear_noon_june", "capacity_factor"] <= 1.0,
        "cloud_reduces": base.loc["cloudy_noon_june_kc0.3", "capacity_factor"]
        < base.loc["clear_noon_june", "capacity_factor"],
        "low_sun_lower": base.loc["clear_low_sun_evening", "capacity_factor"]
        < base.loc["clear_noon_june", "capacity_factor"],
        "warmer_is_lower": bool(
            df[(df.case == "clear_noon_june")]
            .sort_values("temp_air_c")
            .capacity_factor.is_monotonic_decreasing
        ),
    }
    df.attrs["checks"] = {k: bool(v) for k, v in checks.items()}
    return df


def daylight_slots(start: pd.Timestamp, end: pd.Timestamp) -> list[dt.datetime]:
    slots = pd.date_range(start, end, freq=f"{EVT['step_minutes']}min")
    el = pvlib.location.Location(51.93, -0.6).get_solarposition(slots + pd.Timedelta(minutes=11.6))[
        "elevation"
    ]
    return [
        t.to_pydatetime()
        for t in slots[el.to_numpy() >= EVT["search_period"]["daylight_min_elevation_deg"]]
    ]


def acquire(start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    """Fetch the analysis box for every daylight slot, one NetCDF per day (resumable, fills gaps).

    Polite by construction (configs/data/lsasaf.yaml `access.politeness`): sequential, one
    session, >= pause_s between requests, ONE authenticated request per slot (DAP ASCII subset).
    The public archive listing (anonymous) is read first: only slots that exist are requested;
    absent slots are recorded as missing_in_archive. 401/403 stop at once; 429/5xx back off;
    other failures (e.g. 404) are recorded and only abort after N consecutive ones. A day is
    written only when every listed slot was attempted, so an abort never leaves a partial day.
    Days already on disk are completed with only their missing listed slots.
    """
    import time

    env = LSA["access"]["credentials_env"]
    cred = credentials.load("LSA SAF data service", env["user"], env["secret"])  # may raise
    gate.require("lsa_saf_mdssftd", "download", Registry.load())
    product = lsasaf.Product.from_config(LSA)
    pol = LSA["access"]["politeness"]
    client = lsasaf.PoliteClient(cred, pol["pause_s"])
    listing_session = requests.Session()
    g = LSA["expected"]["grid"]
    box = lsasaf.index_box(
        g["lat_first"],
        g["lat_step"],
        g["lon_first"],
        g["lon_step"],
        LSA["study_area"]["analysis_bbox"],
    )
    vars_ = [NAMES["total"], NAMES["diffuse_fraction"], NAMES["quality"]]
    CROPS.mkdir(parents=True, exist_ok=True)
    done, skipped, failed, missing_archive, consecutive = 0, 0, [], [], 0
    status = "OK"
    for day in pd.date_range(start.normalize(), end.normalize(), freq="D"):
        path = CROPS / f"MDSSFTD_analysis_{day:%Y%m%d}.nc"
        existing = xr.open_dataset(path).load() if path.exists() else None
        if existing is not None and existing.attrs.get("complete") == 1:
            skipped += 1
            continue
        wanted = daylight_slots(day, day + pd.Timedelta(hours=23, minutes=45))
        time.sleep(pol["pause_s"])
        listed = set(lsasaf.list_day(product, day.date(), listing_session)["slot"])
        have = (
            set(pd.to_datetime(existing["time"].values).tz_localize("UTC"))
            if existing is not None
            else set()
        )
        absent = [s for s in wanted if pd.Timestamp(s) not in listed]
        missing_archive += [s.isoformat() for s in absent]
        todo = [s for s in wanted if pd.Timestamp(s) in listed and pd.Timestamp(s) not in have]
        parts, day_failed = [], []
        for slot in todo:
            url = lsasaf.dap_ascii_url(product, slot, box, vars_)
            for attempt in range(len(pol["backoff_s"]) + 1):
                try:
                    raw = lsasaf.parse_dap_ascii(client.get_text(url), vars_)
                    parts.append(lsasaf.decode(raw, LSA["verified_packing"], slot))
                    consecutive = 0
                    break
                except lsasaf.AuthRejected as e:
                    return {
                        "status": "ABORTED_AUTH",
                        "message": str(e),
                        "days_written": done,
                        "requests": client.requests_made,
                        "failed_slots": failed,
                    }
                except lsasaf.Throttled as e:
                    if attempt < len(pol["backoff_s"]):
                        print(f"  throttled {slot:%Y-%m-%d %H:%M}: {e}; backing off", flush=True)
                        time.sleep(pol["backoff_s"][attempt])
                        continue
                    day_failed.append({"slot": slot.isoformat(), "error": str(e)})
                    consecutive += 1
                except (lsasaf.DownloadError, ValueError) as e:
                    msg = str(e)[:200]
                    day_failed.append({"slot": slot.isoformat(), "error": msg})
                    print(f"  failed {slot:%Y-%m-%d %H:%M}: {msg[:120]}", flush=True)
                    # a 404 on a listed file is a gap, not a sign of server trouble
                    consecutive += 0 if "HTTP 404" in msg else 1
                    break
            if consecutive >= pol["max_consecutive_failures"]:
                status = "ABORTED_FAILURES"
                break
        failed += day_failed
        if status != "OK":
            print(f"stopping: {status} (day {day:%Y-%m-%d} not written)", flush=True)
            break
        pieces = ([existing] if existing is not None else []) + parts
        if not pieces:
            continue
        ds = xr.concat(pieces, dim="time").sortby("time")
        ds.attrs.update(
            complete=1,
            missing_in_archive=", ".join(s.strftime("%H:%M") for s in absent),
            failed_slots=", ".join(f["slot"][11:16] for f in day_failed),
            packing="decoded with verified_packing (configs/data/lsasaf.yaml)",
        )
        tmp = path.with_suffix(".tmp.nc")
        ds.to_netcdf(tmp, encoding={k: {"zlib": True, "complevel": 4} for k in ds.data_vars})
        tmp.replace(path)
        provenance.record(
            path,
            source_id="lsa_saf_mdssftd",
            url=f"{product.opendap_url(pd.Timestamp(ds.indexes['time'][0]).to_pydatetime())}.ascii?<subset>",
            licence="CC-BY-4.0",
            extra={
                "processing_level": "analysis_bbox subset (DAP ASCII, decoded), daylight slots",
                "bbox": LSA["study_area"]["analysis_bbox"],
                "index_box": list(box),
                "n_slots": int(ds.sizes["time"]),
                "missing_in_archive": [s.isoformat() for s in absent],
                "failed_slots": day_failed,
                "requested_day": f"{day:%Y-%m-%d}",
                "access_mode": "dap_ascii",
            },
        )
        done += 1
        print(
            f"{day:%Y-%m-%d}: +{len(parts)} slots ({ds.sizes['time']} total), "
            f"requests so far {client.requests_made}",
            flush=True,
        )
    return {
        "status": status,
        "days_written_or_completed": done,
        "days_already_complete": skipped,
        "requests": client.requests_made,
        "failed_slots": failed,
        "missing_in_archive": missing_archive,
    }


def satellite_series(
    inv: pd.DataFrame, ev: dict, mapped: pd.DataFrame, nodes: dict
) -> dict[str, Any] | None:
    files = sorted(CROPS.glob("MDSSFTD_analysis_*.nc"))
    if not files:
        return None
    # Small daily files: plain concatenation (no dask dependency).
    ds = xr.concat([xr.open_dataset(f).load() for f in files], dim="time")
    connected = inv[inv["status"] == "Connected"]
    m = mapped[mapped["asset_id"].isin(connected["asset_id"])]
    samples = forcing.sample_assets(ds, m, NAMES)
    allow_low = LSA["quality"]["allow_low_quality"]
    per_asset = forcing.asset_pv(
        samples, m, connected, ev, PVM, allow_low, PVM["capacity"]["include_undated"]
    )
    shares = aggregate.node_shares({a: nodes[a] for a in connected["asset_id"]})
    bus = aggregate.to_bus(
        per_asset.rename(columns={"slot": "timestamp", "status": "quality"})[
            ["timestamp", "asset_id", "active_capacity_mw", "estimated_pv_mw", "quality"]
        ],
        shares,
    )
    acq_offset = float(m["acquisition_offset_min"].mean())
    stats = []
    for t in ds["time"].values:
        s = forcing.field_slot_stats(
            ds.sel(time=t),
            NAMES,
            pd.Timestamp(t, tz="UTC") + pd.Timedelta(minutes=acq_offset),
            EVT["thresholds"],
            allow_low,
        )
        stats.append({"slot": pd.Timestamp(t, tz="UTC"), **s})
    PROC.mkdir(parents=True, exist_ok=True)
    per_asset.to_parquet(PROC / "pv_by_asset.parquet", index=False)
    per_asset[
        [
            "slot",
            "asset_id",
            "pixel_id",
            "native_pixel_id",
            "sampled_native_pixel_id",
            "ghi",
            "dhi",
            "dni",
            "clearsky_index",
            "status",
            "quality_flag",
        ]
    ].to_parquet(PROC / "irradiance_by_asset.parquet", index=False)
    bus.to_parquet(PROC / "pv_by_bus.parquet", index=False)
    pd.DataFrame(stats).to_parquet(PROC / "field_stats.parquet", index=False)
    gate_file = OUT / "first_file_gate.json"
    version = (
        json.loads(gate_file.read_text())["lsasaf_mdssftd"].get("product_version")
        if gate_file.exists()
        else None
    )
    checks = validate_series(per_asset, m)
    pd.DataFrame([{"check": k, "value": v} for k, v in checks.items()]).to_csv(
        TABLES / "e3_pv_satellite_checks.csv", index=False
    )
    return {
        "slots": int(ds.sizes["time"]),
        "files": len(files),
        "assets": int(per_asset["asset_id"].nunique()),
        "product_version_from_gate": version,
        "validation": checks,
    }


def validate_series(pa: pd.DataFrame, mapped: pd.DataFrame) -> dict[str, Any]:
    """Real-data checks of the satellite-driven series (no UKPN data, nothing fitted)."""
    start, end = (
        pd.Timestamp(EVT["search_period"]["start"]),
        pd.Timestamp(EVT["search_period"]["end"]),
    )
    expected = len(daylight_slots(start, end))
    act = pa[pa["active_capacity_mw"] > 0]
    fleet = act.groupby("slot").agg(
        p=("estimated_pv_mw", lambda s: s.sum(min_count=len(s)) if s.notna().all() else np.nan),
        cap=("active_capacity_mw", "sum"),
    )
    fleet["cf"] = fleet["p"] / fleet["cap"]
    valid = fleet["p"].notna()
    idx = fleet.index.to_series()
    consecutive = idx.diff() == pd.Timedelta(minutes=EVT["step_minutes"])
    ramp = fleet["p"].diff().where(consecutive & valid & valid.shift(fill_value=False))
    good = act[act["status"] == "GOOD"]
    q = act["status"].value_counts(normalize=True)
    # assets reading the same native pixel through the NetCDF must get (nearly) the same CF
    smp = mapped.set_index("asset_id")["sampled_native_pixel_id"]
    act2 = act.assign(spix=act["asset_id"].map(smp))
    spread = act2.groupby(["slot", "spix"])["capacity_factor"].agg(lambda s: s.max() - s.min())
    pct = [0.05, 0.25, 0.5, 0.75, 0.95, 0.99]
    return {
        "daylight_slots_expected": expected,
        "slots_retrieved": int(fleet.shape[0]),
        "slots_missing_from_archive_or_failed": int(expected - fleet.shape[0]),
        "slots_rejected_any_active_asset_unusable": int((~valid).sum()),
        "slots_usable": int(valid.sum()),
        "asset_slot_status_fractions": {k: round(float(v), 5) for k, v in q.items()},
        "missing_rate": float(q.get("MISSING", 0.0)),
        "low_quality_fraction": float(q.get("LOW_QUALITY", 0.0)),
        "invalid_fraction": float(q.get("INVALID", 0.0) + q.get("OUT_OF_RANGE", 0.0)),
        "ghi_wm2_range_good": [float(good["ghi"].min()), float(good["ghi"].max())],
        "ghi_wm2_percentiles_good": {
            str(k): float(v) for k, v in good["ghi"].quantile(pct).items()
        },
        "fleet_cf_percentiles": {str(k): float(v) for k, v in fleet["cf"].quantile(pct).items()},
        "fleet_cf_share_ge_0.9": float((fleet["cf"] >= 0.9).mean()),
        "active_capacity_mw": sorted({round(float(x), 6) for x in fleet["cap"]}),
        "aggregate_pv_max_mw": float(fleet["p"].max()),
        "aggregate_pv_max_slot": str(fleet["p"].idxmax()) if valid.any() else None,
        "ramp_mw_abs_percentiles": {str(k): float(v) for k, v in ramp.abs().quantile(pct).items()},
        "ramp_mw_max_up": float(ramp.max()),
        "ramp_mw_max_down": float(ramp.min()),
        "ramp_n_steps": int(ramp.notna().sum()),
        "bound_violations_p_gt_active_capacity": int(
            (act["estimated_pv_mw"] > act["active_capacity_mw"] + 1e-9).sum()
        ),
        "bound_violations_p_lt_0": int((pa["estimated_pv_mw"] < 0).sum()),
        "inactive_assets_nonzero_pv": int(
            (pa.loc[pa["active_capacity_mw"] == 0, "estimated_pv_mw"].fillna(0) != 0).sum()
        ),
        "same_sampled_pixel_max_cf_spread": float(spread.max()) if len(spread) else None,
    }


def night_check(inv: pd.DataFrame, ev: dict, mapped: pd.DataFrame) -> dict[str, Any]:
    """Four real night slots (4 requests, polite client): status must be NIGHT and PV exactly 0."""
    env = LSA["access"]["credentials_env"]
    cred = credentials.load("LSA SAF data service", env["user"], env["secret"])
    client = lsasaf.PoliteClient(cred, LSA["access"]["politeness"]["pause_s"])
    product = lsasaf.Product.from_config(LSA)
    g = LSA["expected"]["grid"]
    box = lsasaf.index_box(
        g["lat_first"],
        g["lat_step"],
        g["lon_first"],
        g["lon_step"],
        LSA["study_area"]["analysis_bbox"],
    )
    vars_ = [NAMES["total"], NAMES["diffuse_fraction"], NAMES["quality"]]
    slots = pd.date_range("2024-06-15T00:00Z", periods=4, freq="15min")
    parts = [
        lsasaf.decode(
            lsasaf.parse_dap_ascii(
                client.get_text(lsasaf.dap_ascii_url(product, s.to_pydatetime(), box, vars_)), vars_
            ),
            LSA["verified_packing"],
            s.to_pydatetime(),
        )
        for s in slots
    ]
    ds = xr.concat(parts, dim="time")
    connected = inv[inv["status"] == "Connected"]
    m = mapped[mapped["asset_id"].isin(connected["asset_id"])]
    pa = forcing.asset_pv(forcing.sample_assets(ds, m, NAMES), m, connected, ev, PVM, False)
    return {
        "slots": [str(s) for s in slots],
        "requests": client.requests_made,
        "status_counts": pa["status"].value_counts().to_dict(),
        "dssf_values": sorted({float(x) for x in pa["ghi"].dropna()}),
        "max_pv_mw": float(pa["estimated_pv_mw"].max()),
        "pass": bool((pa["estimated_pv_mw"] == 0).all() and (pa["status"] == "NIGHT").all()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--acquire", action="store_true")
    ap.add_argument("--start", default=EVT["search_period"]["start"])
    ap.add_argument("--end", default=EVT["search_period"]["end"])
    ap.add_argument("--night-check", action="store_true", help="4 real night slots (4 requests)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    status: dict[str, Any] = {"run_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}

    table, ev, recon, mapped, nodes = build_inventory()
    table.to_csv(TABLES / "e3_pv_assets.csv", index=False)
    status["inventory"] = {
        "assets": len(table),
        "connected_mw_today": float(table.loc[table.status == "Connected", "capacity_mw"].sum()),
        "active_mw_search_period": float(table["active_capacity_search_mw"].sum()),
        "ltds_reconciliation": recon,
    }
    checks = model_checks(PVM)
    checks.to_csv(TABLES / "e3_pv_model_checks.csv", index=False)
    status["model_checks"] = checks.attrs["checks"]

    if args.acquire:
        try:
            status["acquire"] = acquire(pd.Timestamp(args.start), pd.Timestamp(args.end))
        except credentials.AuthenticationBoundary as e:
            status["acquire"] = {"status": "BLOCKED_AUTH", "message": str(e)}
    (OUT / "pv_timeseries.json").write_text(json.dumps(status, indent=2, default=str))
    if args.night_check:
        status["night_check"] = night_check(table, ev, mapped)
    series = satellite_series(table, ev, mapped, nodes)
    status["satellite_series"] = series or {
        "status": "NO_SATELLITE_DATA",
        "message": "no MDSSFTD crops in data/interim/satellite/lsasaf/analysis/ — run with "
        "--acquire once LSA SAF credentials are configured",
    }
    (OUT / "pv_timeseries.json").write_text(json.dumps(status, indent=2, default=str))
    print(
        json.dumps({k: status[k] for k in ("inventory", "model_checks")}, indent=1, default=str)[
            :3000
        ]
    )
    print("satellite series:", status["satellite_series"].get("status", "OK"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

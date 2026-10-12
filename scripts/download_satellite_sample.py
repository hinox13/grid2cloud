"""E3 first-file gate: minimal real satellite samples (no bulk downloads).

    uv run --env-file .env python scripts/download_satellite_sample.py

Steps (each recorded in reports/experiments/e3_satellite/first_file_gate.json):
  1. LSA SAF public static geometry (native lat/lon, regular-grid land/water mask) — no auth.
  2. LSA SAF catalog: the archive listing for the gate day (public) — the file must exist.
  3. LSA SAF MDSSFTD: download EXACTLY ONE NetCDF file (HTTP basic auth from
     LSASAF_USERNAME / LSASAF_PASSWORD), inspect variables/units/grid/fill/quality, crop to the
     context box, sample the Sundon assets. Without credentials: stop cleanly at the
     authentication boundary (status BLOCKED_AUTH) — nothing else is attempted for LSA SAF.
  4. EUMETSAT RGB (E-View + Natural Colour Enhanced) via EUMETView WMS — anonymous: two
     cropped frames, served time read from the server header, paired with the MDSSFTD slot.

Every acquired file is gated by the licence registry and recorded in metadata/provenance.json
(source URL without credentials, requested/served time, size, SHA-256, git commit).
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402
import xarray as xr  # noqa: E402
import yaml  # noqa: E402
from PIL import Image  # noqa: E402

from cloud2grid.licensing import gate  # noqa: E402
from cloud2grid.licensing.registry import REPO_ROOT, Registry  # noqa: E402
from cloud2grid.satellite import credentials, eumetsat, lsasaf, quality  # noqa: E402
from cloud2grid.satellite import geometry as geo  # noqa: E402
from cloud2grid.utils import provenance  # noqa: E402

LSA = yaml.safe_load((REPO_ROOT / "configs/data/lsasaf.yaml").read_text())
EUM = yaml.safe_load((REPO_ROOT / "configs/data/eumetsat.yaml").read_text())
OUT = REPO_ROOT / "reports/experiments/e3_satellite"
TABLES = REPO_ROOT / "reports/tables"
FIGS = REPO_ROOT / "reports/figures"
SUNDON_CENTRE = (51.93, -0.60)
CANTERBURY_CENTRE = (51.27, 1.10)


def git_commit() -> dict[str, Any]:
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO_ROOT
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, cwd=REPO_ROOT
        ).stdout.strip()
    )
    return {"git_commit": sha, "working_tree_dirty": dirty}


def fetch_public(share: str, name: str, dest: Path) -> dict[str, Any]:
    """Public Nextcloud share (the share token is a public link id, not a credential)."""
    token = share.rstrip("/").rsplit("/", 1)[-1]
    url = f"{share.rsplit('/s/', 1)[0]}/public.php/webdav/{name}"
    r = requests.get(url, auth=(token, ""), timeout=300)
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return {"url": f"{share} → {name}", "size_bytes": len(r.content)}


def step_static(reg: Registry, commit: dict) -> dict[str, Any]:
    gate.require("lsa_saf_msg_static", "download", reg)
    sg = LSA["static_geometry"]
    static = REPO_ROOT / LSA["storage"]["raw_dir"] / "static"
    out = {}
    for share, name in [
        (sg["share"], sg["native_lat"]),
        (sg["share"], sg["native_lon"]),
        (sg["regular_grid_share"], sg["regular_grid_mask"]),
    ]:
        dest = static / name
        if not dest.exists():
            fetch_public(share, name, dest)
        e = provenance.record(
            dest,
            source_id="lsa_saf_msg_static",
            url=f"{share} (file {name})",
            licence="CC-BY-4.0",
            extra={
                "provider": "EUMETSAT LSA SAF",
                "product": "MSG static grid / land-water mask",
                "processing_level": "static auxiliary",
                **commit,
            },
        )
        out[name] = {k: e[k] for k in ("size_bytes", "sha256", "local_path")}
    return out


def step_catalog(product: lsasaf.Product, slot: dt.datetime) -> dict[str, Any]:
    listing = lsasaf.list_day(product, slot.date())
    row = listing[listing["slot"] == slot]
    return {
        "day_url": product.day_url(slot.date()),
        "files_listed_for_day": int(len(listing)),
        "first_slot": str(listing["slot"].min()) if len(listing) else None,
        "last_slot": str(listing["slot"].max()) if len(listing) else None,
        "gate_file": product.file_name(slot),
        "gate_file_listed": bool(len(row)),
        "gate_file_size_listed": row["size"].iloc[0] if len(row) else None,
        "listing_public": True,
    }


def step_mdssftd(
    product: lsasaf.Product, slot: dt.datetime, reg: Registry, commit: dict
) -> dict[str, Any]:
    env = LSA["access"]["credentials_env"]
    try:
        cred = credentials.load("LSA SAF data service", env["user"], env["secret"])
    except credentials.AuthenticationBoundary as e:
        return {
            "status": "BLOCKED_AUTH",
            "message": str(e),
            "credentials_set": credentials.status([env["user"], env["secret"]]),
        }
    gate.require("lsa_saf_mdssftd", "download", reg)
    raw_dir = REPO_ROOT / LSA["storage"]["raw_dir"] / "netcdf"
    try:
        d = lsasaf.download(product, slot, raw_dir, cred)
    except lsasaf.DownloadError as e:
        return {"status": "DOWNLOAD_FAILED", "message": cred.redact(str(e))}
    raw = lsasaf.open_raw(d["local_path"])
    ds = lsasaf.open_product(d["local_path"])
    info = lsasaf.inspect(raw, ds)
    checks = lsasaf.check_expectations(info, LSA["expected"])
    version = {
        k: info["global_attrs"].get(k)
        for k in (
            "algorithm_version",
            "base_algorithm_version",
            "platform",
            "processing_level",
            "date_created",
        )
    }
    provenance.record(
        d["local_path"],
        source_id="lsa_saf_mdssftd",
        url=d["url"],
        licence="CC-BY-4.0",
        revision=str(version.get("algorithm_version")),
        extra={
            "provider": "EUMETSAT LSA SAF",
            "product": "MDSSFTD (LSA-207)",
            "product_version": version,
            "requested_timestamp": slot.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "processing_level": "L3 product as distributed (full MSG-Disk NetCDF4)",
            **commit,
        },
    )
    v = LSA["expected"]["variables"]
    crop = lsasaf.crop(
        ds[[v["total"], v["diffuse_fraction"], v["quality"]]], LSA["study_area"]["context_bbox"]
    )
    crop_path = (
        REPO_ROOT / LSA["storage"]["crop_dir"] / "gate" / f"MDSSFTD_context_{slot:%Y%m%d%H%M}.nc"
    )
    crop_path.parent.mkdir(parents=True, exist_ok=True)
    enc = {k: {"zlib": True, "complevel": 4} for k in crop.data_vars}
    crop.to_netcdf(crop_path, encoding=enc)
    provenance.record(
        crop_path,
        source_id="lsa_saf_mdssftd",
        url=d["url"],
        licence="CC-BY-4.0",
        extra={
            "derived_from_sha256": d["sha256"],
            "processing_level": "cropped to context_bbox (no resampling)",
            "bbox": LSA["study_area"]["context_bbox"],
            **commit,
        },
    )
    # quality over the context box
    q = crop[v["quality"]].values.squeeze()
    tot = crop[v["total"]].values.squeeze()
    fr = crop[v["diffuse_fraction"]].values.squeeze()
    status = quality.classify(q, tot, fr)
    vals, counts = np.unique(status.astype(str), return_counts=True)
    flags, fcounts = np.unique(q[np.isfinite(q)].astype(int), return_counts=True)
    return {
        "status": "OK" if all(c["ok"] for c in checks) else "STRUCTURE_MISMATCH",
        "download": {k: str(v_) for k, v_ in d.items()},
        "inspection": info,
        "checks": checks,
        "product_version": version,
        "crop": {
            "path": str(crop_path.relative_to(REPO_ROOT)),
            "size_bytes": crop_path.stat().st_size,
            "dims": {k: int(x) for k, x in crop.sizes.items()},
        },
        "context_status_counts": dict(zip(vals.tolist(), counts.tolist(), strict=True)),
        "context_flag_counts": {
            f"{int(f)} ({quality.describe(int(f))})": int(c)
            for f, c in zip(flags, fcounts, strict=True)
        },
        "grid_from_file": geo.RegularGrid.from_coords(ds["lat"].values, ds["lon"].values).__dict__,
    }


def step_rgb(
    slots: list[dt.datetime], radiation_slot: dt.datetime, reg: Registry, commit: dict
) -> tuple[dict, pd.DataFrame]:
    bbox = LSA["study_area"]["context_bbox"]
    frame_dir = REPO_ROOT / EUM["storage"]["frame_dir"]
    nat_c, nat_l = geo.native_pixel(np.array([SUNDON_CENTRE[0]]), np.array([SUNDON_CENTRE[1]]))
    acq = float(geo.acquisition_offset_min(nat_l)[0])
    frames, pairs = {}, []
    for key in ("eview", "ncl_enh"):
        layer = eumetsat.WMSLayer.from_config(EUM, key)
        gate.require(layer.source_id, "download", reg)
        for t in slots:
            dest = frame_dir / key / f"{key}_{t:%Y%m%dT%H%M}_context.png"
            meta = eumetsat.fetch_frame(
                layer, bbox, t, dest, EUM["sample"]["width_px"], EUM["sample"]["format"]
            )
            served = pd.Timestamp(meta["served_time"]).to_pydatetime()
            provenance.record(
                dest,
                source_id=layer.source_id,
                url=meta["source_url"],
                licence="CC-BY-4.0",
                extra={
                    k: meta[k]
                    for k in (
                        "provider",
                        "product",
                        "wms_layer",
                        "requested_time",
                        "served_time",
                        "bbox_wgs84",
                        "crs",
                        "processing_level",
                    )
                }
                | commit,
            )
            frames[f"{key}@{t:%H%M}"] = meta | {"local_path": str(dest.relative_to(REPO_ROOT))}
            # pair each frame with the MDSSFTD slot of the same nominal time
            pair = eumetsat.match(t, t, served, acq, EUM["matching"]["max_delta_min"])
            pair.update({"product": layer.collection_id, "radiation_slot_listed": None})
            pairs.append(pair)
    # an explicit mismatched pairing, to show the rejection rule working
    pairs.append(
        eumetsat.match(
            slots[0],
            radiation_slot,
            radiation_slot + dt.timedelta(minutes=15),
            acq,
            EUM["matching"]["max_delta_min"],
        )
        | {
            "product": "rejection-rule demonstration (frame 15 min later)",
            "radiation_slot_listed": None,
        }
    )
    return frames, pd.DataFrame(pairs)


def rgb_figure(frames: dict[str, Any], path: Path) -> None:
    bbox = LSA["study_area"]["context_bbox"]
    ab = LSA["study_area"]["analysis_bbox"]
    keys = list(frames)
    # Georeferencing check: LSA SAF land/water mask coastline (sea = 0) over each frame.
    mask = xr.open_dataset(
        REPO_ROOT
        / LSA["storage"]["raw_dir"]
        / "static"
        / LSA["static_geometry"]["regular_grid_mask"]
    )["LWMASK"].isel(time=0)
    mask = lsasaf.crop(mask.to_dataset(), bbox)["LWMASK"]
    fig, axes = plt.subplots(1, len(keys), figsize=(7 * len(keys), 4.6))
    for ax, k in zip(np.atleast_1d(axes), keys, strict=True):
        f = frames[k]
        img = Image.open(REPO_ROOT / f["local_path"])
        ax.imshow(img, extent=(bbox["lon_min"], bbox["lon_max"], bbox["lat_min"], bbox["lat_max"]))
        ax.contour(
            mask["lon"],
            mask["lat"],
            (mask > 0).astype(float),
            levels=[0.5],
            colors="cyan",
            linewidths=0.6,
        )
        ax.add_patch(
            plt.Rectangle(
                (ab["lon_min"], ab["lat_min"]),
                ab["lon_max"] - ab["lon_min"],
                ab["lat_max"] - ab["lat_min"],
                fill=False,
                ec="red",
                lw=1,
            )
        )
        ax.plot(*SUNDON_CENTRE[::-1], "r+", ms=10)
        ax.plot(*CANTERBURY_CENTRE[::-1], "c+", ms=10)
        ax.set_title(f"{f['product']} served {f['served_time']}", fontsize=9)
        ax.set_aspect(1 / np.cos(np.radians(52)))
    fig.text(
        0.01,
        0.01,
        "Contains modified EUMETSAT Meteosat data 2024 (EUMETView WMS; CC BY 4.0). "
        "Cyan line: LSA SAF land/water mask coastline (georeferencing check). "
        "Red box: event-analysis area; + Sundon (red), Canterbury South (cyan).",
        fontsize=7,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main() -> int:
    for d in (OUT, TABLES, FIGS):
        d.mkdir(parents=True, exist_ok=True)
    reg = Registry.load()
    commit = git_commit()
    product = lsasaf.Product.from_config(LSA)
    slot = pd.Timestamp(LSA["first_file_gate"]["slot"]).to_pydatetime()
    result: dict[str, Any] = {
        "run_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        **commit,
    }

    result["static_geometry"] = step_static(reg, commit)
    result["lsasaf_catalog"] = step_catalog(product, slot)
    result["lsasaf_mdssftd"] = step_mdssftd(product, slot, reg, commit)
    print(f"LSA SAF MDSSFTD: {result['lsasaf_mdssftd']['status']}")

    rgb_slots = [pd.Timestamp(s).to_pydatetime() for s in EUM["sample"]["slots"]]
    frames, pairs = step_rgb(rgb_slots, slot, reg, commit)
    pairs["radiation_slot_listed"] = result["lsasaf_catalog"]["gate_file_listed"]
    result["rgb_frames"] = frames
    pairs.to_csv(TABLES / "e3_time_matching.csv", index=False)
    result["time_matching"] = pairs.to_dict("records")
    rgb_figure({k: v for k, v in frames.items() if k.endswith("1200")}, FIGS / "e3_rgb_sample.png")
    (OUT / "first_file_gate.json").write_text(json.dumps(result, indent=2, default=str))
    print(
        json.dumps(
            {
                k: (v.get("status") if isinstance(v, dict) and "status" in v else "ok")
                for k, v in result.items()
                if isinstance(v, dict)
            },
            indent=1,
        )
    )
    print(
        pairs[
            [
                "product",
                "requested_time",
                "radiation_slot",
                "rgb_time",
                "time_delta_min",
                "accepted",
            ]
        ].to_string(index=False)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

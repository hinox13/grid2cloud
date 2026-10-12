"""EUMETSAT RGB imagery (E-View / Natural Colour Enhanced) via EUMETView WMS.

The EUMETSAT catalogue records of EO:EUM:DAT:MSG:EVIEW and EO:EUM:DAT:MSG:NCL_ENH list a single
distribution channel, "EUMETView" (WMS GetMap; GeoTIFF/PNG), with policy "Free and
unrestricted - CC-BY-4.0"; the Data Store search returns no products for them. EUMETView WMS
is anonymous and crops server-side to the requested bounding box.

Frame time is never inferred from the request: the layer's time dimension uses
`nearestValue="1"`, and GeoServer reports the time actually served in the response header
`Warning: 99 Nearest value used: time=<ISO8601> …`. A response without that header is rejected.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import requests

NEAREST_RE = re.compile(r"Nearest value used:\s*time=(\S+)")


class FrameTimeUnknown(RuntimeError):
    """The server did not state which time it served."""


@dataclass(frozen=True)
class WMSLayer:
    endpoint: str
    layer: str
    collection_id: str
    source_id: str

    @classmethod
    def from_config(cls, cfg: dict[str, Any], key: str) -> WMSLayer:
        p = cfg["products"][key]
        return cls(cfg["wms"]["endpoint"], p["wms_layer"], p["collection_id"], p["source_id"])


def getmap_params(
    layer: WMSLayer, bbox: dict[str, float], time: dt.datetime, width: int, fmt: str
) -> dict[str, str]:
    """WMS 1.3.0 GetMap in EPSG:4326 (axis order lat, lon); height keeps square degrees."""
    height = round(
        width * (bbox["lat_max"] - bbox["lat_min"]) / (bbox["lon_max"] - bbox["lon_min"])
    )
    return {
        "service": "WMS",
        "version": "1.3.0",
        "request": "GetMap",
        "layers": layer.layer,
        "styles": "",
        "crs": "EPSG:4326",
        "bbox": f"{bbox['lat_min']},{bbox['lon_min']},{bbox['lat_max']},{bbox['lon_max']}",
        "width": str(width),
        "height": str(height),
        "format": fmt,
        "time": time.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def served_time(headers: dict[str, str] | requests.structures.CaseInsensitiveDict) -> dt.datetime:
    """Time actually served, from GeoServer's nearest-value warning header."""
    warning = headers.get("Warning") or headers.get("warning") or ""
    m = NEAREST_RE.search(warning)
    if not m:
        raise FrameTimeUnknown(f"no served-time header (Warning={warning!r})")
    return pd.Timestamp(m.group(1)).tz_convert("UTC").to_pydatetime()


def fetch_frame(
    layer: WMSLayer,
    bbox: dict[str, float],
    time: dt.datetime,
    dest: Path,
    width: int = 1100,
    fmt: str = "image/png",
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Fetch one cropped frame; returns provenance including the served time and SHA-256."""
    s = session or requests.Session()
    params = getmap_params(layer, bbox, time, width, fmt)
    r = s.get(layer.endpoint, params=params, timeout=120)
    r.raise_for_status()
    ctype = r.headers.get("Content-Type", "")
    if not ctype.startswith("image/"):
        raise RuntimeError(f"WMS returned {ctype}: {r.text[:300]}")
    served = served_time(r.headers)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return {
        "provider": "EUMETSAT",
        "product": layer.collection_id,
        "wms_layer": layer.layer,
        "source_id": layer.source_id,
        "source_url": r.url,
        "requested_time": params["time"],
        "served_time": served.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bbox_wgs84": [bbox["lon_min"], bbox["lat_min"], bbox["lon_max"], bbox["lat_max"]],
        "crs": "EPSG:4326",
        "width": int(params["width"]),
        "height": int(params["height"]),
        "format": ctype,
        "local_path": str(dest),
        "size_bytes": len(r.content),
        "sha256": hashlib.sha256(r.content).hexdigest(),
        "processing_level": "Visualisation (RGB Advanced Image Product), server-side crop",
    }


# --------------------------------------------------------------------------- time matching


def match(
    requested: dt.datetime,
    radiation_slot: dt.datetime,
    rgb_time: dt.datetime,
    acquisition_offset_min: float,
    max_delta_min: float,
) -> dict[str, Any]:
    """Pair a quantitative (MDSSFTD) slot with a visual (RGB) frame.

    Both products come from the same SEVIRI repeat cycle and label frames by the nominal slot
    (scan start). The scene over the study area is observed `acquisition_offset_min` after the
    slot in BOTH products (same scan line), so the delta is computed on nominal times and the
    acquisition time is reported alongside. Pairs with |delta| > max_delta_min are rejected.
    """
    delta = (rgb_time - radiation_slot).total_seconds() / 60.0
    acq = dt.timedelta(minutes=acquisition_offset_min)
    return {
        "requested_time": requested.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "radiation_slot": radiation_slot.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "radiation_time": (radiation_slot + acq).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rgb_time": rgb_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rgb_acquisition_time": (rgb_time + acq).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "time_delta_min": delta,
        "max_delta_min": max_delta_min,
        "accepted": abs(delta) <= max_delta_min,
    }

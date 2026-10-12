"""LSA SAF MDSSFTD (LSA-207) access: catalog, download, open, crop, inspect.

Access paths (LSA SAF data service README, `https://datalsasaf.lsasvcs.ipma.pt/`):

* HTTPS archive `PRODUCTS/MSG/MDSSFTD/<NETCDF|HDF5>/YYYY/MM/DD/<file>`: the directory listing is
  public (used here as the catalog); file downloads need HTTP basic auth (registered users).
* THREDDS/OpenDAP `thredds/dodsC/MSG/MDSSFTD/NETCDF/YYYY/MM/DD/<file>`: server-side subsetting
  of the NetCDF files; same credentials.

Credentials are passed as a `requests` session/auth object — never inside a URL — and every
error message is passed through `Credential.redact` before it can be printed.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
import xarray as xr

from cloud2grid.satellite.credentials import Credential

SLOT_RE = re.compile(r"_(\d{12})(?:\.nc)?$")


@dataclass(frozen=True)
class Product:
    https_base: str
    opendap_base: str
    netcdf_dir: str
    filename: str  # e.g. "NETCDF4_LSASAF_MSG_MDSSFTD_MSG-Disk_{slot}.nc"
    step_minutes: int

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> Product:
        a = cfg["access"]
        return cls(
            https_base=a["https_base"].rstrip("/"),
            opendap_base=a["opendap_base"].rstrip("/"),
            netcdf_dir=a["netcdf_dir"],
            filename=a["filename"],
            step_minutes=int(cfg["product"]["step_minutes"]),
        )

    def file_name(self, slot: dt.datetime) -> str:
        return self.filename.format(slot=slot.strftime("%Y%m%d%H%M"))

    def rel_path(self, slot: dt.datetime) -> str:
        return f"{self.netcdf_dir}/{slot:%Y/%m/%d}/{self.file_name(slot)}"

    def https_url(self, slot: dt.datetime) -> str:
        return f"{self.https_base}/{self.rel_path(slot)}"

    def opendap_url(self, slot: dt.datetime) -> str:
        return f"{self.opendap_base}/{self.rel_path(slot)}"

    def day_url(self, day: dt.date) -> str:
        return f"{self.https_base}/{self.netcdf_dir}/{day:%Y/%m/%d}/"


def parse_slot(name: str) -> dt.datetime:
    """Nominal slot (UTC) from an LSA SAF file name. The slot is the START of the SEVIRI scan,
    not the acquisition time of any given pixel (PUM §6.3)."""
    m = SLOT_RE.search(Path(name).name)
    if not m:
        raise ValueError(f"no slot timestamp in {name!r}")
    return dt.datetime.strptime(m.group(1), "%Y%m%d%H%M").replace(tzinfo=dt.UTC)


def slots(start: dt.datetime, end: dt.datetime, step_minutes: int) -> list[dt.datetime]:
    """Nominal slots in [start, end], aligned to the product step."""
    idx = pd.date_range(start, end, freq=f"{step_minutes}min", tz="UTC")
    return [t.to_pydatetime() for t in idx if t.minute % step_minutes == 0]


# ------------------------------------------------------------------------------- catalog


def parse_listing(html: str) -> pd.DataFrame:
    """Files and sizes from an archive directory listing (public HTML index)."""
    rows = re.findall(
        r'href="[^"]*/([^"/]+\.nc)".*?(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*</td>\s*<td[^>]*>\s*'
        r"([\d.]+\s*[KMG]?B?)",
        html,
        flags=re.S,
    )
    if not rows:  # plain-text style index ("name  date  size")
        rows = re.findall(
            r"(NETCDF4_\S+?\.nc)\S*\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s+([\d.]+\s*[KMG]?B?)", html
        )
    df = pd.DataFrame(rows, columns=["file", "modified", "size"]).drop_duplicates("file")
    df["slot"] = [parse_slot(f) for f in df["file"]]
    df["size_bytes"] = [_size_bytes(s) for s in df["size"]]
    return df.sort_values("slot").reset_index(drop=True)


def _size_bytes(text: str) -> int:
    m = re.match(r"([\d.]+)\s*([KMG]?)", text.strip())
    if not m:
        return -1
    mult = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3}[m.group(2)]
    return int(float(m.group(1)) * mult)


def list_day(
    product: Product, day: dt.date, session: requests.Session | None = None
) -> pd.DataFrame:
    """Catalog for one day from the public archive listing (no credentials needed)."""
    s = session or requests.Session()
    r = s.get(product.day_url(day), timeout=60)
    r.raise_for_status()
    return parse_listing(r.text)


# ------------------------------------------------------------------------------ download


class DownloadError(RuntimeError):
    pass


def download(
    product: Product, slot: dt.datetime, dest_dir: Path, cred: Credential, timeout_s: float = 300
) -> dict[str, Any]:
    """Download one full-disk NetCDF file (HTTPS + basic auth). Returns size and SHA-256."""
    url = product.https_url(slot)
    dest = Path(dest_dir) / product.file_name(slot)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    digest = hashlib.sha256()
    try:
        with requests.get(url, auth=cred.basic_auth(), stream=True, timeout=timeout_s) as r:
            if r.status_code == 401:
                raise DownloadError(f"HTTP 401 for {url}: credentials rejected")
            r.raise_for_status()
            with tmp.open("wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
                    digest.update(chunk)
    except requests.RequestException as e:  # never let a URL with secrets escape
        tmp.unlink(missing_ok=True)
        raise DownloadError(cred.redact(str(e))) from None
    tmp.replace(dest)
    return {
        "local_path": dest,
        "url": url,
        "size_bytes": dest.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def open_subset_opendap(
    product: Product,
    slot: dt.datetime,
    bbox: dict[str, float],
    variables: list[str],
    cred: Credential,
) -> xr.Dataset:
    """Server-side spatial subset via THREDDS/OpenDAP (pydap engine, credentials in session)."""
    session = requests.Session()
    session.auth = cred.basic_auth()
    try:
        ds = xr.open_dataset(product.opendap_url(slot), engine="pydap", session=session)
        return crop(ds[variables], bbox).load()
    except Exception as e:  # noqa: BLE001 — re-raised redacted
        raise DownloadError(
            cred.redact(f"OpenDAP subset failed for {slot:%Y%m%d%H%M}: {e}")
        ) from None


# ------------------------------------------------------------------------- open / inspect


def open_product(path: Path) -> xr.Dataset:
    """Open a MDSSFTD NetCDF file with CF decoding (scale_factor, add_offset, _FillValue)."""
    return xr.open_dataset(path, mask_and_scale=True, decode_times=True)


def open_raw(path: Path) -> xr.Dataset:
    """Same file without CF decoding: the stored integers and their encoding attributes."""
    return xr.open_dataset(path, mask_and_scale=False, decode_times=False)


def crop(ds: xr.Dataset, bbox: dict[str, float]) -> xr.Dataset:
    """Crop to bbox {lat_min, lat_max, lon_min, lon_max}; handles descending latitude."""
    lat = ds["lat"].values
    lat_slice = (
        slice(bbox["lat_max"], bbox["lat_min"])
        if lat[0] > lat[-1]
        else slice(bbox["lat_min"], bbox["lat_max"])
    )
    out = ds.sel(lat=lat_slice, lon=slice(bbox["lon_min"], bbox["lon_max"]))
    if out.sizes["lat"] == 0 or out.sizes["lon"] == 0:
        raise ValueError("bbox does not intersect the product grid")
    return out


def inspect(raw: xr.Dataset, decoded: xr.Dataset) -> dict[str, Any]:
    """Everything the first-file gate must report, read from the file itself."""
    lat, lon = decoded["lat"].values, decoded["lon"].values
    variables = {}
    for name, var in raw.data_vars.items():
        variables[name] = {
            "dims": list(var.dims),
            "stored_dtype": str(var.dtype),
            "attrs": {k: _plain(v) for k, v in var.attrs.items()},
        }
    times = decoded["time"].values if "time" in decoded else []
    return {
        "dims": {k: int(v) for k, v in decoded.sizes.items()},
        "variables": variables,
        "coords": {
            "lat": {
                "first": float(lat[0]),
                "last": float(lat[-1]),
                "step": float(np.diff(lat).mean()),
                "n": len(lat),
                "attrs": {k: _plain(v) for k, v in raw["lat"].attrs.items()},
            },
            "lon": {
                "first": float(lon[0]),
                "last": float(lon[-1]),
                "step": float(np.diff(lon).mean()),
                "n": len(lon),
                "attrs": {k: _plain(v) for k, v in raw["lon"].attrs.items()},
            },
        },
        "time_values": [str(pd.Timestamp(t)) for t in np.atleast_1d(times)],
        "time_attrs": {k: _plain(v) for k, v in raw["time"].attrs.items()} if "time" in raw else {},
        "global_attrs": {k: _plain(v) for k, v in raw.attrs.items()},
    }


def is_wm2(units: str) -> bool:
    """True for the spellings of W/m² used in CF/LSA SAF metadata (W/m2, W m-2, W.m-2, …)."""
    u = re.sub(r"[\s.*^]", "", units).lower()
    return u in {"w/m2", "wm-2"}


def _plain(v: Any) -> Any:
    if isinstance(v, np.ndarray):
        return v.tolist()
    if isinstance(v, np.generic):
        return v.item()
    if isinstance(v, bytes):
        return v.decode(errors="replace")
    return v


def check_expectations(info: dict[str, Any], expected: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare the inspected file with the documented structure (PUM + official tutorial).
    Returns one row per check; the gate fails if any `ok` is False."""
    checks = []
    names = set(info["variables"])
    for role, var in expected["variables"].items():
        checks.append(
            {"check": f"variable {role} = {var}", "ok": var in names, "found": sorted(names)}
        )
    tot = info["variables"].get(expected["variables"]["total"], {})
    units = str(tot.get("attrs", {}).get("units", ""))
    checks.append({"check": "total flux units are W m-2", "ok": is_wm2(units), "found": units})
    g = expected["grid"]
    for ax in ("lat", "lon"):
        c = info["coords"][ax]
        checks.append(
            {
                "check": f"{ax} step {g[ax + '_step']}",
                "ok": abs(c["step"] - g[ax + "_step"]) < 1e-4,
                "found": c["step"],
            }
        )
    return checks


# ------------------------------------------------------- polite single-request DAP subsetting
#
# One HTTP request per slot: an OpenDAP ASCII response constrained to fixed index ranges of
# the three variables (about 6 KB). pydap would issue about 7 requests per slot (DDS, DAS,
# coordinates, each variable). THREDDS NCSS is not enabled on the LSA SAF server (HTTP 404,
# 2026-10-06). Values arrive PACKED; they are decoded with the packing verified on the real
# first-file-gate file (configs/data/lsasaf.yaml `verified_packing`).


class AuthRejected(DownloadError):
    """HTTP 401/403 — fatal: never retried (repeated failures can disable the account)."""


class Throttled(DownloadError):
    """HTTP 429/5xx — the caller backs off."""


def index_box(lat0: float, dlat: float, lon0: float, dlon: float, bbox: dict) -> tuple[int, ...]:
    """Inclusive (r0, r1, c0, c1) on the full product grid covering bbox."""
    rows = sorted(round((v - lat0) / dlat) for v in (bbox["lat_max"], bbox["lat_min"]))
    cols = sorted(round((v - lon0) / dlon) for v in (bbox["lon_min"], bbox["lon_max"]))
    return rows[0], rows[1], cols[0], cols[1]


def dap_ascii_url(
    product: Product, slot: dt.datetime, box: tuple[int, ...], variables: list[str]
) -> str:
    r0, r1, c0, c1 = box
    h = f"[0:1:0][{r0}:1:{r1}][{c0}:1:{c1}]"
    proj = (
        ",".join(f"{v}{h}" for v in variables) + f",lat[{r0}:1:{r1}],lon[{c0}:1:{c1}],time[0:1:0]"
    )
    return f"{product.opendap_url(slot)}.ascii?{proj}"


def parse_dap_ascii(text: str, variables: list[str]) -> dict[str, np.ndarray]:
    """Arrays from a DAP2 ASCII response: each `NAME.NAME[1][ny][nx]` block (rows `[0][i], …`),
    and the top-level `lat[n]`, `lon[n]`, `time[1]` lines."""
    body = text.split("-" * 45, 1)[-1]
    out: dict[str, np.ndarray] = {}
    for v in variables:
        m = re.search(rf"^{v}\.{v}\[1\]\[(\d+)\]\[(\d+)\]\n((?:\[0\]\[\d+\],.*\n)+)", body, re.M)
        if not m:
            raise ValueError(f"variable {v} not found in DAP response")
        ny, nx = int(m.group(1)), int(m.group(2))
        rows = [[float(x) for x in line.split(",")[1:]] for line in m.group(3).strip().splitlines()]
        arr = np.array(rows)
        if arr.shape != (ny, nx):
            raise ValueError(f"{v}: shape {arr.shape} != {(ny, nx)}")
        out[v] = arr
    for c in ("lat", "lon", "time"):
        m = re.search(rf"^{c}\[\d+\]\n(.+)$", body, re.M)
        if not m:
            raise ValueError(f"coordinate {c} not found in DAP response")
        out[c] = np.array([float(x) for x in m.group(1).split(",")])
    return out


def decode(raw: dict[str, np.ndarray], packing: dict[str, dict], slot: dt.datetime) -> xr.Dataset:
    """Packed arrays → CF-decoded dataset (fill → NaN, × scale), same layout as the product."""
    data = {}
    for v, p in packing.items():
        a = raw[v].astype(float)
        a[a == p["fill"]] = np.nan
        data[v] = (("time", "lat", "lon"), (a * p["scale"])[None])
    t = pd.DatetimeIndex(
        [pd.Timestamp(slot).tz_convert(None) + pd.Timedelta(seconds=raw["time"][0])]
    )
    lat = np.round(raw["lat"].astype(np.float32), 4)
    lon = np.round(raw["lon"].astype(np.float32), 4)
    return xr.Dataset(data, coords={"time": t, "lat": lat, "lon": lon})


class PoliteClient:
    """Sequential, rate-limited access with one reused session. 401/403 abort immediately."""

    def __init__(self, cred: Credential, pause_s: float, timeout_s: float = 120) -> None:
        self.session = requests.Session()
        self.session.auth = cred.basic_auth()
        self.cred = cred
        self.pause_s = pause_s
        self.timeout_s = timeout_s
        self.requests_made = 0
        self._last = 0.0

    def get_text(self, url: str) -> str:
        import time

        wait = self.pause_s - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        try:
            r = self.session.get(url, timeout=self.timeout_s)
        except requests.RequestException as e:
            raise DownloadError(self.cred.redact(f"{type(e).__name__}: {e}")) from None
        finally:
            self._last = time.monotonic()
            self.requests_made += 1
        if r.status_code in (401, 403):
            raise AuthRejected(f"HTTP {r.status_code}: credentials rejected — stopping")
        if r.status_code == 429 or r.status_code >= 500:
            raise Throttled(f"HTTP {r.status_code}")
        if r.status_code != 200:
            raise DownloadError(f"HTTP {r.status_code}")
        return r.text

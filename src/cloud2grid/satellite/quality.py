"""MDSSFTD quality control (LSA SAF PUM MDSSFTD v1.0 issue 3, Table 3 and Table 4).

The 8-bit quality flag is a bitfield:

    bits 0-1  land/sea      00 ocean · 01 land · 10 space · 11 continental water
    bits 2-4  cloud mask    000 unprocessed · 001 clear · 010 contaminated · 011 cloud filled
                            100 snow/ice · 101 undefined
    bits 5-7  algorithm     000 cloudy: ok · 001 clear: low quality / bad clear
                            010 cloudy: ATOA outside limits · 011 cloudy: algorithm failure
                            100 clear: ok · 101 clear: night · 110 clear: beyond view-angle limit
                            111 clear: not processed (cloud mask undefined)

    "For ocean and space pixels the values of the bits 2 to 7 are zero."

Every pixel gets one status:

    GOOD         land/continental water, cloud mask processed, algorithm "ok"
    LOW_QUALITY  algorithm 001 or 010: a value exists but the PUM flags it as degraded
    NIGHT        algorithm 101. Product v1.0.11+ sets DSSF = 0 at night, so irradiance = 0
    INVALID      algorithm 011/110/111, cloud mask unprocessed/undefined, ocean or space
    MISSING      the data value is the fill value or non-finite
    OUT_OF_RANGE the value lies outside the PUM physical range ([0, 1500] W/m2; fraction [0, 1])
"""

from __future__ import annotations

from enum import StrEnum

import numpy as np

SURFACE = {0: "ocean", 1: "land", 2: "space", 3: "continental_water"}
CLOUD = {
    0: "unprocessed",
    1: "clear",
    2: "contaminated",
    3: "cloud_filled",
    4: "snow_ice",
    5: "undefined",
}
ALGORITHM = {
    0: "cloudy_ok",
    1: "clear_low_quality",
    2: "cloudy_atoa_out_of_limits",
    3: "cloudy_algorithm_failure",
    4: "clear_ok",
    5: "clear_night",
    6: "clear_beyond_view_angle",
    7: "clear_not_processed",
}
DSSF_RANGE_WM2 = (0.0, 1500.0)
FRACTION_RANGE = (0.0, 1.0)


class Status(StrEnum):
    GOOD = "GOOD"
    LOW_QUALITY = "LOW_QUALITY"
    NIGHT = "NIGHT"
    INVALID = "INVALID"
    MISSING = "MISSING"
    OUT_OF_RANGE = "OUT_OF_RANGE"


# Ordered: a later status overrides an earlier one.
STATUS_CODES = {s: i for i, s in enumerate(Status)}


def decode(flag: np.ndarray | int) -> dict[str, np.ndarray]:
    """Split the flag into its three PUM fields (integer codes)."""
    q = np.asarray(flag)
    q = np.where(np.isfinite(q), q, 0).astype(np.int64) if q.dtype.kind == "f" else q
    return {"surface": q & 0b11, "cloud": (q >> 2) & 0b111, "algorithm": (q >> 5) & 0b111}


def describe(flag: int) -> str:
    d = {k: int(v) for k, v in decode(flag).items()}
    return f"{SURFACE[d['surface']]}|{CLOUD.get(d['cloud'], '?')}|{ALGORITHM[d['algorithm']]}"


def classify(flag: np.ndarray, dssf: np.ndarray, fraction: np.ndarray | None = None) -> np.ndarray:
    """Per-pixel `Status` (as a string array) from the flag and the decoded values."""
    flag = np.asarray(flag, dtype=float)
    d = decode(np.where(np.isfinite(flag), flag, 0))
    surface, cloud, alg = d["surface"], d["cloud"], d["algorithm"]
    out = np.full(flag.shape, Status.GOOD.value, dtype=object)

    on_surface = np.isin(surface, (1, 3))
    cloud_ok = np.isin(cloud, (1, 2, 3, 4))
    alg_ok = np.isin(alg, (0, 4))
    low = np.isin(alg, (1, 2))
    night = alg == 5
    out[~(on_surface & cloud_ok & alg_ok)] = Status.INVALID.value
    out[on_surface & cloud_ok & low] = Status.LOW_QUALITY.value

    dssf = np.asarray(dssf, dtype=float)
    lo, hi = DSSF_RANGE_WM2
    bad_range = np.isfinite(dssf) & ((dssf < lo) | (dssf > hi))
    if fraction is not None:
        fr = np.asarray(fraction, dtype=float)
        flo, fhi = FRACTION_RANGE
        # The diffuse fraction is undefined when DSSF = 0; only test it where DSSF > 0.
        bad_range |= np.isfinite(fr) & (dssf > 0) & ((fr < flo) | (fr > fhi))
    out[bad_range & (out != Status.INVALID.value)] = Status.OUT_OF_RANGE.value
    out[~np.isfinite(dssf) | ~np.isfinite(flag)] = Status.MISSING.value
    # Night (algorithm 101, SZA limit 90 deg since v1.0.12): irradiance is physically zero, even
    # where the cloud mask is unprocessed (e.g. flag 161) or the value is not stored.
    out[np.isfinite(flag) & on_surface & night] = Status.NIGHT.value
    return out


def usable(status: np.ndarray, allow_low_quality: bool) -> np.ndarray:
    """Pixels whose irradiance may drive the PV model."""
    ok = {Status.GOOD.value, Status.NIGHT.value}
    if allow_low_quality:
        ok.add(Status.LOW_QUALITY.value)
    return np.isin(np.asarray(status, dtype=object), list(ok))


def apply(
    dssf: np.ndarray, fraction: np.ndarray, status: np.ndarray, allow_low_quality: bool
) -> tuple[np.ndarray, np.ndarray]:
    """Masked (GHI, diffuse fraction): NaN where unusable; night forced to exactly 0."""
    ok = usable(status, allow_low_quality)
    ghi = np.where(ok, np.asarray(dssf, dtype=float), np.nan)
    fd = np.where(ok, np.asarray(fraction, dtype=float), np.nan)
    night = np.asarray(status, dtype=object) == Status.NIGHT.value
    ghi = np.where(night, 0.0, ghi)
    fd = np.where(night, np.nan, fd)
    return ghi, fd

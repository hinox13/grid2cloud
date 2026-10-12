"""E0-D UKPN feasibility audit: parsing and table summaries.

Encodings below were verified on the authenticated exports of 2 October 2026 (see
reports/e0_data_audit.md, "Real encodings"):

    redacted            strings 'True' / 'False', no nulls
    operating_voltage   strings '132', '33', '11', '66', '22', '6.6'  (LTDS T1)
    nominal_voltage     int 132 / 33                                  (monthly operational)
    spatial_coordinates 21-byte little-endian WKB POINT (x=lon, y=lat) in Parquet exports
    licence area        'Eastern Power Networks (EPN)' (LTDS, sites, ECR) or 'EPN' (monthly)
    ECR placeholders    '-', 'Data not available' (and 'Direct' for bulk_supply_point)

Parsers never drop values silently: anything they cannot interpret returns None and is counted
by the callers (`*_unparsed` counters in reports/experiments/e0_ukpn_audit/summary.json).
"""

from __future__ import annotations

import re
import struct

import pandas as pd

# Values UKPN uses in place of nulls. Compared after upper-casing and collapsing to alnum.
PLACEHOLDERS = frozenset({"", "DATA NOT AVAILABLE", "DATA", "N A", "NA", "NONE", "NULL", "UNKNOWN"})


def _is_null(value: object) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NA


def normalise_name(value: object) -> str | None:
    """Upper-case, alphanumeric-only key for exact matching. No suffix stripping, no fuzzing.

    UKPN placeholder strings ('-', 'Data not available', …) become None.
    """
    if _is_null(value):
        return None
    key = re.sub(r"[^A-Z0-9]+", " ", str(value).upper()).strip()
    return None if key in PLACEHOLDERS else key


def is_placeholder(value: object) -> bool:
    """True for a non-null value that is a UKPN placeholder rather than data."""
    return not _is_null(value) and normalise_name(value) is None


def parse_voltage_kv(value: object) -> float | None:
    """'132', '132kV', 132, '6.6' → float kV. Unparseable → None."""
    if _is_null(value):
        return None
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    return float(match.group()) if match else None


_TRUE = {"true", "yes", "y", "1", "redacted"}
_FALSE = {"false", "no", "n", "0", "public", "not redacted"}


def parse_flag(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if _is_null(value):
        return None
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return None


_AREA = re.compile(r"\b(EPN|LPN|SPN)\b")


def licence_area_code(value: object) -> str | None:
    """'Eastern Power Networks (EPN)' / 'EPN' → 'EPN'."""
    if _is_null(value):
        return None
    match = _AREA.search(str(value).upper())
    return match.group(1) if match else None


def node_key(area: object, node: object) -> str | None:
    """Licence-area-scoped LTDS node ID.

    LTDS node codes are NOT globally unique: e.g. BROG31 is Broad Oak Grid (SPN), Brogborough
    Primary (EPN) and Bromley Grid (LPN). Unscoped codes wire unrelated networks together.
    """
    code = licence_area_code(area)
    if code is None or _is_null(node) or not str(node).strip():
        return None
    return f"{code}:{str(node).strip()}"


def floc_from_code(area: object, code: object) -> str | None:
    """Monthly-index site code '0C6047' + area 'EPN' → site FLOC 'EPN-S0000000C6047'."""
    area_code = licence_area_code(area)
    if area_code is None or _is_null(code):
        return None
    return f"{area_code}-S{str(code).strip().zfill(12)}"


_SITE_CODE = re.compile(r"\((\w+)\)\s*$")


def site_code_from_label(value: object) -> str | None:
    """'Walpole GIS 132kV (0C6047)' → '0C6047'; label without a code → None."""
    if _is_null(value):
        return None
    match = _SITE_CODE.search(str(value))
    return match.group(1) if match else None


def parse_point(value: object) -> tuple[float | None, float | None]:
    """Geo point → (lat, lon). Accepts WKB bytes, dict, 'lat, lon' string or [lat, lon].

    Opendatasoft Parquet exports encode geo points as 2-D WKB POINTs (x = lon, y = lat).
    Points outside a generous GB bounding box are treated as invalid.
    """
    if _is_null(value):
        return None, None
    if isinstance(value, bytes | bytearray | memoryview):
        return _parse_wkb_point(bytes(value))
    if isinstance(value, dict):
        return _valid_latlon(value.get("lat"), value.get("lon"))
    if isinstance(value, list | tuple) and len(value) == 2:
        return _valid_latlon(value[0], value[1])
    parts = re.split(r"[,\s]+", str(value).strip())
    if len(parts) == 2:
        return _valid_latlon(parts[0], parts[1])
    return None, None


def _parse_wkb_point(blob: bytes) -> tuple[float | None, float | None]:
    if len(blob) != 21 or blob[0] not in (0, 1):
        return None, None
    order = "<" if blob[0] == 1 else ">"
    (geom_type,) = struct.unpack(order + "I", blob[1:5])
    if geom_type != 1:  # 2-D POINT only
        return None, None
    lon, lat = struct.unpack(order + "dd", blob[5:21])
    return _valid_latlon(lat, lon)


def _valid_latlon(lat: object, lon: object) -> tuple[float | None, float | None]:
    try:
        lat_f, lon_f = float(lat), float(lon)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None, None
    if 49.0 <= lat_f <= 61.5 and -9.0 <= lon_f <= 2.5:
        return lat_f, lon_f
    return None, None


def add_lat_lon(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Copy of `df` with `lat`/`lon` parsed from a geo-point column."""
    out = df.copy()
    points = out[column].map(parse_point) if column in out else pd.Series(index=out.index)
    out["lat"] = [p[0] if isinstance(p, tuple) else None for p in points]
    out["lon"] = [p[1] if isinstance(p, tuple) else None for p in points]
    return out


# ---------------------------------------------------------------------- table summaries


def missingness(df: pd.DataFrame) -> pd.DataFrame:
    """Per column: nulls, blank strings and UKPN placeholder strings, counted separately."""
    rows = []
    for column in df.columns:
        series = df[column]
        nulls = int(series.isna().sum())
        values = series.dropna()
        if len(values) and isinstance(values.iloc[0], bytes | bytearray):
            blanks = int(values.map(len).eq(0).sum())
            placeholders = 0
        else:
            text = [str(v) for v in values]
            blanks = sum(not v.strip() for v in text)
            placeholders = sum(bool(v.strip()) and is_placeholder(v) for v in text)
        missing = nulls + blanks + placeholders
        rows.append(
            {
                "column": column,
                "n_null": nulls,
                "n_blank": blanks,
                "n_placeholder": placeholders,
                "n_missing": missing,
                "frac_missing": missing / len(df) if len(df) else 0.0,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------- operational index


def circuit_publication_status(monthly: pd.DataFrame, min_public_fraction: float) -> pd.DataFrame:
    """Per (licence area, LTDS line name) from the monthly operational index.

    A (line, month) counts as public only if every row for it is `redacted == False`; months
    with duplicate rows are counted (`n_dup_month_rows`). Rows with a null line name or an
    unparseable redaction flag are not dropped silently — see `publication_counters`.
    """
    df = pd.DataFrame(
        {
            "area": monthly["licence_area"].map(licence_area_code),
            "line_name": monthly["ltds_line_name"],
            "month": pd.to_datetime(monthly["timestamp"], utc=True).dt.strftime("%Y-%m"),
            "redacted": monthly["redacted"].map(parse_flag),
            "voltage_kv": monthly["nominal_voltage"].map(parse_voltage_kv),
            "from_node_key": [
                node_key(a, n)
                for a, n in zip(monthly["licence_area"], monthly["from_ltds_node"], strict=True)
            ],
            "to_node_key": [
                node_key(a, n)
                for a, n in zip(monthly["licence_area"], monthly["to_ltds_node"], strict=True)
            ],
            "site_label": monthly["grid_supply_point"],
        }
    ).dropna(subset=["line_name", "area"])
    per_month = df.groupby(["area", "line_name", "month"]).agg(
        n_rows=("redacted", "size"),
        public=("redacted", lambda s: bool(s.notna().all() and (~s.astype(bool)).all())),
    )
    per_line_month = per_month.groupby(["area", "line_name"]).agg(
        n_months=("public", "size"),
        n_public_months=("public", "sum"),
        n_dup_month_rows=("n_rows", lambda s: int((s - 1).sum())),
    )
    first = df.groupby(["area", "line_name"]).agg(
        voltage_kv=("voltage_kv", "first"),
        first_month=("month", "min"),
        last_month=("month", "max"),
        n_unparsed_flag=("redacted", lambda s: int(s.isna().sum())),
        from_node_key=("from_node_key", "first"),
        to_node_key=("to_node_key", "first"),
        site_label=("site_label", "first"),
    )
    pairs = (
        df.assign(pair=[frozenset(p) for p in zip(df.from_node_key, df.to_node_key, strict=True)])
        .groupby(["area", "line_name"])["pair"]
        .nunique()
    )
    status = per_line_month.join(first)
    status["n_node_pairs"] = pairs
    status["public_fraction"] = status["n_public_months"] / status["n_months"]
    status["usable_monthly"] = status["public_fraction"] >= min_public_fraction
    return status.reset_index()


def publication_counters(monthly: pd.DataFrame) -> dict[str, int]:
    flags = monthly["redacted"].map(parse_flag)
    return {
        "rows": len(monthly),
        "rows_null_line_name": int(monthly["ltds_line_name"].isna().sum()),
        "rows_unparsed_redacted": int(flags.isna().sum()),
        "rows_redacted_true": int((flags == True).sum()),  # noqa: E712
        "rows_unparsed_voltage": int(monthly["nominal_voltage"].map(parse_voltage_kv).isna().sum()),
        "rows_unknown_area": int(monthly["licence_area"].map(licence_area_code).isna().sum()),
    }


# ---------------------------------------------------------------------------- solar


def is_solar(ecr: pd.DataFrame) -> pd.Series:
    """Primary resource is solar PV: `primary_resource_type_group == 'Solar PV'` or
    `energy_source_1 == 'Solar'` (identical on the 2 Oct 2026 data)."""
    group = ecr.get("primary_resource_type_group", pd.Series(index=ecr.index, dtype=object))
    source = ecr.get("energy_source_1", pd.Series(index=ecr.index, dtype=object))
    return group.astype(str).str.strip().eq("Solar PV") | source.astype(str).str.strip().eq("Solar")


def ecr_assets(ecr: pd.DataFrame) -> pd.DataFrame:
    """All ECR rows (any technology) with normalised identifiers and connected capacity.

    Capacity: `already_connected_registered_capacity_mw` for connected assets (the ECR column
    for built capacity); assets still "Accepted to Connect" are kept but get no capacity.
    """
    out = ecr.copy()
    out["is_solar"] = is_solar(ecr)
    out["connected"] = out["connection_status"].astype(str).str.strip().eq("Connected")
    out["capacity_mw"] = pd.to_numeric(
        out.get("already_connected_registered_capacity_mw"), errors="coerce"
    ).where(out["connected"])
    out["area"] = out["licence_area"].map(licence_area_code)
    for column, key in [
        ("grid_supply_point", "gsp_key"),
        ("bulk_supply_point", "bsp_key"),
        ("primary", "primary_key"),
    ]:
        out[key] = out[column].map(normalise_name) if column in out else None
    out["floc"] = out["sitefunctionallocation"].where(
        out["sitefunctionallocation"].map(normalise_name).notna()
    )
    return out


def solar_assets(ecr: pd.DataFrame) -> pd.DataFrame:
    """ECR rows whose *primary* resource is solar PV, with normalised identifiers.

    Assets with solar only as a secondary technology are not included and are counted by
    `solar_counters`. See `ecr_assets` for capacity semantics.
    """
    return ecr_assets(ecr).loc[lambda d: d["is_solar"]].drop(columns=["is_solar"])


def solar_counters(ecr: pd.DataFrame, solar: pd.DataFrame) -> dict[str, float]:
    tech_cols = [
        c for c in ("energy_conversion_technology_2", "energy_conversion_technology_3") if c in ecr
    ]
    secondary = (
        ecr.loc[~ecr.index.isin(solar.index), tech_cols]
        .astype(str)
        .apply(lambda s: s.str.contains("photovolt|solar", case=False))
        .any(axis=1)
        .sum()
        if tech_cols
        else 0
    )
    connected = solar[solar["connected"]]
    return {
        "solar_assets": len(solar),
        "solar_connected": int(solar["connected"].sum()),
        "solar_accepted_not_connected": int((~solar["connected"]).sum()),
        "solar_connected_mw": float(connected["capacity_mw"].sum()),
        "solar_connected_missing_capacity": int(connected["capacity_mw"].isna().sum()),
        "solar_only_as_secondary_technology_excluded": int(secondary),
    }

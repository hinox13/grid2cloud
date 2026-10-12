import datetime as dt

import numpy as np
import pandas as pd
import pytest

from cloud2grid.satellite import credentials, eumetsat, lsasaf, quality
from cloud2grid.satellite import geometry as geo

from .fixtures import CLEAR_OK, CLOUD_OK, FAIL, NIGHT, product, write_packed

LSA_CFG = {
    "access": {
        "https_base": "https://datalsasaf.lsasvcs.ipma.pt/PRODUCTS/MSG/MDSSFTD",
        "opendap_base": "https://thredds.lsasvcs.ipma.pt/thredds/dodsC/MSG/MDSSFTD",
        "netcdf_dir": "NETCDF",
        "filename": "NETCDF4_LSASAF_MSG_MDSSFTD_MSG-Disk_{slot}.nc",
    },
    "product": {"step_minutes": 15},
}
EXPECTED = {
    "variables": {
        "total": "DSSF_TOT",
        "diffuse_fraction": "FRACTION_DIFFUSE",
        "quality": "quality_flag",
    },
    "grid": {"lat_step": -0.05, "lon_step": 0.05},
}


# ----------------------------------------------------------------------------- credentials


def test_missing_credentials_stop_at_boundary_naming_variables_only():
    with pytest.raises(credentials.AuthenticationBoundary) as e:
        credentials.load(
            "LSA SAF", "LSASAF_USERNAME", "LSASAF_PASSWORD", env={"LSASAF_USERNAME": "u"}
        )
    assert e.value.missing == ["LSASAF_PASSWORD"]
    assert "LSASAF_PASSWORD" in str(e.value)


def test_credentials_never_appear_in_repr_or_status():
    env = {"U": "alice-user", "P": "s3cr3t-pass-value"}
    c = credentials.load("svc", "U", "P", env=env)
    for text in (repr(c), str(c), str(credentials.status(["U", "P"], env))):
        assert "alice-user" not in text and "s3cr3t-pass-value" not in text
    assert credentials.status(["U", "P", "X"], env) == {"U": True, "P": True, "X": False}
    assert (
        c.redact("https://alice-user:s3cr3t-pass-value@host/x")
        == "https://<redacted>:<redacted>@host/x"
    )


# ------------------------------------------------------------------------------ timestamps


def test_slot_parsing_and_urls():
    p = lsasaf.Product.from_config(LSA_CFG)
    slot = lsasaf.parse_slot("NETCDF4_LSASAF_MSG_MDSSFTD_MSG-Disk_202406151215.nc")
    assert slot == dt.datetime(2024, 6, 15, 12, 15, tzinfo=dt.UTC)
    assert p.https_url(slot).endswith(
        "NETCDF/2024/06/15/NETCDF4_LSASAF_MSG_MDSSFTD_MSG-Disk_202406151215.nc"
    )
    assert p.opendap_url(slot).startswith(
        "https://thredds.lsasvcs.ipma.pt/thredds/dodsC/MSG/MDSSFTD/NETCDF/2024/06/15/"
    )
    assert "@" not in p.https_url(slot)
    with pytest.raises(ValueError):
        lsasaf.parse_slot("no_timestamp.nc")
    s = lsasaf.slots(
        dt.datetime(2024, 6, 15, 12, tzinfo=dt.UTC), dt.datetime(2024, 6, 15, 13, tzinfo=dt.UTC), 15
    )
    assert len(s) == 5 and all(t.minute % 15 == 0 for t in s)


def test_listing_parser_on_real_index_format():
    html = (
        '<tr><td class="fb-n"><a href="/PRODUCTS/MSG/MDSSFTD/NETCDF/2024/06/15/'
        'NETCDF4_LSASAF_MSG_MDSSFTD_MSG-Disk_202406151200.nc">NETCDF4_LSASAF_MSG_MDSSFTD_MSG-Disk_202406151200.nc</a>'
        '</td><td class="fb-d">2024-06-15 13:19</td><td class="fb-s">5446 KB</td></tr>'
        '<tr><td class="fb-n"><a href="/PRODUCTS/MSG/MDSSFTD/NETCDF/2024/06/15/'
        'NETCDF4_LSASAF_MSG_MDSSFTD_MSG-Disk_202406151145.nc">x</a>'
        '</td><td class="fb-d">2024-06-15 12:19</td><td class="fb-s">5394 KB</td></tr>'
    )
    df = lsasaf.parse_listing(html)
    assert list(df["slot"].dt.strftime("%H%M")) == ["1145", "1200"]
    assert df["size_bytes"].iloc[1] == 5446 * 1024


def test_rgb_served_time_from_header_and_matching():
    t = eumetsat.served_time(
        {"Warning": "99 Nearest value used: time=2024-06-15T12:00:00.000Z ISO8601 (layer)"}
    )
    assert t == dt.datetime(2024, 6, 15, 12, tzinfo=dt.UTC)
    with pytest.raises(eumetsat.FrameTimeUnknown):
        eumetsat.served_time({})
    ok = eumetsat.match(t, t, t, 11.65, 7.5)
    assert (
        ok["accepted"]
        and ok["time_delta_min"] == 0
        and ok["radiation_time"] == "2024-06-15T12:11:39Z"
    )
    bad = eumetsat.match(t, t, t + dt.timedelta(minutes=15), 11.65, 7.5)
    assert not bad["accepted"]


def test_wms_bbox_axis_order_epsg4326():
    layer = eumetsat.WMSLayer(
        "https://x", "msg_fes:rgb_eview", "EO:EUM:DAT:MSG:EVIEW", "eumetsat_eview"
    )
    p = eumetsat.getmap_params(
        layer,
        {"lat_min": 50.5, "lat_max": 53.5, "lon_min": -3.5, "lon_max": 2.0},
        dt.datetime(2024, 6, 15, 12, tzinfo=dt.UTC),
        1100,
        "image/png",
    )
    assert (
        p["bbox"] == "50.5,-3.5,53.5,2.0"
        and p["height"] == "600"
        and p["time"] == "2024-06-15T12:00:00Z"
    )


# -------------------------------------------------------------------------------- geometry


def test_native_projection_matches_official_lsasaf_lat_lon():
    # Official LSA SAF MSG-disk lat/lon file (0.01° precision): pixel (ncol 1844, nlin 306)
    # has centre 51.95 N, -0.61 E; (1881, 318) → 51.27, 1.10; (1904, 380) → 48.00, 2.00.
    for ncol, nlin, lat, lon in [
        (1844, 306, 51.95, -0.61),
        (1881, 318, 51.27, 1.10),
        (1904, 380, 48.00, 2.00),
    ]:
        glat, glon = geo.native_to_geo(np.array([ncol]), np.array([nlin]))
        assert abs(glat[0] - lat) <= 0.006 and abs(glon[0] - lon) <= 0.006
        c, l_ = geo.native_pixel(np.array([lat]), np.array([lon]))
        assert (c[0], l_[0]) == (ncol, nlin)


def test_native_footprint_and_acquisition_offset_near_sundon():
    fp = geo.native_footprint_km(51.93, -0.6)
    assert 3.0 < fp["dx_km"] < 3.4 and 6.0 < fp["dy_km"] < 6.6
    assert abs(float(geo.acquisition_offset_min(np.array([306]))[0]) - 11.6467) < 1e-3
    # south of the disk is scanned first
    assert geo.acquisition_offset_min(np.array([3700]))[0] < 1.0


def test_regular_grid_mapping_descending_latitude():
    g = geo.RegularGrid()  # MDSSFTD NetCDF: lat 80 → -80, lon -80 → 80, 0.05°
    r, c = g.index(np.array([51.9333]), np.array([-0.6190]))
    assert (int(r[0]), int(c[0])) == (561, 1588)
    lat, lon = g.centre(r, c)
    assert abs(lat[0] - 51.95) < 1e-9 and abs(lon[0] - (-0.60)) < 1e-9
    with pytest.raises(ValueError):
        g.index(np.array([85.0]), np.array([0.0]))
    dx, dy = g.cell_km(52.0)
    assert 3.3 < dx < 3.5 and 5.5 < dy < 5.6


def test_asset_to_pixel_mapping_and_sharing():
    assets = pd.DataFrame(
        {
            "asset_id": ["a", "b", "c"],
            "capacity_mw": [6.0, 2.0, 15.0],
            "lat": [51.9248, 51.9513, 51.9188],
            "lon": [-0.6113, -0.6214, -0.5639],
        }
    )
    m = geo.map_assets(assets, geo.RegularGrid())
    assert m["native_pixel_id"].iloc[0] == m["native_pixel_id"].iloc[1]  # 6 & 2 MW share a pixel
    assert m["native_pixel_id"].iloc[2] != m["native_pixel_id"].iloc[0]
    assert (m["dist_to_pixel_center_km"] < 3.3).all()
    s = geo.pixel_summary(m, "native_pixel_id")
    assert s["distinct_pixels"] == 2 and s["shared_pixels"]
    sep = geo.pixel_separations(m, "native_nlin", "native_ncol")
    assert set(sep["chebyshev"]) <= {0, 1}


# --------------------------------------------------------------------------------- quality


def test_quality_flag_decoding_matches_pum_table4():
    d = {k: int(v) for k, v in quality.decode(CLEAR_OK).items()}
    assert d == {"surface": 1, "cloud": 1, "algorithm": 4}
    assert quality.describe(CLOUD_OK) == "land|cloud_filled|cloudy_ok"
    assert quality.describe(9) == "land|contaminated|cloudy_ok"
    assert quality.describe(161) == "land|unprocessed|clear_night"
    assert quality.describe(37) == "land|clear|clear_low_quality"


def test_quality_classification_and_masking():
    flag = np.array([CLEAR_OK, CLOUD_OK, NIGHT, 161, 37, FAIL, 0, CLEAR_OK, CLEAR_OK])
    dssf = np.array([800, 200, 0, np.nan, 500, 300, 0, np.nan, 1600])
    frac = np.array([0.2, 0.9, np.nan, np.nan, 0.3, 0.5, 0.0, 0.2, 0.1])
    st = quality.classify(flag, dssf, frac)
    assert list(st) == [
        "GOOD",
        "GOOD",
        "NIGHT",
        "NIGHT",
        "LOW_QUALITY",
        "INVALID",
        "INVALID",
        "MISSING",
        "OUT_OF_RANGE",
    ]
    ghi, fd = quality.apply(dssf, frac, st, allow_low_quality=False)
    assert ghi[0] == 800 and ghi[2] == 0 and ghi[3] == 0  # night forced to zero
    assert np.isnan(ghi[4]) and np.isnan(ghi[5]) and np.isnan(ghi[7]) and np.isnan(ghi[8])
    ghi2, _ = quality.apply(dssf, frac, st, allow_low_quality=True)
    assert ghi2[4] == 500


# ------------------------------------------------------------------------ product opening


def test_open_inspect_crop_product_shaped_file(tmp_path):
    ds = product(["2024-06-15T12:00Z"])
    ds["DSSF_TOT"][0, 0, 0] = np.nan  # becomes the fill value on disk
    path = write_packed(ds, tmp_path / "NETCDF4_LSASAF_MSG_MDSSFTD_MSG-Disk_202406151200.nc")
    raw = lsasaf.open_raw(path)
    dec = lsasaf.open_product(path)
    assert raw["DSSF_TOT"].dtype == np.int16 and int(raw["DSSF_TOT"][0, 0, 0]) == -1
    assert (
        np.isnan(float(dec["DSSF_TOT"][0, 0, 0]))
        and abs(float(dec["DSSF_TOT"][0, 1, 1]) - 800.0) < 0.05
    )
    info = lsasaf.inspect(raw, dec)
    assert info["variables"]["DSSF_TOT"]["attrs"]["scale_factor"] == pytest.approx(0.1)
    assert all(c["ok"] for c in lsasaf.check_expectations(info, EXPECTED))
    crop = lsasaf.crop(dec, {"lat_min": 51.8, "lat_max": 52.0, "lon_min": -0.7, "lon_max": -0.5})
    assert (
        float(crop.lat.max()) <= 52.0 + 1e-6
        and float(crop.lat.min()) >= 51.8 - 1e-6
        and crop.sizes["lon"] == 5
    )
    with pytest.raises(ValueError):
        lsasaf.crop(dec, {"lat_min": 10, "lat_max": 11, "lon_min": 10, "lon_max": 11})


def test_units_check_spellings():
    for u in ("W/m2", "W m-2", "W.m-2", "w/m^2", "W/m**2"):
        assert lsasaf.is_wm2(u), u
    assert not lsasaf.is_wm2("kW/m2")

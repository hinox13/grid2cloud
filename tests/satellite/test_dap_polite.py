import datetime as dt

import numpy as np
import pytest

from cloud2grid.satellite import credentials, lsasaf

# Shape of a real LSA SAF THREDDS DAP2 ASCII response (trimmed to 2 × 3 cells).
DAP = """Dataset {
    Grid { ARRAY: Int16 DSSF_TOT[time = 1][lat = 2][lon = 3]; } DSSF_TOT;
} MSG/MDSSFTD/NETCDF/2024/06/15/NETCDF4_LSASAF_MSG_MDSSFTD_MSG-Disk_202406151200.nc;
---------------------------------------------
DSSF_TOT.DSSF_TOT[1][2][3]
[0][0], 8732, -1, 9310
[0][1], 9357, 9352, 0

DSSF_TOT.time[1]
0

FRACTION_DIFFUSE.FRACTION_DIFFUSE[1][2][3]
[0][0], 35, -1, 30
[0][1], 100, 0, -1

quality_flag.quality_flag[1][2][3]
[0][0], 9, 0, 133
[0][1], 13, 255, 165

lat[2]
52.25, 52.199997

lon[3]
-1.0499954, -1.0, -0.94999695

time[1]
0
"""
PACK = {
    "DSSF_TOT": {"scale": 0.1, "fill": -1},
    "FRACTION_DIFFUSE": {"scale": 0.01, "fill": -1},
    "quality_flag": {"scale": 1.0, "fill": 255},
}
V = list(PACK)


def test_index_box_matches_product_grid():
    box = lsasaf.index_box(
        80.0,
        -0.05,
        -80.0,
        0.05,
        {"lat_min": 51.65, "lat_max": 52.25, "lon_min": -1.05, "lon_max": -0.15},
    )
    assert box == (555, 567, 1579, 1597)


def test_dap_ascii_parse_and_decode():
    raw = lsasaf.parse_dap_ascii(DAP, V)
    assert raw["DSSF_TOT"].shape == (2, 3) and list(raw["lat"]) == pytest.approx(
        [52.25, 52.2], abs=1e-4
    )
    ds = lsasaf.decode(raw, PACK, dt.datetime(2024, 6, 15, 12, tzinfo=dt.UTC))
    d = ds["DSSF_TOT"].values[0]
    assert d[0, 0] == pytest.approx(873.2) and np.isnan(d[0, 1]) and d[1, 2] == 0.0
    assert ds["FRACTION_DIFFUSE"].values[0, 1, 0] == pytest.approx(1.0)
    q = ds["quality_flag"].values[0]
    assert q[0, 2] == 133 and np.isnan(q[1, 1])  # 255 is the fill value
    assert str(ds["time"].values[0])[:16] == "2024-06-15T12:00"
    assert list(ds["lat"].values) == pytest.approx([52.25, 52.2])


def test_dap_url_is_single_request_without_credentials():
    p = lsasaf.Product(
        "https://a", "https://thredds/dodsC/MSG/MDSSFTD", "NETCDF", "F_{slot}.nc", 15
    )
    u = lsasaf.dap_ascii_url(p, dt.datetime(2024, 6, 15, 12, tzinfo=dt.UTC), (1, 2, 3, 4), V)
    assert u.count("?") == 1 and ".ascii?" in u and "@" not in u
    assert "DSSF_TOT[0:1:0][1:1:2][3:1:4]" in u and "quality_flag[0:1:0][1:1:2][3:1:4]" in u


def test_missing_variable_is_an_error():
    with pytest.raises(ValueError):
        lsasaf.parse_dap_ascii(DAP.replace("quality_flag.quality_flag", "x.x"), V)


class _Resp:
    def __init__(self, code):
        self.status_code, self.text = code, "x"


def test_polite_client_stops_on_auth_failure_and_spaces_requests(monkeypatch):
    cred = credentials.load("svc", "U", "P", env={"U": "user1", "P": "secret-pass"})
    c = lsasaf.PoliteClient(cred, pause_s=0.05)
    calls = []
    monkeypatch.setattr(c.session, "get", lambda url, timeout: calls.append(url) or _Resp(401))
    with pytest.raises(lsasaf.AuthRejected) as e:
        c.get_text("https://x")
    assert "secret-pass" not in str(e.value) and c.requests_made == 1
    monkeypatch.setattr(c.session, "get", lambda url, timeout: _Resp(503))
    with pytest.raises(lsasaf.Throttled):
        c.get_text("https://x")
    import time

    t0 = time.monotonic()
    monkeypatch.setattr(c.session, "get", lambda url, timeout: _Resp(200))
    c.get_text("https://x")
    c.get_text("https://x")
    assert time.monotonic() - t0 >= 0.05  # pause enforced between requests

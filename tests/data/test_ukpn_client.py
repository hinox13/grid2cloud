import io

import pandas as pd
import pytest

from cloud2grid.data.ukpn import DatasetMetadata, UKPNAccessError, UKPNClient


def _parquet_bytes(n_rows: int) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame({"a": list(range(n_rows))}, dtype="int64").to_parquet(buf)
    return buf.getvalue()


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200, payload=None) -> None:
        self.body, self.status_code, self.payload = body, status, payload
        self.reason = "Forbidden" if status == 403 else "OK"

    def json(self):
        if self.payload is None:
            raise ValueError("no JSON")
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def iter_content(self, chunk_size):
        yield self.body


def _client(monkeypatch, body: bytes, status: int = 200, payload=None) -> UKPNClient:
    client = UKPNClient("https://example.org/api", api_key="k")
    monkeypatch.setattr(client.session, "get", lambda *a, **k: _FakeResponse(body, status, payload))
    return client


def test_export_requires_api_key(tmp_path):
    with pytest.raises(UKPNAccessError, match="no API key"):
        UKPNClient("https://example.org/api").export_parquet("ds", tmp_path / "x.parquet")


def test_empty_export_of_nonempty_dataset_is_access_error(monkeypatch, tmp_path):
    client = _client(monkeypatch, _parquet_bytes(0))
    dest = tmp_path / "x.parquet"
    with pytest.raises(UKPNAccessError, match="0 rows"):
        client.export_parquet("ds", dest, expected_records=1504)
    assert not dest.exists()


def test_forbidden_is_access_error(monkeypatch, tmp_path):
    client = _client(monkeypatch, b"", status=403)
    with pytest.raises(UKPNAccessError, match="403"):
        client.export_parquet("ds", tmp_path / "x.parquet")


def test_successful_export(monkeypatch, tmp_path):
    client = _client(monkeypatch, _parquet_bytes(3))
    dest = tmp_path / "x.parquet"
    assert client.export_parquet("ds", dest, expected_records=3) == 3
    assert len(pd.read_parquet(dest)) == 3


def test_metadata_parsing():
    meta = DatasetMetadata.from_api(
        {
            "dataset_id": "grid-and-primary-sites",
            "data_visible": False,
            "fields": [{"name": "sitename"}],
            "metas": {"default": {"title": "T", "license": "CC BY 4.0", "records_count": 1504}},
        }
    )
    assert meta.licence == "CC BY 4.0" and meta.records_count == 1504
    assert meta.fields == ("sitename",) and meta.data_visible is False


def test_aggregate_export_writes_parquet(monkeypatch, tmp_path):
    rows = [{"ltds_line_name": "A_B_1", "n_rows": 10, "n_active_power": 0, "n_current": 10}]
    client = _client(monkeypatch, b"", payload=rows)
    dest = tmp_path / "agg.parquet"
    assert client.export_aggregate("ds", {"group_by": "ltds_line_name"}, dest) == 1
    assert pd.read_parquet(dest)["n_current"].tolist() == [10]


def test_server_error_message_is_surfaced(monkeypatch, tmp_path):
    payload = {"error_code": "AggregationNotSupported", "message": "parquet export ..."}
    client = _client(monkeypatch, b"", status=400, payload=payload)
    with pytest.raises(RuntimeError, match="AggregationNotSupported"):
        client.export_parquet("ds", tmp_path / "x.parquet")

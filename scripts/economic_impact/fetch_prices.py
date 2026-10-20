# ruff: noqa: E501
"""Fetch the two pre-registered Elexon Insights price series for 1 Apr – 30 Sep 2024 (no API key needed).

    .venv/bin/python scripts/economic_impact/fetch_prices.py
    → data/interim/economic_impact/{mid,system_prices}.parquet, reports/economic_impact/prices_retrieval.json

- Market Index Data: /balancing/pricing/market-index (APXMIDP and N2EXMIDP rows), 7-day windows.
- System prices: /balancing/settlement/system-prices/{settlementDate}, one call per settlement date.
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "data/interim/economic_impact"
OUT = ROOT / "reports/economic_impact"
API = "https://data.elexon.co.uk/bmrs/api/v1"


def get(url: str) -> list[dict]:
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "cloud2grid-research"}), timeout=60) as r:
                d = json.loads(r.read())
            return d.get("data", d)
        except Exception:  # noqa: BLE001  retry transient failures, then raise
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
    return []


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = datetime.now(UTC)
    mid = []
    for start in pd.date_range("2024-03-31", "2024-10-01", freq="7D", tz="UTC"):
        end = min(start + pd.Timedelta(days=7), pd.Timestamp("2024-10-01 23:59", tz="UTC"))
        mid += get(f"{API}/balancing/pricing/market-index?from={start:%Y-%m-%dT%H:%MZ}&to={end:%Y-%m-%dT%H:%MZ}&format=json")
        time.sleep(0.3)
    M = pd.DataFrame(mid).drop_duplicates(subset=["startTime", "dataProvider"])
    M["startTime"] = pd.to_datetime(M.startTime, utc=True)
    M.to_parquet(WORK / "mid.parquet", index=False)
    sp = []
    for d in pd.date_range("2024-03-31", "2024-10-01", freq="D"):
        sp += get(f"{API}/balancing/settlement/system-prices/{d:%Y-%m-%d}?format=json")
        time.sleep(0.2)
    S = pd.DataFrame(sp).drop_duplicates(subset=["startTime"])
    S["startTime"] = pd.to_datetime(S.startTime, utc=True)
    S.to_parquet(WORK / "system_prices.parquet", index=False)
    apx = M[M.dataProvider == "APXMIDP"]
    rec = {
        "retrieved_utc": t0.isoformat(), "api": API,
        "mid_rows": int(len(M)), "mid_providers": M.dataProvider.value_counts().to_dict(),
        "apx_periods": int(len(apx)), "apx_zero_volume_periods": int((apx.volume == 0).sum()),
        "apx_price_range": [float(apx.price.min()), float(apx.price.max())],
        "system_price_periods": int(len(S)), "ssp_equals_sbp_share": float((S.systemSellPrice == S.systemBuyPrice).mean()),
        "system_price_range": [float(S.systemSellPrice.min()), float(S.systemSellPrice.max())],
        "system_price_created_range": [str(S.createdDateTime.min()), str(S.createdDateTime.max())],
    }  # fmt: skip
    (OUT / "prices_retrieval.json").write_text(json.dumps(rec, indent=2))
    print(json.dumps(rec, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

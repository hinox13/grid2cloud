"""Discover candidate 2024 weather events from satellite irradiance + estimated PV only.

    uv run python scripts/discover_weather_events.py

Reads ONLY data/processed/satellite/sundon/{pv_by_asset,field_stats}.parquet (written by
scripts/build_pv_timeseries.py) and the pre-registered configs/experiments/e3_event_discovery.yaml.
Never reads GENCO, AC power-flow or network-loading outputs (README §18–19).

Deterministic: same date range + thresholds + asset set + satellite version ⇒ same events.
The run records a hash of the configuration, the asset set and the product algorithm version.

Outputs
    reports/tables/e3_candidate_events.csv
    reports/experiments/e3_satellite/event_discovery.json
"""

from __future__ import annotations

import datetime as dt
import json
import sys

import pandas as pd
import yaml

from cloud2grid.licensing.registry import REPO_ROOT
from cloud2grid.scenarios import events

CFG = yaml.safe_load((REPO_ROOT / "configs/experiments/e3_event_discovery.yaml").read_text())
PROC = REPO_ROOT / "data/processed/satellite/sundon"
OUT = REPO_ROOT / "reports/experiments/e3_satellite"
TABLES = REPO_ROOT / "reports/tables"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    status = {
        "run_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "config_hash": events.params_hash(CFG),
    }
    pv_path, field_path = PROC / "pv_by_asset.parquet", PROC / "field_stats.parquet"
    if not (pv_path.exists() and field_path.exists()):
        status.update(
            status="BLOCKED_NO_SATELLITE_DATA",
            message="No processed MDSSFTD series. LSA SAF credentials are required to acquire the "
            "pre-registered search period (scripts/build_pv_timeseries.py --acquire).",
        )
        (OUT / "event_discovery.json").write_text(json.dumps(status, indent=2))
        print(status["status"])
        return 0
    pv = pd.read_parquet(pv_path)
    field = pd.read_parquet(field_path)
    start, end = (
        pd.Timestamp(CFG["search_period"]["start"]),
        pd.Timestamp(CFG["search_period"]["end"]),
    )
    pv = pv[(pv["slot"] >= start) & (pv["slot"] <= end)]
    field = field[(field["slot"] >= start) & (field["slot"] <= end)]
    usable = pv["status"].isin(["GOOD", "NIGHT"])
    asset_ts = pv.assign(cf=pv["capacity_factor"], kc=pv["clearsky_index"], usable=usable)[
        ["slot", "asset_id", "cf", "active_capacity_mw", "kc", "usable"]
    ]
    thr = CFG["thresholds"]
    f = events.slot_features(asset_ts, field, CFG["step_minutes"], thr)
    wf = events.window_features(f, CFG["window_slots"], CFG["step_minutes"], thr)
    cl = events.classify(wf, CFG["classes"])
    sel = events.select(cl, CFG["selection"]["per_class"], CFG["selection"]["min_separation_h"])
    sel.to_csv(TABLES / "e3_candidate_events.csv", index=False)
    active = sorted(asset_ts.loc[asset_ts.active_capacity_mw > 0, "asset_id"].unique())
    status.update(
        status="OK",
        slots=int(len(f)),
        valid_slots=int(f["valid"].sum()),
        windows=int(len(wf)),
        class_counts={k: int(cl[k].sum()) for k in events.CLASSES} if len(cl) else {},
        selected=int(len(sel)),
        asset_set=active,
        asset_set_hash=events.params_hash(active),
    )
    (OUT / "event_discovery.json").write_text(json.dumps(status, indent=2, default=str))
    print(json.dumps(status, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

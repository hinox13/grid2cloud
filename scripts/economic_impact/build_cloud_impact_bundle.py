# ruff: noqa: E501
"""Build the small, frozen Cloud Impact bundle the Explorer reads (no runtime API calls, no secrets).

    .venv/bin/python scripts/economic_impact/build_cloud_impact_bundle.py
    → data/demo/cloud_impact/{periods_2024-06-15.parquet, season.json, provenance.json}

Inputs (all frozen, produced by the pre-registered economic-impact study, configs/economic_impact/prereg.yaml):
- data/interim/economic_impact/imports.parquet: AC / E5c / E5d imports of each S1 state and its
  CF_noPV / CF_clear counterfactuals (explicit 6 MW plant ECR:955 only);
- data/interim/economic_impact/{mid,system_prices}.parquet: Elexon BMRS prices (BMRS data licence);
- reports/economic_impact/results.json: the published aggregates;
- the frozen Explorer event bundle (fleet PV, 15-min) and the E3 per-asset PV (plant PV per slot).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

from cloud2grid.licensing import gate
from cloud2grid.licensing.registry import Registry

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "data/interim/economic_impact"
OUT = ROOT / "data/demo/cloud_impact"
DAY = "2024-06-15"
ATTRIBUTION = "Contains BMRS data © Elexon Limited copyright and database right 2024"
# every source whose derived values the bundle carries; the build stops if the licence gate refuses one
GATED = ["elexon_bmrs_market_index", "elexon_bmrs_system_prices", "ukpn_33kv_operational_half_hourly_epn",
         "ukpn_ecr_1mw_and_above", "ukpn_ecr_under_1mw", "lsa_saf_mdssftd", "eumetsat_eview"]  # fmt: skip


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def periods() -> pd.DataFrame:
    imp = pd.read_parquet(WORK / "imports.parquet")
    imp = imp[imp.slot.dt.strftime("%Y-%m-%d") == DAY]
    w = imp.pivot(index="scenario_id", columns="action", values=["import_AC", "import_E5c", "import_E5d"])
    base = imp[imp.action == "base"].set_index("scenario_id")
    P = pd.DataFrame({"slot_utc": base.slot, "plant_pv_mw": base.pv_mw, "plant_pv_clear_mw": base.pv_clear_mw})
    for m in ("AC", "E5c", "E5d"):
        for a, tag in (("base", "observed"), ("clear", "clear_sky"), ("noPV", "no_plant")):
            P[f"import_{m}_{tag}_mw"] = w[(f"import_{m}", a)]
    mid = pd.read_parquet(WORK / "mid.parquet")
    apx = mid[mid.dataProvider == "APXMIDP"].set_index("startTime")
    sp = pd.read_parquet(WORK / "system_prices.parquet").set_index("startTime")
    P["settlement_date"] = P.slot_utc.map(apx.settlementDate)
    P["settlement_period"] = P.slot_utc.map(apx.settlementPeriod).astype("Int64")
    P["apx_gbp_per_mwh"] = P.slot_utc.map(apx.price)
    P["apx_volume_mwh"] = P.slot_utc.map(apx.volume)
    P["system_price_gbp_per_mwh"] = P.slot_utc.map(sp.systemSellPrice)
    fleet = pd.read_parquet(ROOT / "data/demo/events/jun15_cloud_clearing/fleet_pv.parquet").set_index("timestamp_utc").fleet_pv_mw
    P["fleet_pv_mw"] = P.slot_utc.map(fleet)  # only inside the Explorer event window (08:45–12:15)
    return P.sort_values("slot_utc").reset_index(drop=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    P = periods()
    P.to_parquet(OUT / f"periods_{DAY}.parquet", index=False)
    R = json.loads((ROOT / "reports/economic_impact/results.json").read_text())
    season = {
        "periods_valued": R["periods_valued"],
        "pv_attributed": R["season"]["pv_attributed"],
        "cloud_attributed": R["season"]["cloud_attributed"],
        "absolute_mode_diagnostic": R["absolute_mode_diagnostic"],
        "event_2024-06-15": R["events"][DAY],
        "daily_context": R["daily_context"],
    }
    (OUT / "season.json").write_text(json.dumps(season, indent=2, default=float))
    reg = Registry.load()
    decisions = [gate.require(s, "redistribute_derived", reg) for s in GATED]  # raises if refused
    assert reg.sources["elexon_bmrs_market_index"].attribution.replace("[year]", "2024").rstrip(".") == ATTRIBUTION
    prov = {
        "title": "Cloud Impact bundle: 15 June 2024 and season aggregates (illustrative historical valuation)",
        "built_from": "the frozen study outputs listed under input_sha256 (no runtime data access)",
        "methodology": "configs/economic_impact/prereg.yaml (pre-registered before any valuation; see its publication note); reports/economic_impact/methodology.md",
        "definitions": {
            "plant": "the explicit 6 MW 33 kV PV plant ECR:955 (Leighton Buzzard), the only PV changed in the counterfactuals",
            "fleet_pv": "all 2024 PV assets of the study area (8.945 MW), satellite-derived; shown for context only",
            "clear_sky": "the plant at its clear-sky estimate (same pvlib chain, Ineichen); everything else unchanged",
            "no_plant": "the plant's output set to 0; everything else unchanged",
            "energy": "MW difference x 0.5 h per settlement period; each AC state stands for its period",
            "value": "energy x the APX Market Index price of the same period (GBP); illustrative, not a realised saving, cost, bill or revenue",
        },
        "sources": [
            {"name": "Elexon Insights Market Index Data (APXMIDP)", "endpoint": "https://data.elexon.co.uk/bmrs/api/v1/balancing/pricing/market-index",
             "licence": "BMRS data licence", "licence_url": "https://www.elexon.co.uk/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/", "attribution": ATTRIBUTION},
            {"name": "Elexon Insights system prices (imbalance; separate scenario)", "endpoint": "https://data.elexon.co.uk/bmrs/api/v1/balancing/settlement/system-prices/{date}",
             "licence": "BMRS data licence", "attribution": ATTRIBUTION},
            {"name": "Cloud2Grid AC-reconstructed states, PV estimates and frozen E5c/E5d predictions", "licence": "derived from UK Power Networks (CC BY 4.0) and EUMETSAT LSA SAF (CC BY 4.0) data"},
        ],
        "gate_decisions": [{"source_id": d.source_id, "use": d.use, "allowed": d.allowed, "licence": d.detail} for d in decisions],
        "retrieval": json.loads((ROOT / "reports/economic_impact/prices_retrieval.json").read_text())["retrieved_utc"],
        "input_sha256": {p: sha(ROOT / p) for p in ("data/interim/economic_impact/imports.parquet", "data/interim/economic_impact/mid.parquet",
                                                     "data/interim/economic_impact/system_prices.parquet", "reports/economic_impact/results.json")},
        "files_sha256": {p.name: sha(p) for p in (OUT / f"periods_{DAY}.parquet", OUT / "season.json")},
    }  # fmt: skip
    (OUT / "provenance.json").write_text(json.dumps(prov, indent=2))
    print(f"{len(P)} periods {P.slot_utc.min():%H:%M}–{P.slot_utc.max():%H:%M} UTC → {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

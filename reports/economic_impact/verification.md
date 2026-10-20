# Economic numbers: verification and provenance

## Commands

```bash
.venv/bin/python scripts/economic_impact/build_cloud_impact_bundle.py   # rebuild data/demo/cloud_impact (needs the local study outputs)
.venv/bin/python scripts/economic_impact/verify_economic.py             # public clone: 26/26 (bundle + released tables); development: 42/42
.venv/bin/python -m pytest -q tests/economic                            # public clone: 35 passed, 1 skipped; development: 51 passed
```

## What a public clone can and cannot reproduce

The verifier uses its own implementation, not `analyze.py`. Its output labels every check with the data it needs.

| Check class | Needs | In a public clone | What it establishes | What it does **not** establish |
|---|---|---|---|---|
| `[bundle]` | `data/demo/cloud_impact/` (released) | **runs** | the page's 15 June numbers are internally consistent: day totals = the sum of the 24 periods; settlement numbering; no missing price; 11:00 vs day; fleet PV | that the per-period imports are right |
| `[released tables]` | `reports/economic_impact/tables/periods.csv`, `results.json` (released) | **runs** | the 16 season totals, the displayed error percentages and the bundle's season totals all follow from the published per-half-hour values and prices; the APX gap is exactly the documented one; negative prices kept | that the per-half-hour import changes are right: they are taken from the table, not recomputed |
| `[local study data]` | `data/interim/economic_impact/` (AC counterfactual imports, raw Elexon responses) | **skipped** | the same totals from the raw solver outputs and raw prices; the re-solved base reproduces the frozen S1 AC import (≤ 1.03 × 10⁻⁵ MW) | — |

**Not reproducible from public files alone:**
- **The AC counterfactual solves and the GENCO predictions** (`states.py`). They need the frozen S1 AC states (`data/interim/e4/…`, local research data) plus the published model release `cloud2grid-models-v1`. The code is published (`counterfactual.py`, `clearsky.py`), but the S1 states are not redistributed.
- **The raw prices.** These can be re-fetched without a key (`fetch_prices.py`); Elexon may revise the system prices in later settlement runs.

**Re-checked in the development repository (42/42):**
- **15 June totals:** 16.9414 MWh and £1,661.18 of cloud-attributed import, plus 31.2410 MWh and £2,890.20 displaced by the plant.
- **Sample:** 2,820 half-hours, no duplicates, every half-hour inside BST; 180 negative-price half-hours kept.
- **Season totals:** all 16 (AC, accounting, E5c, E5d × displaced and cloud-attributed × energy and value) match `results.json` to 1e-9 from the raw data, and to 1e-6 from the released table.
- **Displayed errors:** −98.4 %, −0.3 % and −1.5 % match the exact −98.436 %, −0.292 % and −1.537 %.
- **Documented price gap:** APX is missing only for **2024-04-13 07:00 UTC (SP 17)**, which is absent at the source (Elexon publishes no APXMIDP row for it). Its energy is counted and its value omitted, bounded at ≤ £4.14 (< 0.01 % of the season).

**Tests:** `tests/economic/test_cloud_impact.py` covers:
- UTC↔BST settlement numbering, including 23:00 UTC → SP 1 and the gap period;
- MW → MWh integration and negative prices;
- every check class above (the local-data class is skipped in a public clone);
- attribution present and no credential words in the bundle;
- the Elexon price sources pass the project licence gate for `redistribute_derived` (not `redistribute_raw`), and the bundle records the gate decision for every source it carries.

## Provenance (`data/demo/cloud_impact/provenance.json`)

- **Built from:** the frozen outputs of the pre-registered study (`configs/economic_impact/prereg.yaml`). The study was registered, scripted and run in the development repository and is published here as one commit; the pre-registration's publication note records its two wording edits and the SHA-256 of the file as registered.
- **Recorded inside:** the SHA-256 of every input (imports, prices, results), the price retrieval time (2026-10-20 15:05 UTC), the licences and the required attribution "Contains BMRS data © Elexon Limited copyright and database right 2024".
- **What the bundle contains:** derived data plus 24 half-hours of APX and system prices. Redistribution is permitted by the BMRS data licence with attribution, and by CC BY 4.0 for the UKPN and EUMETSAT-derived data.
- **Licence gate:** `build_cloud_impact_bundle.py` stops unless every source passes `gate.require(..., "redistribute_derived")` (`metadata/data_sources.yaml`, `metadata/licence_manifest.yaml`); the decisions are stored in `provenance.json`.
- **What it does not contain:** no UKPN flexibility data and no credentials. The app makes no runtime API call.

## Exact vs displayed

The UI rounds values for display:
- MWh to 0.1;
- GBP to £1;
- percentages to 0.1 %.

The 11:00 example is shown as "2.28 MWh × £96.76/MWh ≈ £221". The exact values are in the bundle and in `results.json`.

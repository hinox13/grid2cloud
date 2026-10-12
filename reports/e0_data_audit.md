# E0 data audit: UKPN feasibility (E0-D) and licences (E0-L)

_Updated 2 October 2026 with authenticated UKPN records._

The machine-generated companion is [`e0_ukpn_audit_generated.md`](e0_ukpn_audit_generated.md). Tables are in [`reports/tables/e0_ukpn_*.csv`](tables/) and the run summary is in [`experiments/e0_ukpn_audit/summary.json`](experiments/e0_ukpn_audit/summary.json). To reproduce:

```bash
uv run --env-file .env python scripts/audit_ukpn.py [--refresh] [--write-study-region]
```

## Verdict

**The public UKPN data supports the planned experiment, but no single study region is selected yet.**

- **Data joins.** Topology, site coordinates, operational measurements and solar assets **can be joined on published identifiers** (site functional locations and LTDS line/node names). Site-code joins succeed for 94–99.7% of rows.
- **Region candidates.** 147 grid-fed 33 kV networks ("BSP subtrees") were built from LTDS transformer connectivity; 100+ fall in the 10–50 node band.
- **Eligible regions.** **4 regions** pass every hard requirement fixed before the robustness check: Sundon 33 kV, Canterbury South 33 kV, Histon Grid and Fulbourn Grid.
- **No selection.** The pre-declared rule is that a region must rank first in at least 50% of random weightings of the five scores. The best eligible region, **Sundon 33 kV**, ranks first in **43.5%** of 2,000 weightings, and Canterbury South in 36%. So the evidence identifies a robust **shortlist of three**, not one defensible winner.
- **No study region file.** `configs/networks/study_region.yaml` was therefore **not created**. The script refuses to write it unless the rule passes.

## 1. Authenticated datasets loaded

Downloads were authenticated with an API key sent as a request header only. The key was never logged or persisted, and a scan found it in no repository file other than the gitignored `.env`. Every file has a SHA-256 hash, size, timestamp and export parameters in [`metadata/provenance.json`](../metadata/provenance.json).

| Dataset | Mode | Rows in portal | Rows retrieved |
|---|---|---|---|
| Grid and Primary Sites | full | 1,504 | 1,504 |
| LTDS T1 circuits | full | 5,076 | 5,076 |
| LTDS T2a transformers (2W) | full | 2,171 | 2,171 |
| LTDS T2b transformers (3W) | full | 143 | 143 |
| ECR ≥ 1 MW | full | 1,041 | 1,041 |
| ECR < 1 MW | full | 4,503 | 4,503 |
| 132 kV operational, monthly | full | 17,019 | 17,019 |
| 33 kV operational, monthly | full | 49,334 | 49,334 |
| 132 kV operational, half-hourly | **server-side aggregate per line** | 22,077,113 | 409 groups |
| 33 kV operational, half-hourly, SPN | **server-side aggregate per line** | 23,858,137 | 495 groups |
| 33 kV operational, half-hourly, **EPN** (newly registered) | **server-side aggregate per line** | 29,887,093 | 739 groups |

**No half-hourly rows were downloaded.** Per-circuit row counts, non-null counts for P and I, and first/last timestamps were computed on the server with an ODSQL `group_by`. Parquet exports reject grouping (`AggregationNotSupported`), so the aggregate is fetched as JSON and stored locally as Parquet.

**New source registered:** `ukpn-33kv-circuit-operational-data-half-hourly-epn`. It is CC BY 4.0, verified through the catalogue API, and passes the licence gate. It is relevant because most grid-fed 33 kV networks with published monthly data are in EPN. Licence drift was re-checked for all sources with `audit_licences.py --check-remote`, and none was found.

## 2. Real encodings and parser findings

| Field | Assumed in Phase 0 | Observed | Action |
|---|---|---|---|
| `redacted` (monthly) | bool-like | strings `'True'` / `'False'`; 0 nulls; 59,409 False / 6,944 True | Already parsed; 0 unparsed |
| `nominal_voltage` (monthly) | numeric | int `132` (132 kV dataset) or `33` (33 kV dataset) | 0 unparsed |
| `operating_voltage` (LTDS T1) | `'132'`, `'33'` | strings `'33'` 3,425 · `'132'` 1,011 · `'11'` 418 · `'66'` 142 · `'22'` 54 · `'6.6'` 26 | 0 unparsed; non-132/33 kV circuits excluded from the study network |
| `spatial_coordinates` | geo point dict or `"lat, lon"` | **21-byte little-endian WKB POINT, x = lon, y = lat** | **Parser added** (stdlib `struct`); sites 1,504/1,504, ECR ≥1 MW 1,041/1,041, ECR <1 MW 4,397/4,397 non-null parsed; 0 unparsed. The ECR `latitude`/`longitude` columns agree exactly |
| Licence area | — | `'Eastern Power Networks (EPN)'` (LTDS, sites, ECR) vs `'EPN'` (monthly) | `licence_area_code()` |
| ECR identifiers | nulls | **placeholders** `'-'` (≥1 MW: 280 BSP, 585 primary), `'Data not available'` (3), `'Direct'` (<1 MW BSP: 524), and nulls (<1 MW: 632) | Placeholders → missing and counted per column (`n_placeholder` in the missingness tables); `'Direct'` counted separately |
| Monthly `grid_supply_point` | GSP name | **not a GSP**: the metering site label with a site code, e.g. `SALL GRID (0D5023)` | Code → site FLOC (`EPN-S0000000D5023`) |
| LTDS T1 `fromsubstation_sitefunctionallocation` | FLOC | FLOC, or `'CUSTOMER_SITE'` (8), or null (1,346) | `CUSTOMER_SITE` treated as no key |
| **LTDS node IDs** | globally unique | **Not unique across licence areas.** `BROG31` is Broad Oak Grid (SPN), Brogborough Primary (EPN) and Bromley Grid (LPN); 84 codes recur across areas | **All node keys are now area-scoped** (`EPN:BROG31`). Unscoped, one bogus 33 kV "network" spanned 820 nodes and 18 GSPs. Scoped, only 2 nodes keep conflicting names |

Other counters, each counted and never silently dropped:

- **Monthly index:** 814 rows with a null `ltds_line_name`; 3,809 duplicate (line, month) rows. A month counts as public only if *every* row is unredacted.
- **Half-hourly:** 841,196 (132 kV), 98,829 (SPN 33 kV) and 100,344 (EPN 33 kV) rows with a null line name.
- **LTDS T1:** 65 area-scoped duplicate line names; 33 self-loop circuits skipped.
- **ECR:** 121 connected solar assets with no connected-capacity value (not imputed); 7 assets with solar only as a secondary technology (excluded and counted).

**Time coverage.**

- **Monthly index:** 2023-01 to 2026-08, but **2026-01 to 2026-07 are missing**. That gives 37 distinct months.
- **Half-hourly:** 2023-01-01 to 2026-08-31 in all three datasets. Individual circuits start later; for example, AMER_ILME_1 starts on 2024-05-15.

**Measurement content: a key finding.** In the half-hourly data, most circuits publish **current only**, and in EPN 33 kV each circuit publishes either current or active power, never both.

| Dataset | Lines | Current ≥ 80% complete | Active power ≥ 80% complete | Active power 0% |
|---|---|---|---|---|
| 132 kV | 408 | 387 | 251 | 141 |
| 33 kV SPN | 494 | 490 | 39 | 450 |
| 33 kV EPN | 738 | 645 | 106 | 631 |

The measurement criterion therefore has two levels:

- `usable`: current **or** P is published.
- `usable_active_power`: P specifically is published. E2's "direction agreement" needs signed P.

`measurement_score` is the mean of the two shares. Requiring P alone would have discarded most of the observed data. Of 4,370 study lines, 1,276 are usable and 282 are usable with active power.

## 3. Cross-dataset joins (real values)

Full table: [`tables/e0_ukpn_identifier_overlap.csv`](tables/e0_ukpn_identifier_overlap.csv).

- All joins are exact on the stated key.
- "Normalised" means upper-case, alphanumeric-only, with UKPN placeholders mapped to null.
- **No fuzzy matching was introduced.** Name-based site matching fails, but FLOC routes make it unnecessary.

| Join | Left rows | No key | Matched | Unmatched | Match % | Left dup rows | Right ambiguous keys | Ambiguous matches |
|---|---|---|---|---|---|---|---|---|
| Monthly line name → LTDS T1 `linename` (area-scoped) | 1,689 | 0 | 1,573 | 116 | **93.1** | 0 | 2 | 1 |
| LTDS T1 132/33 kV circuit (EPN/SPN) → monthly line | 3,913 | 0 | 1,583 | 2,330 | 40.5 | 65 | 0 | 0 |
| Monthly from/to node pair → T1 node pair (area-scoped, unordered) | 1,576 | 0 | 1,393 | 183 | **88.4** | 0 | 188 | 48 |
| Monthly (line + node pair) → T1 (line + node pair) | 1,611 | 0 | 1,322 | 289 | 82.1 | 0 | 0 | 0 |
| T1 from-substation FLOC → site FLOC | 5,076 | 1,354 | 3,527 | 195 | **94.8** | 3,538 | 0 | 0 |
| T2a FLOC → site FLOC | 2,171 | 102 | 2,057 | 12 | **99.4** | 1,999 | 0 | 0 |
| T1 from/to substation name → `sitename` (exact normalised) | 10,152 | 0 | 2,594 | 7,558 | 25.6 | 9,869 | 0 | 0 |
| Monthly site code → site FLOC | 205 | 1 | 200 | 4 | **98.0** | 0 | 0 | 0 |
| Monthly `grid_supply_point` label → LTDS GSP | 219 | 0 | 0 | 219 | 0.0 | 0 | 0 | 0 |
| ECR FLOC → site FLOC | 5,544 | 1,305 | 4,224 | 15 | **99.65** | 4,108 | 0 | 0 |
| ECR FLOC → LTDS T1/T2a site FLOC | 5,544 | 1,305 | 3,986 | 253 | **94.0** | 4,108 | 0 | 0 |
| ECR `grid_supply_point` → LTDS GSP (exact normalised) | 5,544 | 635 | 2,960 | 1,949 | 60.3 | 4,903 | 0 | 0 |
| ECR `bulk_supply_point` → LTDS substation name (area-scoped) | 5,544 | 1,463 | 3,760 | 321 | **92.1** | 4,023 | 0 | 0 |
| ECR `bulk_supply_point` → `sitename` | 5,544 | 1,463 | 558 | 3,523 | 13.7 | 4,023 | 0 | 0 |
| ECR `primary` → LTDS T2a `lv_substation` (area-scoped) | 5,544 | 1,288 | 3,728 | 528 | **87.6** | 4,066 | 4 | 11 |
| ECR `primary` → `sitename` | 5,544 | 1,288 | 214 | 4,042 | 5.0 | 4,066 | 0 | 0 |

How to read these joins:

- **LTDS ↔ operational joins work.** 93% of monthly line names exist in LTDS, and 88% of monthly node pairs match an LTDS circuit independently of the names.
- **Low LTDS → monthly coverage (40%) is mostly structure, not missing data.** The operational index meters whole circuits (e.g. `SU33_LBUZT_1`), while LTDS splits them into tee sections (`SU33_LBUZT_2_(3)`, …). The 188 ambiguous node pairs are parallel circuits between the same busbars.
- **Site FLOCs are the reliable geography key.** They match at 94–99.7%. Exact `sitename` matching fails at 5–26% because site names embed voltage ratios (`ILMER GRID 132/33kV` vs LTDS `Ilmer Grid 33kV`). Name matching works well *within* LTDS (ECR BSP/primary → LTDS names: 92%/88%).
- **GSP names are not a shared key.** Monthly labels match 0% of LTDS GSPs and ECR GSP names match 60% (`Brimsdown (EPN)`, `Pelham and Wymondley`, …). Regions are therefore defined from LTDS connectivity, not from GSP strings.

## 4. Geography and electrical attribution

- **Node coordinates.** Each node's substation names lead to site FLOCs: those published in LTDS T1/T2a/T2b, plus exact site names. Site coordinates then come from the FLOC. A node is *resolved* when all reachable FLOCs lie within 2 km of each other.
  - 2,860 of 4,317 study nodes are resolved, 22 are ambiguous, and 1,435 are unresolved.
  - Most unresolved nodes (1,282) are generic tee/boundary points (`EPN 0158`, `DNO-UKPN`) that have no site.
  - **LTDS has no coordinates of its own.** All coordinates are site coordinates (DERIVED).
- **Solar → electrical node, by identifiers only:** ECR site FLOC → LTDS transformer/circuit site → network node. If that fails, the ECR primary name → that primary's 33 kV busbar; then the ECR BSP name → that grid site's 33 kV busbar. Where a site has both 132 and 33 kV nodes, the ECR point-of-connection voltage picks one.
  - **Proximity is never used** to infer a connection.
  - Connected solar: **1,684 assets, 2,800.8 MW**. Attribution by route:

    | Route | Assets | MW |
    |---|---|---|
    | Site FLOC | 1,303 | 2,136.2 |
    | Primary name | 121 | 29.7 |
    | BSP name | 5 | 12.4 |
    | Unattributed | 255 | 622.6 |

  - A further 931 solar entries are "Accepted to Connect" (not built) and are excluded.
  - **Sanity check (diagnostic only):** the asset-to-attached-node distance has a median of 2.4 km and a p90 of 7.6 km; 1.3% exceed 30 km.

## 5. Candidate regions

Two region levels are ranked. Both use only 132/33 kV LTDS branches with area-scoped nodes:

- **`gsp`:** all branches under one LTDS GSP. There are 57 groups, with 4 to 394 nodes. 23 fall in the 10–50 band, but **none is eligible**: they fail on active-power measurements or solar.
- **`bsp_subtree`:** one grid-fed connected 33 kV network plus its 132/33 kV grid transformers. These come from splitting large GSPs **along LTDS transformer connectivity, not by truncation**. There are 147 subtrees (median 16 nodes, 33 kV-only), plus 20 unfed 33 kV islands (121 nodes) that are reported and not ranked.
  - 9 subtrees span two LTDS GSPs. These are most likely normally-open ties, but the planning tables don't publish switch states. They are flagged as a limitation.

**Scores, each in [0, 1].** Definitions are in [`configs/networks/candidate_regions.yaml`](../configs/networks/candidate_regions.yaml) and `ukpn_regions.py::score_regions`.

| Score | Definition |
|---|---|
| Topology | Mean of: parameter completeness; 1/number of components; share of nodes without conflicting names |
| Measurement | Mean of the `usable` and `usable_active_power` circuit shares |
| Solar | min(1, connected attributed MW / 50) |
| Coordinate | Share of nodes with resolved coordinates |
| Identifier | Share of indexed circuits whose LTDS name is unique and whose monthly node pair equals the LTDS pair |

The overall score is the equal-weight mean, × 0.5 when outside 10–50 nodes. **No GENCO output and no weather data enter the ranking.**

Top of [`tables/e0_ukpn_candidate_regions.csv`](tables/e0_ukpn_candidate_regions.csv) (204 regions):

| Region | Nodes | Circuits (132/33) | Usable I/P | P-capable | Solar MW (assets) | Topo | Meas | Solar | Coord | Ident | Overall | Eligible |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BSP EPN **Sundon 33kV** | 28 | 26 (0/26) | 10 | 9 | 43.9 (12) | 1.00 | 0.37 | 0.88 | 0.68 | 0.92 | **0.768** | yes |
| BSP SPN **Canterbury South 33kV** | 40 | 37 (0/37) | 11 | 3 | 39.2 (14) | 1.00 | 0.19 | 0.79 | 0.80 | 1.00 | **0.755** | yes |
| BSP EPN Austin Canons Grid 33kV | 12 | 9 (0/9) | 9 | **0** | 13.1 (14) | 1.00 | 0.50 | 0.26 | 1.00 | 1.00 | 0.752 | no: current only |
| BSP SPN Dormansland Grid 33kV | 13 | 10 (0/10) | 5 | **0** | 21.5 (7) | 1.00 | 0.25 | 0.43 | 1.00 | 1.00 | 0.736 | no: current only; spans 2 GSPs |
| BSP EPN **Histon Grid** | 31 | 31 (0/31) | 9 | 7 | 50.7 (10) | 1.00 | 0.26 | 1.00 | 0.71 | 0.69 | **0.732** | yes |
| BSP EPN Burwell Local Grid 33kV | 46 | 44 (0/44) | 5 | **0** | 153.2 (32) | 1.00 | 0.06 | 1.00 | 0.57 | 1.00 | 0.724 | no: current only; coordinates 0.57 |
| BSP EPN Letchworth Grid 33kV +1 | 44 | 41 (0/41) | 7 | **0** | 56.2 (16) | 1.00 | 0.09 | 1.00 | 0.52 | 1.00 | 0.722 | no: current only; coordinates 0.52 |
| BSP EPN Aylesbury East Grid 33kV | 46 | 51 (0/51) | 8 | 8 | 49.3 (13) | 1.00 | 0.16 | 0.99 | 0.46 | 1.00 | 0.720 | no: coordinates 0.46 |
| … | | | | | | | | | | | | |
| BSP EPN Fulbourn Grid 33kV | 27 | 24 (0/24) | 5 | 5 | 30.9 (7) | 1.00 | 0.21 | 0.62 | 0.81 | 0.75 | 0.678 | yes |

The "Circuits" counts are 33 kV only for BSP subtrees. The 132 kV side is represented by the grid transformers' HV busbars.

**Hard requirements.** Fixed after the first equal-weight ranking and **before** the sensitivity analysis:

- size in band;
- ≥ 5 usable measured circuits;
- ≥ 1 active-power circuit;
- ≥ 10 MW connected solar;
- coordinate score ≥ 0.6.

Of 204 regions, 4 pass. The most common reasons for failing are no active-power circuit (155) and too little connected solar (145).

**Robustness.** 2,000 Dirichlet weight draws, seed 20261002; full table in [`tables/e0_ukpn_rank_sensitivity.csv`](tables/e0_ukpn_rank_sensitivity.csv).

| Eligible region | Rank (equal weights) | P(rank 1) | P(top 3) | Median rank | Worst rank, leave-one-score-out |
|---|---|---|---|---|---|
| Sundon 33kV | 1 | **0.436** | 0.971 | 2 | 2 |
| Canterbury South 33kV | 2 | 0.363 | 0.987 | 2 | 3 |
| Histon Grid | 3 | 0.192 | 0.778 | 3 | 4 |
| Fulbourn Grid 33kV | 4 | 0.011 | 0.265 | 4 | 4 |

**Scoring correction, disclosed.** The first run defined the third topology component as "exactly one substation name". That penalised 1,282 unnamed tee points that `coordinate_score` already counts, contrary to the component's purpose of detecting name *conflicts*. It was corrected to "≤ 1 name" after the first ranking. The selection outcome is unchanged: before the fix, the best eligible region was Canterbury South at P(rank 1) = 0.46, with Sundon second at 0.32. Neither meets the threshold before or after.

### Shortlist

1. **Sundon 33 kV** (EPN; Luton / Dunstable / Leighton Buzzard; centroid 51.92 N, 0.52 W; diagonal ~14 km).
   - Network: 28 nodes (3 at 132 kV), 26 circuits and 3 grid transformers, all with complete R/X/ratings.
   - Measurements: **9 circuits with half-hourly active power**, which is the most direction-capable measurement of any eligible region.
   - Solar: 43.9 MW connected across 12 assets, **all attributed through site FLOCs**.
   - Limitations: 9 unnamed tee nodes have no coordinates; 14 of 26 LTDS sections are not separately metered (the metered circuits are whole tee'd lines); PV is concentrated in four farms of 20, 15, 6 and 2 MW at Sundon 33 kV.
2. **Canterbury South 33 kV** (SPN; ~27 km).
   - Network: 40 nodes and 37 circuits.
   - Measurements: 11 usable circuits, but only 3 with active power.
   - Solar: 39.2 MW across 14 assets.
   - Coordinates: 80% of nodes resolved.
3. **Histon Grid** (EPN; north Cambridge; ~17 km).
   - Network: 31 nodes and 31 circuits.
   - Measurements: 9 usable, 7 with active power.
   - Solar: 50.7 MW across 10 assets.
   - Identifier score 0.69. One LTDS transformer's LV substation is labelled "Histon Grid **132kV**", an LTDS naming anomaly.

**A scientific caveat that the ranking doesn't capture.** In all three regions, more than 95% of connected PV capacity sits in **four ≥1 MW farms** within roughly 15–30 km. That is enough to drive meaningful injections, but it gives limited *spatial* structure for H2 (spatial shuffling). Satellite pixels are ~3 km, so four farms are only a few independent forcing points. This should weigh in the final choice and may favour a slightly larger region or a pair of adjacent subtrees.

## 6. Recommended study region

**None selected.** Sundon 33 kV is the equal-weight leader and has the strongest active-power measurement coverage. However, it is first in only 43.5% of weightings (threshold 50%), and its lead over Canterbury South depends on how measurement is weighed against coordinates and identifiers. Choosing between the three shortlisted regions is a judgement about scientific priorities: direction-capable validation (Sundon, Histon), node geolocation (Canterbury South), and PV spatial diversity (none is strong). That judgement should be made explicitly by the project owner, not by the audit.

`configs/networks/study_region.yaml` was not created. Once a choice is made, `--write-study-region` will freeze the region's membership: nodes, branches, measured circuits, the half-hourly download scope, and solar assets referenced by site FLOC only. It does this only if the rule passes; changing the rule must be recorded here.

## 6a. Post-audit engineering decision (added 2 October 2026, after E0-D)

**No candidate passed the original robustness rule, and that result stands.** The ranking, weights, hard requirements and sensitivity analysis above are unchanged. Re-running the audit reproduces `reports/tables/e0_ukpn_candidate_regions.csv` byte-for-byte, and Sundon still ranks first in only 43.5% of weightings.

After the audit, the project owner **manually selected Sundon 33 kV** for E1/E2. This is an engineering decision. It is not a claim that Sundon passed the selection gate. The decision is recorded verbatim in [`configs/networks/region_decision.yaml`](../configs/networks/region_decision.yaml). `scripts/audit_ukpn.py --write-study-region` reads that file **only** when the original rule fails, and writes [`configs/networks/study_region.yaml`](../configs/networks/study_region.yaml) with:

- `selection.mode: post_audit_manual`;
- `passed_original_robustness_rule: false`;
- the original rule result.

Reasons given for Sundon:

- a compact network (28 nodes, 26 circuits);
- complete published electrical parameters;
- about 43.9 MW of connected solar, linked through identifiers;
- **the strongest active-power observation coverage among the eligible candidates** (9 circuits with half-hourly P).

**Why active-power coverage matters for the next stage.** E2 compares simulated and observed branch flows. Only active power carries a sign. So only P-metered circuits can test flow **direction** (README §20 E2), and only they can detect reverse power flow from embedded generation, which is the mechanism through which satellite-driven PV changes would act on this network. Current magnitude cannot tell import from export.

Known weaknesses accepted with the decision, not removed:

- 9 junction nodes have no geographic location;
- more than 95% of connected solar capacity sits in four farms;
- LTDS is planning topology;
- many 33 kV circuits publish current only.

E1/E2 then found further limitations; see [`e1_network_reconstruction.md`](e1_network_reconstruction.md) and [`e2_operational_validation.md`](e2_operational_validation.md).

## 7. Blockers and open issues

1. **The region choice needs a decision from you.** Either confirm one of the three shortlisted regions as a documented judgement, or change the rule (for example, weight active-power measurement above coordinates) and re-run. Changing the rule after seeing the results must be disclosed.
2. **Most 33 kV circuits publish current but not active power.** Validation on most circuits will be on |I| (magnitude, no direction). Only 282 study circuits have half-hourly P.
3. **Planning ≠ operational topology.** The LTDS does not publish normally-open points or switch states. Nine subtrees span two GSPs through probable open ties, and whole tee'd circuits are metered as one line. E1 must reconcile tee sections with metered circuits.
4. **The monthly index lacks 2026-01 to 2026-07.** Publication status in those months is unknown; half-hourly data does cover them.
5. **There is no LPN operational data** (neither monthly nor half-hourly). LPN regions can't be validated.
6. **Half-hourly rows have no licence-area field.** 17 study lines share a name across areas and are marked ambiguous for the 132 kV dataset.
7. **Unattributed PV:** 255 connected assets (622.6 MW) have no identifier route to a 132/33 kV node. Most likely they connect at levels or sites outside the LTDS 132/33 kV study network; this is not investigated.

## 8. Next step (not started)

Choose a region from the shortlist, or revise the rule and record the change here. Then:

1. Run `scripts/audit_ukpn.py --write-study-region`.
2. Download half-hourly data **only** for that region's measured circuits, filtered server-side by `ltds_line_name`.
3. Begin E1 network reconstruction.

## Attribution

All UKPN-derived tables in `reports/tables/` contain UK Power Networks data licensed under CC BY 4.0. Site coordinates additionally contain Ordnance Survey data © Crown copyright and database right [2019-], and data from the Office for National Statistics under the Open Government Licence v3.0. No customer-identifying ECR fields (names, addresses, MPANs) are written to any output.

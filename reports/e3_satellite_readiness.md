# E3 readiness: satellite experiment suitability and licence decision

> **Follow-up (E3 satellite ingestion, 2 Oct 2026):** [`e3_satellite_ingestion.md`](e3_satellite_ingestion.md).
> - §3 is superseded by **real** MDSSFTD pixel geometry: Sundon 1.83 effective pixels; Canterbury South 3.06. The H2 classes are unchanged.
> - §7 access note corrected: the RGB collections are distributed only via anonymous EUMETView WMS, so Data Store keys are not needed.
> - The text below is kept as written.

_2 October 2026. No satellite data was downloaded or processed._

To reproduce:

```bash
uv run python scripts/satellite_suitability.py
```

Outputs:

- [`tables/e3_region_solar_geometry.csv`](tables/e3_region_solar_geometry.csv) (per asset)
- [`tables/e3_region_satellite_suitability.csv`](tables/e3_region_satellite_suitability.csv) (per region)
- [`experiments/e3_satellite_readiness/suitability.json`](experiments/e3_satellite_readiness/suitability.json)
- [`figures/e3_region_solar_geometry.png`](figures/e3_region_solar_geometry.png)

## Decisions at a glance

| Question | Answer |
|---|---|
| Sundon network | Remains **B — usable with limitations**. Default interpretation for later stages: `sundon_capacity_scaled_with_outages` ([`e2_topology_sensitivity.md`](e2_topology_sensitivity.md)) |
| H2 (spatial correlation) | Sundon **WEAK**, Canterbury South **PLAUSIBLE**, Histon **WEAK** |
| Experiment structure | **Option B**: Sundon primary (temporal/generalisation); Canterbury South secondary (spatial correlation, H2) |
| Quantitative forcing | **LSA SAF MDSSFTD (LSA-207)**, unchanged: CC BY 4.0, archive 2004–2026 |
| Visual imagery | **E-View** and **Natural Colour Enhanced RGB**: now VERIFIED CC BY 4.0 (EUMETSAT Data Policy "Core") |
| Satellite stage | **CLEARED TO START**, subject to the access prerequisites in §6 |

## 1. Scope

**This is a SATELLITE EXPERIMENT SUITABILITY ANALYSIS, not a new E0 ranking.** The E0 ranking, rule and result are unchanged: `e0_ukpn_candidate_regions.csv` is byte-identical. Sundon's selection remains a post-audit manual decision.

The analysis compares the E0 shortlist using already-downloaded UKPN metadata only. Solar assets are the connected ECR assets attributed to each region's nodes **by identifiers** (the E0-D method). No satellite data, weather data or GENCO output is used.

The H2 criteria and the option rule were written in [`configs/experiments/e3_satellite_suitability.yaml`](../configs/experiments/e3_satellite_suitability.yaml) **before** computing Histon's and Canterbury South's geometry.

## 2. Solar spatial diversity

| Metric | Sundon 33 kV | Canterbury South 33 kV | Histon Grid |
|---|---|---|---|
| Connected solar (with capacity) | 43.9 MW, 12 assets | 39.2 MW, 13 assets¹ | 50.7 MW, 9 assets¹ |
| Assets for 50 / 80 / 90 / 95% of MW | 2 / 3 / 3 / 4 | 2 / 3 / 3 / 4 | 2 / 3 / 4 / 4 |
| Major assets (95% set), MW | 20, 15, 6, 2 | 15, 12, 9.5, 1 | 20, 20, 5, 4.5 |
| HHI / normalised HHI / effective number of assets | 0.344 / 0.285 / 2.9 | 0.299 / 0.241 / 3.3 | 0.329 / 0.246 / 3.0 |
| Pairwise distance, major assets (min–max) | 1.1–5.3 km | 4.5–14.6 km | 1.1–4.3 km |
| Capacity-weighted mean pairwise distance | **3.3 km** | **9.4 km** | **2.1 km** |
| Effective spatial extent (2 × weighted radius of gyration) | 4.9 km | 11.7 km | 2.9 km |
| E–W span of major assets | 3.9 km | 11.0 km | 2.7 km |
| Bounding box (all connected solar) | 51.887–51.951 N, 0.643–0.442 W | 51.221–51.324 N, 0.936–1.278 E | 52.272–52.334 N, 0.138–0.221 E |

¹ E0 counted one more connected asset in each of these regions; it has no published capacity value and is excluded here, not imputed.

All three fleets are **concentrated**: two assets hold more than 50% of the capacity and four hold 95%. They differ in **separation**. Canterbury South's major farms are three to four times further apart than Sundon's or Histon's.

## 3. Approximate satellite resolvability

**Approximation.** This uses the MSG/SEVIRI geometry, not product files. MDSSFTD is on the MSG grid with a nominal 3 km sampling at the sub-satellite point (0°E). At southern-England latitudes the viewing zenith is about 59°. The modelled footprint is therefore about **3.2 km E–W × 6.2–6.4 km N–S**, using dx = 3 km × slant range / altitude and dy = dx / cos(viewing zenith). The unknown grid phase is handled by Monte Carlo over 500 offsets. **Actual pixel independence must be checked on real product files later.**

| | Sundon | Canterbury South | Histon |
|---|---|---|---|
| Distinct pixels occupied by the 4 major assets (mean; min–max over grid phases) | 2.7 (2–4) | 3.9 (3–4) | 2.3 (1–4) |
| Capacity-weighted effective independent pixels | **2.1** | **3.0** | **1.6** |
| E–W span of major assets in pixel widths | 1.2 | 3.4 | 0.8 |
| Cloud-edge transit across the major assets at 5 / 10 / 15 m/s | 13 / 6.6 / 4.4 min | 37 / 18 / 12 min | 9 / 4.5 / 3.0 min |

Reading, with typical advection of about 10 m/s and a 15-minute product:

- **Sundon.** A front crosses all major farms within one frame. The 20 MW and 6 MW farms (1.1 km apart) almost always share a pixel; the 15 MW farm is about 3–4 km east, so roughly two independent forcing samples exist. Propagation between farms is **not** resolvable at 15 minutes.
- **Canterbury South.** About three independent pixels, and a front needs more than one frame to cross the 11 km E–W span. Staggered ramps are **plausibly** resolvable.
- **Histon.** Effectively one or two pixels. Not resolvable.

## 4. Operational observability (E0 coverage basis, same for all three)

| | Sundon | Canterbury South | Histon |
|---|---|---|---|
| P-capable circuits | **9** | 3 | 7 |
| Current-only circuits | 1 | **8** | 2 |
| Operational history (half-hourly) | 2023-01 → 2026-08 | 2023-01 → 2026-08 | 2023-01 → 2026-08 |
| Network size (E0 subtree) | 28 nodes / 26 circuits | 40 / 37 | 31 / 31 |
| Reconstruction status | **E1/E2 done — B**; sensitivity done | E0 audit only | E0 audit only |

Sundon's E1/E2 used a richer measurement set: transformer series and GIS meters, 12 P targets. The table uses E0 coverage for comparability.

## 5. H2 classification

The criteria are pre-defined; all conditions of a level must hold.

| Criterion | STRONG | PLAUSIBLE |
|---|---|---|
| Effective independent pixels | ≥ 4 | ≥ 2 |
| Capacity-weighted mean pairwise distance | ≥ 10 km | ≥ 5 km |
| E–W span of major assets | ≥ 9 km (≈ 1 frame at 10 m/s) | ≥ 4.5 km |
| Normalised HHI | ≤ 0.15 | ≤ 0.35 |
| P-capable circuits | ≥ 3 | ≥ 1 |

| Region | H2 | Fails the next level on |
|---|---|---|
| Sundon 33 kV | **WEAK** | weighted mean distance (3.3 < 5 km); E–W span (3.9 < 4.5 km) |
| Canterbury South 33 kV | **PLAUSIBLE** | for STRONG: effective pixels (3.0 < 4); weighted distance (9.4 < 10 km); normalised HHI (0.24 > 0.15) |
| Histon Grid | **WEAK** | effective pixels (1.6 < 2); weighted distance (2.1 < 5 km); E–W span (2.7 < 4.5 km) |

There is a further caveat specific to Sundon. E2 found the observed midday PV footprint in its measurements to be only about 1–2 MW (battery idle), which makes observed-data checks of PV-driven states weak there.

## 6. Recommended experiment design: **Option B**

The pre-declared rule gives:

- **Option A** requires Sundon H2 ≥ PLAUSIBLE. Sundon is **WEAK**, so A is not chosen.
- **Option C** requires another region to be STRONG, with ≥ 3 P-capable circuits and a non-marginal advantage. Canterbury South is only **PLAUSIBLE**, and its observability is current-dominated (3 P / 8 I). C is not chosen.
- That leaves **Option B**:
  - **Sundon 33 kV is the primary** network: temporal and generalisation experiments (H1, H3–H5, S0/S1/S3/S4). It has the most validated network (B, best P coverage) and two independent AC solvers.
  - **Canterbury South 33 kV is the secondary** network: the spatial-correlation experiment (H2, S1 vs S2). It first needs a lighter E1/E2 pass with the same tooling: reconstruction plus validation on its 3 P-capable circuits and its current meters.

Moving the whole project away from Sundon is **not** justified. The H2 gain at Canterbury South is real but not decisive (PLAUSIBLE, not STRONG), and its electrical observability is weaker.

## 7. Satellite licence decision

| Product | Purpose | Licence | Derived use | Redistribution | Public demo | Status |
|---|---|---|---|---|---|---|
| **LSA SAF MDSSFTD (LSA-207)** | Quantitative forcing (GHI/DHI → PV) | **CC BY 4.0** (LSA SAF data-usage policy; corroborated by EUMETSAT Data Policy Annex I: SAF Derived Products are "Core") | Allowed (adapt, any purpose) | Allowed, with attribution, no added restrictions | Allowed: cropped/processed values and derived PV in public bundles, with attribution, licence link and "modified" notice | **VERIFIED** |
| **European HRV RGB / E-View** (EO:EUM:DAT:MSG:EVIEW) | Visual cloud layer | **CC BY 4.0**: SEVIRI RGB = "Advanced Image Product" = "Core" (Data Policy amended 01-01-2025, Annex I/II; Art. 5.1) | Allowed | Allowed (Art. 6.1) | Allowed: frames in bundles, attribution "Contains modified EUMETSAT Meteosat data [year]" (Art. 6.3) | **VERIFIED** (was UNVERIFIED) |
| **Natural Colour Enhanced RGB** (EO:EUM:DAT:MSG:NCL_ENH) | Visual cloud layer (daytime; solar channels) | **CC BY 4.0** (same basis) | Allowed | Allowed | Allowed (same attribution) | **VERIFIED** (was UNVERIFIED) |
| Rapid Scan Natural Colour Enhanced (EO:EUM:DAT:0175) | Optional, not in MVP | not assessed | — | — | — | NOT ASSESSED (not proposed) |

**Evidence trail.**

- **EUMETSAT Data Policy**, `https://www-cdn.eumetsat.int/files/2025-02/45173 - Data_Policy(1442019 V1).pdf`, sha256 `7198d34b…5859c3`, "Last amended on 01 January 2025":
  - Annex I classes "All SEVIRI, FCI, IRS and LI Advanced Image Products" and "All … Derived Products" as **Core**.
  - Annex II defines an Advanced Image Product as an RGB channel combination containing no original numerical data, and defines Derived Products as including "all products generated by … the EUMETSAT Satellite Application Facilities (SAFs)".
  - Article 5.1: Core is "Free and Unrestricted … under a CC-BY-4.0 licence, regardless of when and how these are made available".
  - Article 6.1: "Users may redistribute all Core Data and Products".
  - Article 6.3 gives the attribution wording.
- **Data Store collection abstracts** confirm both visual collections are SEVIRI RGB composites (E-View: HRV + IR10.8; NCL_ENH: NIR1.6/VIS0.8/VIS0.6). Their `rights: NoConditions` is consistent with Free and Unrestricted. That field alone was **not** used as evidence.
- **The earlier block was correct at the time:** the licence wasn't established. It is now resolved from the authoritative policy. The README §38 example value was not copied.
- **Not covered by these licences:** Level 1 SEVIRI data with < 1 h latency (Recommended Data). The project will not use real-time Level 1 data.

**Access prerequisites** (registration, not licence restrictions):

- **LSA SAF data service:** "access … restricted to registered users". Free signup at `mokey.lsasvcs.ipma.pt`, HTTP basic auth. THREDDS/OpenDAP allows server-side spatial subsetting, so only the region crop is needed. The archive lists MDSSFTD in **NetCDF and HDF5 for 2004–2026**, with all 12 months of 2024, covering Sundon's validated window.
- **EUMETSAT Data Store** (E-View, NCL_ENH): free EUMETSAT EO Portal account and API consumer key/secret (EUMDAC).

Variable **names** are added to `.env.example`: `LSASAF_USERNAME`, `LSASAF_PASSWORD`, `EUMETSAT_CONSUMER_KEY`, `EUMETSAT_CONSUMER_SECRET`.

**Quantitative source decision.** MDSSFTD remains the forcing. No licence, access or technical blocker was found, and it is not replaced.

## 8. UI data requirements (specification only; no UI built)

The event-bundle schema is specified in [`metadata/event_bundle_schema.yaml`](../metadata/event_bundle_schema.yaml). Its tables cover:

- `event`, `attribution`, `satellite_frame`;
- `irradiance_by_asset`, `pv_by_asset`, `pv_by_bus`, `loads`;
- `ac_state`, `genco_state`, `error_state`;
- `network_nodes`, `network_edges`.

Each field has a provenance class (OBSERVED / DERIVED / SIMULATED / PREDICTED), units and the E1 area-scoped identifiers. Unlocated nodes carry `geolocation_status: unresolved` for schematic rendering. No bundle exists yet.

## 9. Satellite stage: **CLEARED TO START**

- All three proposed satellite products are **VERIFIED CC BY 4.0** and pass the licence gate for download, derive and public redistribution of derived assets.
- The quantitative product is available for the validated period.
- The primary network has a documented default interpretation (B).

Conditions that travel with the clearance:

1. **Credentials.** The user must register for LSA SAF and EUMETSAT Data Store access and provide credentials through environment variables. No downloader exists yet, and none should run automatically.
2. **Event windows.** Satellite events for Sundon should fall where E2 inputs exist (mostly 2024). Note that the 15 MW farm connected only in Feb 2026, a period with almost no validated states.
3. **H2 scope.** H2 on Sundon is WEAK. Spatial-shuffle results there must be labelled accordingly, and the H2 test belongs to Canterbury South once its E1/E2-lite pass is complete.
4. **The pixel model is approximate.** Verify actual MDSSFTD grid geometry and pixel independence on the first downloaded files before relying on §3.

## Attribution

Contains UK Power Networks data licensed under CC BY 4.0; site coordinates contain Ordnance Survey data © Crown copyright and database right [2019-] and ONS data under the Open Government Licence v3.0.

Licence text is quoted from the EUMETSAT Data Policy and the LSA SAF data-usage policy.

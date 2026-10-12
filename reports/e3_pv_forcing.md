# E3 PV forcing: Sundon PV inventory, historical capacity, PV model, bus mapping

_2 October 2026; satellite-driven series completed 6 October 2026._

To reproduce:

```bash
uv run python scripts/build_pv_timeseries.py            # inventory + model checks (+ series if crops exist)
```

Outputs:

- [`tables/e3_pv_assets.csv`](tables/e3_pv_assets.csv)
- [`tables/e3_pv_model_checks.csv`](tables/e3_pv_model_checks.csv)
- [`experiments/e3_satellite/pv_timeseries.json`](experiments/e3_satellite/pv_timeseries.json)
- Satellite-driven series, once MDSSFTD is available: `data/processed/satellite/sundon/{irradiance_by_asset,pv_by_asset,pv_by_bus,field_stats}.parquet`

Configuration: [`configs/experiments/e3_pv_model.yaml`](../configs/experiments/e3_pv_model.yaml) (written before any radiation data were available).

All output is **satellite-driven estimated PV generation**, never measured generation.

## Answer

- **Only 8.945 MW of Sundon's PV was connected in 2024**, against 43.9 MW today:
  - 6 MW at 33 kV (ECR:955, connected 2015);
  - 2 MW at 11 kV (ECR:526, Dec 2023);
  - 0.945 MW in eight sub-1 MW sites.
- The 15 MW farm connected in Feb 2026. The undated 20 MW farm was **not connected before 29 May 2026**, according to published LTDS evidence (below).
- The PV chain (pvlib) has run on **real MDSSFTD data for April–September 2024**: 9,040 slots, of which 8,308 are usable. All physical checks pass (§4a).
- PV maps to buses through E0's identifier link, never through geography.

## 1. Inventory (E0 attribution is authoritative)

Assets come from the generated study region, which records the E0 site-FLOC link for each asset. Date and status fields are joined from the ECR; no customer fields are used.

| Asset | Status | MW | kV | Connected | Flexible | Injection nodes | Active Apr–Sep 2024 |
|---|---|---|---|---|---|---|---|
| ECR:953 | Connected | 20.0 | 33 | — (undated; "in queue: Yes") | yes | LBUZ31/32/33 | **no**: EXCLUDED_BY_EVIDENCE |
| ECR:449 | Connected | 15.0 | 33 | 2026-02-25 | no | LBUZ31/32/33 | **no**: NOT_YET_CONNECTED |
| ECR:955 | Connected | 6.0 | 33 | 2015-03-30 | no | LBUZ31/32/33 | **yes** |
| ECR:526 | Connected | 2.0 | 11 | 2023-12-01 | no | LBUZ51/5A | **yes** |
| 8 assets < 1 MW | Connected | 0.945 total | LV/11 | 2013–2015 | — | CHAU51/52, LBUZ51/5A, LEWS51 | **yes** |
| 6 assets | Accepted to Connect | 75.1 (≥1 MW) | — | — | — | — | no |

The full table, with dates, reasons and pixel IDs, is [`tables/e3_pv_assets.csv`](tables/e3_pv_assets.csv).

## 2. Historical capacity

The rules (`solar/capacity.py`) applied at each timestamp:
- **ACTIVE** if `date_connected ≤ t`;
- **NOT_YET_CONNECTED** if later;
- **NOT_CONNECTED** if only accepted;
- **UNDATED** (excluded by default, and reported) if connected but without a date or other evidence;
- **EXCLUDED_BY_EVIDENCE** if published data date it.

**The 20 MW farm (ECR:953).** The ECR gives no connection date. It has `in_a_connection_queue = Yes` despite "Connected", and `last_updated` is 2026-08-14. LTDS Table 5 is the "snapshot of existing distributed generation" ("Published 29th May 2026").

| LTDS T5 group | Connected (MVA → MW at T5's MW/0.95 convention) | ECR dated assets before snapshot | Undated | Verdict |
|---|---|---|---|---|
| Sundon 33kV, PV, 33 kV (T5 row 328) | 22.105 MVA → **21.0 MW** | ECR:449 15 MW + ECR:955 6 MW = **21.0 MW** | ECR:953 20 MW | **undated not connected at snapshot** |
| Leighton Buzzard Primary 11kV, PV (row 310) | 2.105 MVA → 2.0 MW | ECR:526 2.0 MW | — | consistent |

- The MW/0.95 convention is confirmed independently on the battery row: 49.5 MW gives 52.105 MVA.
- So ECR:953 connected **after** the snapshot's data date, and is excluded from every 2024 timestamp.
- **Residual uncertainty:** the LTDS could have omitted a connected asset. The reconciliation is exact to 0.05 MW, which makes that unlikely, but it is an inference, not a dated record.

**Consistency with E2 (not calibration).** E2 measured a midday PV signature of only about 1.2 MW in May–Aug 2024 and could not explain it against "26 MW" of connected PV. With the historical fleet, 6 MW sits at 33 kV and 2.9 MW is embedded in primary loads. That narrows the gap considerably; it is recorded here and not used to tune anything.

## 3. PV model (pvlib; forcing, not fitted)

**Irradiance** (`solar/irradiance.py`). MDSSFTD gives total flux and diffuse fraction. The PUM defines fD as the ratio of diffuse to total solar irradiance, so:

- GHI = DSSF_TOT;
- DHI = fD × GHI;
- DNI = (GHI − DHI)/cos θz, via `pvlib.irradiance.dni`. This sets DNI to 0 for θz ≥ 88° and caps it at 1.1 × Ineichen clear-sky DNI for θz ≥ 80°. Any excess is returned to diffuse, so closure holds.
- Solar position is taken at the **acquisition** time (slot + 11.65 min).
- No decomposition model is used; the product's own diffuse fraction is the better-supported route.

**Plant** (`solar/pv.py`). Capacity-normalised: CF(t) is computed at unit AC capacity, then P(asset, t) = CF(t) × active capacity(asset, t), bounded to [0, active capacity].

| Step | pvlib component | Assumption (all ASSUMED; ECR has no plant engineering data) |
|---|---|---|
| Plane of array | `irradiance.get_total_irradiance`, Hay–Davies | fixed tilt 30°, azimuth 180°, albedo 0.2 |
| Incidence | `iam.ashrae` (beam) | b = 0.05 |
| Cell temperature | `temperature.faiman` | ambient 15 °C, wind 3 m/s (no met input; ±10 °C ⇒ about ±3–4 % in P below clipping) |
| DC | `pvsystem.pvwatts_dc` | DC/AC = 1.25, γ = −0.35 %/°C |
| Losses | `pvsystem.pvwatts_losses` | soiling 2, mismatch 2, wiring 2, connections 0.5, LID 1.5, nameplate 1 (%); availability/snow/shading 0 (annual derates, not instantaneous) |
| AC | `inverter.pvwatts` | η = 0.98; clipped at the ECR export capacity |

No parameter is fitted to UKPN data.

## 4. Sanity checks

**Model checks:** [`tables/e3_pv_model_checks.csv`](tables/e3_pv_model_checks.csv). The input is pvlib clear-sky irradiance × kc at the 6 MW asset. **This is not satellite data.**

| Case | GHI (W/m²) | CF | P (6 MW asset) |
|---|---|---|---|
| Night (00:00) | 0 | **0.000** | 0.00 MW |
| Clear noon, June | 832 | **1.000** (AC clipping) | 6.00 MW |
| Cloudy noon, June (kc 0.3, all diffuse) | 250 | **0.268** | 1.61 MW |
| Clear 06:00, June | 200 | 0.111 | 0.67 MW |
| Clear 19:30, June (elevation 6°) | 26 | 0.013 | 0.08 MW |
| Clear noon, December | 193 | 0.533 | 3.20 MW |

All checks pass: night is zero; output is bounded to [0, 1]; clear noon is high; cloud reduces output; low sun is lower; warmer is lower (CF 0.98 at 25 °C).

- **Clipping caveat:** with DC/AC 1.25, clear summer noon saturates. Moderate cloud dimming (kc 1.0 → about 0.85) is not visible in P. That is the physical behaviour of an oversized plant and is kept.
- **Satellite checks** (night = 0, clear high, cloud lower, bounds, and agreement between assets sharing a pixel) **ran on real data and pass** (§4a).

## 4a. Real satellite-driven series, Apr–Sep 2024 (6 Oct 2026)

Files: `data/processed/satellite/sundon/{irradiance_by_asset,pv_by_asset,pv_by_bus,field_stats}.parquet` (14.7 MB) and [`tables/e3_pv_satellite_checks.csv`](tables/e3_pv_satellite_checks.csv). No UKPN measurement was used and nothing was fitted.

| Quantity | Value |
|---|---|
| Active capacity (every slot) | **8.945 MW**: 10 assets. ECR:449 (2026) and ECR:953 (undated) contribute exactly 0 |
| Daylight slots expected / retrieved | 9,078 / 9,040 (38 absent from the LSA SAF archive) |
| Slots usable (every active asset GOOD) | **8,308** (91.9%) |
| Slots rejected | **732**: at least one active asset LOW_QUALITY. 495 involve the 6 or 2 MW asset |
| Asset-slot status | GOOD 95.24%, LOW_QUALITY 4.74%, MISSING 0.02%, INVALID 0 |
| LOW_QUALITY cause | PUM algorithm code 010 "cloudy: ATOA out of limits" (flags 77/73: thick cloud), evenly across all pixels |
| GHI range (GOOD) | 2.7 – 947 W/m²; median 361; p95 823 |
| Fleet capacity factor | p5 0.05, p25 0.21, **median 0.42**, p75 0.72, p95 1.00; 12.7% of slots ≥ 0.9 (AC clipping) |
| Aggregate PV maximum | **8.94 MW** = active capacity (first reached 2024-04-13 11:30) |
| Aggregate 15-min ramps (7,972 consecutive usable steps) | \|ΔP\| median 0.45 MW, p75 0.73, p95 1.76, p99 2.97; max **+5.86 / −6.13 MW** |

| Check | Result |
|---|---|
| 0 ≤ P ≤ historically active capacity | **0 violations** (P > capacity: 0; P < 0: 0) |
| Inactive assets (2026 and undated farms) | **0** non-zero values |
| Night behaviour (2024-06-15 00:00–00:45, 4 real slots) | every asset `NIGHT`, DSSF = 0, P = 0: **pass** |
| Assets reading the same sampled pixel | max capacity-factor spread 0.0005 (geometry only): **consistent** |
| Clear vs cloud | P follows the clear-sky index (e.g. 2024-06-15: 8.4 MW at clear 12:00, 2.4 MW at 11:00 under cloud, kc 0.38) |

**Observations (no change made):**

1. **Clear-sky index above 1.** On the clearest windows, mean kc is 1.15–1.18 against pvlib Ineichen with climatological Linke turbidity. This is a property of the clear-sky reference, which is too turbid on very clear days, or of MDSSFTD. It affects only the event features, not P. The class-A threshold (kc ≥ 0.85) is not sensitive to it.
2. **Thick cloud is under-represented in usable slots.** The frozen QC (`allow_low_quality: false`) excludes code 010, which occurs mainly under thick cloud. Overcast situations are therefore censored (event report §5).

## 5. PV → bus

The rule set (`solar/aggregate.py`):
- **33 kV assets** inject at the site's 33 kV busbars from E0 (LBUZ31/32/33). The section is not published, so the split is equal (ASSUMED).
- **≤11 kV assets** inject at the model load nodes of the same site FLOC (LBUZ51/5A, CHAU51/52, LEWS51).
- No nearest-neighbour reassignment is made. The LTDS alternative (T5 lists this PV under Sundon 33 kV) is kept for a sensitivity run (design note §6).

The output schema is `timestamp, bus_id, active_solar_capacity_mw, estimated_pv_mw, n_assets_active, n_assets_missing, quality`.
- A bus where any active asset lacks a usable value gets **NaN**, never a partial sum.
- Its quality is the worst contributing status.

**Embedded-PV treatment:** see [`docs/SATELLITE_SCENARIO_CONSTRUCTION.md`](../docs/SATELLITE_SCENARIO_CONSTRUCTION.md).
- In 2024 the 6 MW farm is the only injection *not* already inside observed loads.
- The 2.9 MW at ≤11 kV is inside the observed primary-transformer flows.

## Attribution

Data source: EUMETSAT LSA SAF, MDSSFTD (LSA-207), CC BY 4.0. Contains UK Power Networks data (Embedded Capacity Registers, LTDS Table 5), licensed under CC BY 4.0. PV modelling uses pvlib-python (BSD-3).

# E3 weather-event discovery: pre-registered criteria and results

_Criteria fixed 2 October 2026; run on real data 6 October 2026._

To reproduce:

```bash
uv run --env-file .env python scripts/build_pv_timeseries.py --acquire   # needs LSA SAF credentials
uv run python scripts/discover_weather_events.py
uv run python scripts/fetch_event_frames.py                             # E-View frames, selected events only
```

Outputs:

- [`tables/e3_candidate_events.csv`](tables/e3_candidate_events.csv)
- [`tables/e3_event_frames.csv`](tables/e3_event_frames.csv) (E-View frames per event)
- [`figures/e3_event_A.png`](figures/e3_event_A.png) … `e3_event_D.png` (top-ranked event per class)
- [`experiments/e3_satellite/event_discovery.json`](experiments/e3_satellite/event_discovery.json)

## Answer

The frozen criteria ran unchanged (config hash `90825a9180e792ed`; asset set hash `4b3ca8309397bdbb`, the 10 assets active in 2024) on 9,040 real MDSSFTD slots. They selected **10 candidate events**:

| Class | Candidates | Windows qualifying |
|---|---|---|
| A clear-sky control | **3** | 277 |
| B fast ramp | **3** | 322 |
| C broken cloud | **3** | 225 |
| D coherent transition | **1** | 1 |
| E overcast control | **0** | 0 |

E is empty and D is thin. This is a **result of the frozen definitions and the frozen quality rule**, not a code defect (§5). No threshold was changed. GENCO output, power-flow results, overloads and visual appeal were not used.

## 1. Search period (decided before any data)

| | |
|---|---|
| Period | **2024-04-01 → 2024-09-30** (UTC) |
| Why 2024 | Sundon's E2 inputs are complete through 2024: 12 validation timestamps in every month (`e2_timestamps.csv`) |
| Why Apr–Sep | midday solar elevation ≥ 30° at 52°N; long days |
| Fleet in the period | constant at **8.945 MW**: 6 MW HV + 2.945 MW embedded. Nothing is commissioned inside the window ([`e3_pv_forcing.md`](e3_pv_forcing.md) §2) |
| Slots | daylight only (elevation ≥ 10° at acquisition time): **9,078** slots |
| Data | analysis box 51.65–52.25 N, 1.05–0.15 W (13 × 19 cells), server-side subset |

GENCO results, AC power-flow errors, network loading and later model performance are **not** used. The discovery module imports nothing from the network or GENCO code, and a test enforces this.

## 2. Features (weather/PV only)

**Per 15-minute slot:**
- fleet capacity factor;
- fleet ramp (Δ over one slot; a gap breaks the ramp);
- maximum asset ramp;
- fraction of active capacity with |Δcf| ≥ 0.20;
- mean clear-sky index at the assets;
- analysis-box field: mean and standard deviation of kc, mean |∇kc| per km, and the fraction of clear (kc ≥ 0.8) and cloudy (kc ≤ 0.4) cells;
- solar elevation;
- validity: every active asset GOOD/NIGHT, and ≥ 90% of the box valid.

**Per 3-hour window (12 consecutive valid slots, elevation ≥ 20°):**
- mean and temporal standard deviation of kc;
- maximum one- and two-step ramp;
- count of significant ramps (|Δ| ≥ 0.15) and their sign changes;
- ramp persistence (longest same-sign run);
- event duration;
- recovery time after the largest down-ramp;
- field transition (start versus end thirds), with its Spearman trend and maximum gradient.

## 3. Classes and selection (pre-registered thresholds)

| Class | Definition |
|---|---|
| **A**: clear-sky control | mean kc ≥ 0.85; temporal std ≤ 0.05; field std ≤ 0.06; max ramp ≤ 0.05 |
| **B**: fast ramp | one-step \|Δcf\| ≥ 0.40, or two-step ≥ 0.50 |
| **C**: broken cloud | ≥ 3 sign changes among ≥ 4 significant ramps; 0.30 ≤ mean kc ≤ 0.85 |
| **D**: coherent transition | box ≥ 70% clear at the start and ≥ 70% cloudy at the end (or the reverse); \|ρ_trend\| ≥ 0.8; max gradient ≥ 0.02 kc/km |
| **E**: overcast control | mean kc ≤ 0.30; temporal std ≤ 0.05; field std ≤ 0.06 |

Selection:
- within each class, the top 3 by class score, with ties broken by the earlier start;
- windows are greedy and non-overlapping, with at least 24 h between events of the same class;
- the output records the config hash, the active asset set and its hash, and the product `algorithm_version`;
- the same inputs give the same events.

**Implication of the real geometry.** In 2024, Sundon's ≥1 MW PV sits in **one** native pixel. Sundon events will therefore be **temporal** events: ramps, broken cloud, transitions in time. Class D uses the 13 × 19-cell field around the assets to characterise the passing cloud structure, which also serves the visualisation. It does not imply spatially resolved forcing across Sundon's farms.

## 4. Candidate events (selection order; all times UTC)

Fleet = 8.945 MW. Ramps are per 15-minute slot, as a fraction of capacity (cf) or in MW.

| Event | Window | Score | Objective metrics | Fleet PV | Physical description (E-View inspected for **A01, B01, C01, D01**; others inferred from metrics only) |
|---|---|---|---|---|---|
| **A01** | 2024-09-16 11:45–14:30 | 1.154 | mean kc 1.18, temporal std 0.017, field std 0.006, max ramp 0.047 | 7.0–8.9 MW | Cloud-free England; smooth afternoon decline only |
| A02 | 2024-08-23 10:45–13:30 | 1.154 | kc 1.16, std 0.002, field std 0.004, no ramp | 8.9 MW flat (AC clipping) | Clear late-summer midday |
| A03 | 2024-05-20 10:30–13:15 | 1.150 | kc 1.16, std 0.003, field std 0.005, no ramp | 8.9 MW flat (clipping) | Clear spring midday |
| **B01** | 2024-07-07 08:00–10:45 | 0.756 | max ramp 0.61 cf (two-step 0.76); 3 significant ramps; 100% of capacity affected; recovery 60 min | 1.9–8.7 MW; **+5.4 MW** at 10:45 | Cloud band and cirrus moving off Sundon; fast clearing |
| B02 | 2024-06-15 08:45–11:30 | 0.725 | max ramp 0.64 cf (two-step 0.73); field kc 0.34 → 0.69 (ρ 0.87) | 1.5–8.9 MW; **+5.7 MW** at 11:15 | Morning cloud breaking up into sunshine |
| B03 | 2024-04-25 10:15–13:00 | 0.714 | max ramp 0.61 cf; 4 significant ramps, 3 sign changes | 2.2–8.7 MW; **−5.5 MW** at 12:45 | Showery spring day; sharp drop under a shower cloud |
| **C01** | 2024-04-15 12:15–15:00 | 7.176 | **7 sign changes** among 9 significant ramps; kc 0.83 ± 0.18; field std 0.24 | 1.8–8.8 MW; −4.5 MW at 14:15 | Broken cumulus over all of SE England, repeated on/off |
| C02 | 2024-06-10 10:15–13:00 | 7.149 | 7 sign changes / 9 ramps; kc 0.80 ± 0.15 | 5.1–8.9 MW; −3.7 MW at 12:45 | Fair-weather cumulus; shallower dips |
| C03 | 2024-08-20 08:30–11:15 | 6.199 | 6 sign changes / 9 ramps; field kc 0.95 → 0.66 (ρ −0.93) | 1.6–7.2 MW; +5.5 MW at 10:30 | Cumulus developing through the morning |
| **D01** | 2024-06-15 09:30–12:15 | 0.557 | box ≥70% cloudy → ≥70% clear; field kc 0.36 → 0.92; trend ρ 0.98; max gradient 0.031 kc/km | 1.5–8.9 MW; +5.7 MW at 11:15 | Coherent clearing of a cloud sheet over the whole analysis box |

**Overlap:** D01 and B02 describe the same clearing on 2024-06-15 and overlap by 2 h. Selection separates events only within a class, as pre-registered. They count as one physical event seen through two criteria.

## 5. Why E is empty and D is thin (diagnosis, no change)

- **Quality censoring.** Thick cloud frequently returns PUM algorithm code 010 ("cloudy: ATOA out of limits"; flags 77/73), which the frozen QC treats as LOW_QUALITY and excludes.
  - Only **35%** of slots with field kc ≤ 0.3 are valid.
  - Overcast windows rarely survive the requirement of 12 consecutive valid slots.
- **Field uniformity.** Of the valid windows, 37 had mean kc ≤ 0.30, 1 also had temporal std ≤ 0.05, and **none** had field std ≤ 0.06. Their median field std was 0.083: UK summer overcast is rarely spatially uniform over a 60 × 70 km box.
- **D** needs ≥70% of the box clear at the start and ≥70% cloudy at the end (or the reverse), within 3 h. 4 windows met that coverage condition, and 1 met all criteria.
- **Possible amendment for a later stage.** Allowing code 010 for class E, or relaxing the field-std limit, would have to be a new, logged config version with its reason. It would no longer be the pre-registered analysis. **Not done.**

## 6. RGB frames (selected events only)

- **120 E-View frames** were fetched: 12 per window for the 10 events, in the context box, ≥ 1 s apart.
- **120 / 120 matched** their MDSSFTD slot exactly (served time from the server header; Δ = 0 min; tolerance 7.5 min). None was rejected.
- The frames are stored in `data/interim/satellite/eumetsat/events/<event_id>/` (20 MB), because EUMETView re-renders and bytes can differ on re-fetch. Their hashes are in `metadata/provenance.json` and `tables/e3_event_frames.csv`.

**Suggested hero candidates** (chosen *after* objective selection, for display only):
- **D01 / B02** (2024-06-15 09:30–12:15): a coherent clearing with a +5.7 MW ramp.
- **C01** (2024-04-15): classic broken cumulus.
- **A01** (2024-09-16): a cloud-free control.

## 7. Next

E3 is complete. E4 (GENCO on weather-driven scenarios) has **not** been started. Its construction rules are in [`docs/SATELLITE_SCENARIO_CONSTRUCTION.md`](../docs/SATELLITE_SCENARIO_CONSTRUCTION.md).

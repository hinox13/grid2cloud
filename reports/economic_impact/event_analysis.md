# Economic impact: event analysis

**Sources:** `results.json`, `tables/event_*.csv`, `tables/periods.csv`, `tables/daily.csv`. **Figures:** `figures/event_2024-06-15.png`, `figures/method_comparison.png`.

**What every number below is:**
- **Energy:** AC-reconstructed import differences × 0.5 h per settlement period.
- **Value:** that energy × the APX Market Index price of the same period, unless stated otherwise.
- **Status:** an **illustrative avoided-import valuation, not a realised saving.** Contains BMRS data © Elexon Limited copyright and database right 2024.

## Season (all 2,820 valued half-hours; not every daylight half-hour of the season)

One valued half-hour, 2024-04-13 07:00 UTC (SP 17), has no APX price at source: its energy is counted, its value omitted (≤ £4.14).

| | Energy (MWh) | Value, APX (£) | Value, system price (£) |
|---|---:|---:|---:|
| Import displaced by the 6 MW plant (ΔI_pv) | 4,038 | 234,226 | 225,211 |
| Extra import because clouds held the plant below clear sky (ΔI_cloud) | 1,428 | 93,286 | 99,224 |
| For scale: total AC import in the same half-hours | 68,580 | 4,379,353 | — |

- **Consistency:** the re-solved base reproduces every frozen S1 import to within 0.00001 MW.
- **Energy sensitivity:** using the half-hour mean of the two 15-min PV estimates changes the PV-attributed value by +£51 (+0.02 %).
- **Losses:** AC needs 1.016 MW more import per MW of PV removed (median), because local generation also reduces network losses.
- **Prices:** the APX price over the valued half-hours averaged £64/MWh (median £72). 180 half-hours had negative prices, and they are kept.
- **Per day (136 days):** the cloud-attributed value has a median of £602, a 90th percentile of £1,698 and a maximum of £2,707 (1 June).

## The four events

| Day | Half-hours (UTC) | PV-attributed: MWh / £ | Cloud-attributed: MWh / £ | Rank of cloud value among 136 days | APX range (£/MWh); day mean percentile |
|---|---|---|---|---:|---|
| **15 Jun**, cloud clearing (Explorer) | 24 (05:00–16:30), SP 13–36 | 31.2 / **£2,890** | 16.9 / **£1,661** | 15 | 73.8–105.5; **97th** |
| **7 Jul**, 30-min PV ramp of +6.76 MW | 24 | 33.3 / £2,524 | 12.7 / £1,033 | 46 | 25.9–88.7; 54th |
| **15 Apr**, broken cumulus (Explorer) | 18 | 36.3 / £342 | 5.7 / £170 | 89 | −9.7–59.0; 8th |
| **23 Aug**, clear-sky control (Explorer) | 23 | 46.5 / £201 | −2.6 / £69 | 96 | −11.9–87.4; 6th |

**Reading:**
- **15 June** combines a heavily clouded morning (the plant at 0.5–1.8 MW against a clear-sky 3–5.8 MW) with prices in the top 3 % of the season. It ranks 15th of 136 days for cloud-attributed value. The local clouds did not cause the national price level; the two simply coincided.
- **15 April** has more PV energy than 15 June (36.3 against 31.2 MWh), but prices near or below zero make it worth about 12 % as much (£342 against £2,890). Price conditions, not just weather, set the economic exposure.
- **The clear-sky control (23 Aug)** has a negative cloud-attributed energy (the plant is above its clear-sky estimate at times), as a control should. Its small positive value comes from negative-price half-hours, where negative energy times negative price is positive.
- **Representative vs extreme:** a median day is about £600 of cloud-attributed import; 15 June is about 2.8× that; the season's extreme is £2,707.

### Exact calculation, 15 June

| Slot UTC | SP | PV (MW) | Clear-sky PV (MW) | AC import (MW) | ΔI_pv (MW) | ΔI_cloud (MW) | APX (£/MWh) | ΔI_pv value (£) | ΔI_cloud value (£) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 07:30 | 18 | 0.47 | 2.80 | 3.32 | 0.48 | 2.36 | 100.20 | 23.90 | 117.99 |
| 09:00 | 21 | 1.42 | 4.59 | 59.55 | 1.45 | 3.22 | 105.38 | 76.18 | 169.47 |
| 11:00 | 25 | 1.46 | 5.97 | 54.37 | 1.48 | 4.57 | 96.76 | 71.66 | 220.87 |
| 11:30 | 26 | 6.00 | 6.00 | 34.04 | 6.06 | 0.00 | 95.87 | 290.68 | 0.00 |
| 13:00 | 29 | 1.60 | 5.86 | 72.47 | 1.62 | 4.31 | 87.28 | 70.65 | 188.18 |
| 14:00 | 31 | 5.95 | 5.24 | 67.87 | 6.01 | −0.72 | 73.78 | 221.75 | −26.52 |

How to compute a row: value = ΔI × 0.5 h × price. For example, 11:00: 4.57 MW × 0.5 h × £96.76 = £220.87. All 24 rows are in `tables/event_2024-06-15.csv`.

The 11:00 → 11:30 clearing (+4.5 MW at the plant) **removes** the cloud-attributed import of the 11:00 period (£221) in the 11:30 period. The ramp is valued period by period, never as one endpoint difference × duration.

## Limitations

- **Coverage:** only the explicit 6 MW plant is varied. The ≤ 11 kV PV (about 2.9 MW) stays inside the metered loads.
- **Sample:** the half-hours valued are the 2,820 S1 states (usable, daylight, no line out), not the whole season.
- **Inputs:** PV is a satellite-derived estimate and the import an AC reconstruction; neither is a meter reading.
- **Prices:** MID is a short-term exchange index, not the price the plant or any supplier realised. The system price is an imbalance price, shown only as a separate scenario.
- **Interpretation:** no causation from local clouds to national prices, no future-price claim, no realised saving.

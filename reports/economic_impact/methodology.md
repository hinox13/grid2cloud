# Economic impact: methodology (pre-registered)

**Pre-registration:** `configs/economic_impact/prereg.yaml`, commit `593c2c6` (2026-10-20 15:05 UTC), before any valuation. The code (`scripts/economic_impact/`) was committed before it ran: fetcher and state builder `3abfb2b`, analysis `b0fcf7a`.

## Question

Under the observed 2024 GB prices:
1. What is the illustrative value of the grid-import energy attributable to the explicit 33 kV solar at Sundon, and of the extra import caused by clouds?
2. How accurately do simple accounting, E5c and E5d reproduce the AC-based estimate?

## Counterfactuals

**States:** each of the 2,820 intact AC-reconstructed half-hourly states (S1, April–September 2024) is solved three times on the same network (E1 planning case, the unchanged E5d pair machinery in `scripts/economic_impact/counterfactual.py`):

| State | Explicit 33 kV PV (ECR:955) | Everything else |
|---|---|---|
| S1 (as reconstructed) | the satellite-derived estimate at the slot | metered loads, battery, Q as reconstructed |
| CF_noPV | 0 | unchanged |
| CF_clear | its clear-sky estimate (same pvlib chain, Ineichen) | unchanged |

**Quantities:**
- **PV-attributed import:** ΔI_pv = I(CF_noPV) − I(S1), the import the plant displaced.
- **Cloud-attributed import:** ΔI_cloud = I(S1) − I(CF_clear), the extra import because clouds reduced the plant's output below clear sky.

**What the counterfactuals leave out:** the 2 MW and smaller ≤ 11 kV plants sit inside the metered loads and are **not** changed. "Absent", "clear" and "observed" refer to the explicit 6 MW plant only.

## Energy and value

- **Energy:** E = ΔI × 0.5 h per settlement period. Each state represents its settlement period: the loads are period averages, and the PV is the slot-start 15-min estimate.
  - Sensitivity check: replace the PV with the mean of the period's two 15-min estimates, scaled through the state's own AC response.
  - **No endpoint power change is ever multiplied by a duration as if it were an energy integral.** Every period is integrated separately.
- **Illustrative value:** V = Σ E × p, where p is the APX Market Index price (primary) or the imbalance system price (separate scenario) for the same period.

**Units:**

| Quantity | Unit |
|---|---|
| power | MW |
| energy | MWh |
| price | GBP/MWh |
| value | GBP |

Flexibility payments (GBP/MWh of utilisation) are a different object and are never mixed in.

**Alignment:**
- **Matching:** Elexon `startTime` (UTC) equals the S1 slot.
- **Recorded fields:** settlement date and period number.
- **Clock changes:** none inside the period (BST from 31 March to 27 October 2024).
- **Missing prices:** One valued half-hour, 2024-04-13 07:00 UTC (SP 17), has no APX price at source: its energy is counted, its value omitted (≤ £4.14).

## Methods compared for ΔI

| Method | ΔI_pv | ΔI_cloud |
|---|---|---|
| AC (reference) | pandapower AC difference | pandapower AC difference |
| Accounting | the explicit PV (lossless) | clear-sky PV − PV |
| E5c, E5d (frozen) | model(CF_noPV) − model(S1) | model(S1) − model(CF_clear) |
| Diagnostic: absolute mode | Σ model import × price compared with Σ AC import × price | — |

## Outcome rules (pre-registered)

| Outcome | Condition |
|---|---|
| **A (strong)** | prices for every event period, **and** E5d's season-value error ≤ 50 % of E5c's, **and** E5d's error is smaller than accounting's |
| **B (moderate)** | authentic prices and a physically meaningful valuation, but A fails |
| **C (weak)** | prices missing for the events, **or** a season PV-attributed value below £1,000, **or** the re-solved base deviating from the frozen S1 import by more than 0.05 MW |

## Interpretation limits (fixed in advance)

- **Not a financial saving:** the value is the illustrative market value of energy the plant displaced at the Sundon boundary, essentially that energy's wholesale value. It is not a saving realised by UKPN, a supplier or a customer.
- **No price causation:** no causal link is claimed between local clouds and national prices.
- **Historical only:** these are historical valuations, not forecasts.
- **No flexibility cost:** no avoided-flexibility cost is claimed (`data_sources.md`).

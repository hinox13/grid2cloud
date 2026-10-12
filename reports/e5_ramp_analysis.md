# E5: ramp tracking and hero events after topology adaptation (E4-D repeated)

_7 October 2026._
- Frozen checkpoint `ft_n50000_s0` (commit `61a4fbd`).
- Ramp bins frozen to the E4 edges in [`configs/experiments/e5_topology_adaptation.yaml`](../configs/experiments/e5_topology_adaptation.yaml); test `test_ramp_bins_frozen_to_e4_edges`.

Outputs:
- [`tables/e5_ramp_conditioned.csv`](tables/e5_ramp_conditioned.csv)
- [`tables/e5_transitions_by_event.csv`](tables/e5_transitions_by_event.csv)
- [`figures/e5_ramp_conditioned.png`](figures/e5_ramp_conditioned.png)
- `figures/e5_hero_*.png`
- [`experiments/e5/hero/`](experiments/e5/hero/) (UI-ready CSVs)

## Answer

- **Topology adaptation does not recover physical sensitivity to PV ramps; it swaps under-response for over-response.**
  - The median branch-flow tracking ratio moves from 0.46 to **1.37** in the extreme bin.
  - The absolute transition error is **4× larger**: 0.84 against 0.21 MW per edge, with a true change of 0.28.
  - Voltage-change and angle-change errors now exceed the true changes in every bin.
- The pre-registered "ramp improved" test, |1 − ratio| smaller than zero-shot in the high and extreme bins, is formally met (0.37 < 0.54). It is misleading here and does not count as an improvement in the E5 verdict ([`e5_weather_generalisation.md`](e5_weather_generalisation.md) §6).
- **On the hero events:**
  - The adapted import now has the right sign but sits about 50 MW too high.
  - It moves with the half-hourly load steps, not with the satellite PV ramps.
  - Its local voltages are biased about +0.03 pu.

## 1. Ramp-conditioned tracking (within-half-hour transitions: load held, PV only)

Same 2,739 primary transitions and same bins as E4. Branch P quantities are per directed edge; adapted 95 % CIs are day blocks.

| Bin (\|ΔPV\| MW) | n | AC \|ΔP\| | ΔP error zero-shot → adapted | Median tracking ratio zero-shot → adapted | AC \|ΔVm\| (pu) | ΔVm error zero-shot → adapted | AC \|ΔVa\| (°) | ΔVa error zero-shot → adapted | Adapted end-state PBE |
|---|---|---|---|---|---|---|---|---|---|
| low (0–0.33) | 1,370 | 0.020 | 0.031 → 0.077 [0.058, 0.107] | 1.14 → **1.91** | 3.0e-5 | 2.8e-5 → 4.0e-5 | 0.0090 | 0.0083 → 0.0098 | 34.5 |
| medium (0.33–0.67) | 821 | 0.062 | 0.057 → 0.186 [0.147, 0.233] | 0.62 → **1.47** | 9.5e-5 | 8.6e-5 → 1.2e-4 | 0.028 | 0.026 → 0.030 | 30.6 |
| high (0.67–1.40) | 411 | 0.130 | 0.106 → 0.561 [0.321, 0.916] | 0.50 → **1.37** | 2.0e-4 | 1.8e-4 → 2.6e-4 | 0.059 | 0.055 → 0.064 | 31.4 |
| extreme (1.41–4.20) | 137 | 0.277 | 0.210 → **0.839** [0.606, 1.192] | **0.46 → 1.37** | 4.3e-4 | 3.9e-4 → 5.4e-4 | 0.126 | 0.116 → 0.136 | 49.4 |

**Reading:**
- Zero-shot GENCO barely moved when PV ramped.
- The adapted model moves too much and in the wrong places: Σ|ΔP_GENCO| exceeds Σ|ΔP_AC| by 40–90 %, and the element-wise error is larger than the true change.
- The end-state error rises in the extreme bin (49 against about 31 MVA): large PV injections push states further outside the synthetic support (§2 of [`e5_topology_adaptation.md`](e5_topology_adaptation.md)).
- **The pre-registered "acceptable" band** for the extreme-bin ratio is [0.8, 1.25]; 1.37 is outside it.

## 2. Pre-registered events (E3 frozen; same transitions and tagging as E4)

| Event | Class | States | Tracking ratio zero-shot → adapted | PBE zero-shot → adapted |
|---|---|---|---|---|
| B01 2024-07-07 | fast ramp | 12 | 0.57 → 2.06 | 49.1 → 8.9 |
| B02 2024-06-15 | fast ramp | 12 | 0.83 → 2.80 | 49.0 → 12.4 |
| B03 2024-04-25 | fast ramp | 12 | 0.96 → 2.70 | 48.5 → 12.4 |
| C01 2024-04-15 | broken cloud | 12 | 0.43 → 0.64 | 49.2 → 3.7 |
| C02 2024-06-10 | broken cloud | 12 | 0.64 → 3.54 | 48.4 → **63.1** |
| D01 2024-06-15 | coherent transition | 12 | 0.64 → 1.68 | 49.4 → 6.8 |
| A02 2024-08-23 | clear control | 12 | 0.80 → 2.70 | 49.8 → 7.3 |
| A03 2024-05-20 | clear control | 12 | 1.03 → 7.62 | 48.9 → 10.4 |
| A01, C03 | | 0 | not evaluable (LBUZ51 gap, as in E4) | |

Event windows include half-hour crossings, where load also changes. The adapted model's large ratios there show that it over-reacts to load steps too.

## 3. Hero events (AC vs zero-shot vs adapted)

| Hero | PV injected | AC import | Zero-shot import | Adapted import | Mean PBE zero-shot → adapted (DC-PF res.) | Local Vm, AC → adapted |
|---|---|---|---|---|---|---|
| **D01** 15 Jun clearing | 1.0 → 6.0 MW | 34–54 MW | −211.6 (flat) | 86–116 MW | 49.4 → 6.8 (0.09) | 0.997 → 1.023 |
| **B02** 15 Jun fast ramp | 1.0 → 6.0 MW | 34–60 MW | −211.5 (flat) | 72–116 MW | 49.0 → 12.4 (0.09) | 0.992 → 1.022 |
| **C01** 15 Apr broken cumulus | 1.2–6.0 MW swings | 54–62 MW | −211.6 (flat) | **97.8–98.7 (flat)** | 49.2 → 3.7 (0.11) | 0.981 → 1.014 |
| **A02** 23 Aug clear (illustration) | 6.0 (clipping) | 29–48 MW | −211.7 (flat) | 85–99 MW | 49.8 → 7.3 (0.09) | 0.974 → 1.024 |

- **D01, 11:15:** PV goes from 1.5 to 5.4 MW and the AC import falls 54 → 50 MW, while the adapted import stays at 116 MW. At 11:30 the load step (AC 50 → 34) is followed by the adapted model (116 → 88), but with about a 50 MW offset.
- **C01:** the AC import follows the cumulus-driven PV swings (54–62 MW); the adapted import is flat within ±0.5 MW.
- **Selected elements:** each hero CSV and figure carries two branch flows and one bus Vm/Va, chosen from the **AC response only** (largest AC range in the window). The selected branch is usually `CHAP31–SUND31`, the out-of-support customer node; there the adapted flow ranges −46 to +13 MW against an AC range of −6 to +9.

**Hero CSVs** (`experiments/e5/hero/<event>.csv`):
- keep every E4 hero column unchanged, holding the E4 zero-shot values identical to [`experiments/e4/hero/`](experiments/e4/hero/);
- add `adapted_*` columns, plus `branch_<f>_<t>_P_{ac,zero_shot,adapted}_mw` and `bus_<b>_{Vm,Va}_{ac,zero_shot,adapted}`.

The future event bundle can therefore show AC, zero-shot and adapted side by side.

## Attribution

UK Power Networks data (CC BY 4.0). EUMETSAT LSA SAF MDSSFTD, LSA-207 (CC BY 4.0). GENCO `gridfm/genco-pf-transfer` (Apache-2.0).

# E5: representation sensitivity of the near-zero-impedance area

_6–7 October 2026. Pre-registered in [`configs/experiments/e5_representation_sensitivity.yaml`](../configs/experiments/e5_representation_sensitivity.yaml) (commit `cb5b11d`), before any fine-tuning. No GENCO output was used for anything in this report._

To reproduce:

```bash
uv run --env-file .env python scripts/e5_representation_sensitivity.py analyse
```

Outputs:
- [`tables/e5_near_zero_z_branches.csv`](tables/e5_near_zero_z_branches.csv)
- [`tables/e5_representation_equivalence.csv`](tables/e5_representation_equivalence.csv)
- [`experiments/e5/representation.json`](experiments/e5/representation.json)

## Answer

- **The near-zero-impedance branches are real equipment, not artefacts.** They are short cable connections inside the Sundon grid/primary site:
  - three 265–337 m 132 kV cables from the GIS busbar to the three grid transformers;
  - a 25 m 33 kV cable from the Sundon 33 kV board to Sundon Primary transformer T2.
  
  Their **published impedances are at the LTDS quantisation floor**: R and X are 1–3 quanta of the printed 0.01 % (1e-4 pu).
- **Merging them is a defensible engineering simplification, but it is not AC-equivalent over the whole operating range.**
  - On all 2,829 real 2024 states (S1) the merged and original solutions agree within every pre-registered tolerance.
  - At the heavy loadings that the synthetic (S0-type) data cover (≥ 1.5 × the LTDS planning peak, 134–179 MW), the angle, reactive-flow and slack-Q differences exceed tolerance. The worst case is slack ΔQ 0.29 MVAr against a 0.05 MVAr tolerance.
- **Verdict (pre-registered rule): `SUNDON_MERGED_NEAR_ZERO_Z` REJECTED.** `SUNDON_ORIGINAL` remains the primary and only E5 representation. The after-adaptation 2×2 (zero-shot/adapted × original/merged) is therefore **not run**: the merged graph is not eligible.

## 1. Where E4's zero-shot error sat

In E4, 67 % of GENCO's per-bus power-balance error (S1) was on three 33 kV buses:

| GENCO bus | LTDS node | Share of PBE | Connection |
|---|---|---|---|
| 31 | `EPN:SUPR32`, Sundon Primary 33 kV (T2) | 34 % | 25 m cable `SU33_SU11_4` |
| 26 | `EPN:SUND31`, Sundon Grid 33 kV main board | 26 % | hub of every short branch below |
| 30 | `EPN:SUPR31`, Sundon Primary 33 kV (T1) | 7 % | 81 m cable `SU33_SU11_3` |

## 2. Branch impedances (100 MVA base)

Smallest series impedances in the network. "Quanta" is the number of LTDS 0.01 % steps.

| Branch | From → to | kV | Length | r / x (pu) | Quanta r / x | \|Y\| (pu) | ΔP per 0.001° of angle error | Merged by rule |
|---|---|---|---|---|---|---|---|---|
| SUG1_SUG1_1 | SUND1A → SUND11 (GIS) | 132 | 265 m | 1e-4 / 2e-4 | 1 / 2 | 4,472 | 7.8 MW | yes |
| SU33_SU11_4 | SUPR32 → SUND31 | 33 | 25 m | 2e-4 / 2e-4 | 2 / 2 | 3,536 | 6.2 MW | yes |
| SUG1_SUG1_3 | SUND1C → SUND11 | 132 | 337 m | 1e-4 / 3e-4 | 1 / 3 | 3,162 | 5.5 MW | yes |
| SUG1_SUG1_2 | SUND1B → SUND12 | 132 | 319 m | 1e-4 / 3e-4 | 1 / 3 | 3,162 | 5.5 MW | yes |
| Lne_NESD_T1 | SUND31 → SUND3A (GT1 tail) | 33 | 237 m | 3e-4 / 7e-4 | 3 / 7 | 1,313 | 2.3 MW | no |
| SU33_SU11_3 | SUND31 → SUPR31 | 33 | 81 m | 9e-4 / 6e-4 | 9 / 6 | 925 | 1.6 MW | no |
| Line(124) | SUND31 → SUND3C (GT3 tail) | 33 | 120 m | 5e-4 / 11e-4 | 5 / 11 | 828 | 1.4 MW | no |
| lne_SUND_CHAP, SU33_SU11_1/2 | SUND31 → … | 33 | 150–300 m | 1.0e-3 / 1.4e-3 | 10 / 14 | 581 | 1.0 MW | no |

**What they are:**
- **SUG1 cables:** 132 kV cable connections from the Sundon GIS busbars (SUND11/SUND12, coupled) to the HV terminals of the three 90 MVA 132/33 kV grid transformers.
- **NESD and Line(124):** the transformers' 33 kV cable tails.
- **SU33_SU11:** 33 kV cables from the Sundon Grid 33 kV board to the co-located Sundon Primary 33/11 kV transformers.
- **Classification:** these are true electrical branches (cable connections and transformer tails). They are not busbar sections, jumpers, tee points or LTDS artefacts, but they are short enough that LTDS can only state their impedance to ±50 %.

**Why the metric is stiff:** ∂P/∂θ on these branches is 3–4.5 × 10⁵ MW per radian. So a GENCO angle error of one thousandth of a degree across a single one of them is 5–8 MW of apparent power-balance error.
- **Erratum to E4.** [`e4_zero_shot.md`](e4_zero_shot.md) §5 quotes "|Y_ft| up to 3.5 × 10⁵ pu". The admittance is 3.5 × 10³ pu (`SU33_SU11_4`; the largest, `SUG1_SUG1_1`, is 4.5 × 10³ pu). 3.5 × 10⁵ is the same quantity expressed as MW per radian on 100 MVA. The E4 conclusion is unaffected; the E4 report is not edited.

**Metric conditioning:** the PBE of the *exact* AC solution evaluated in float32, GENCO's arithmetic, is 0.0042 MVA, against 1.3e-6 MVA in float64. The metric's numerical floor is therefore four orders of magnitude below GENCO's zero-shot error (49 MVA) and about 50× below DC-PF's residual (0.1–0.2 MW), so adaptation targets near DC-PF accuracy are measurable.

## 3. Merge rule and method (pre-registered)

**Rule:**
- non-transformer branch;
- same nominal voltage at both ends;
- |r + jx| ≤ 5 × 10⁻⁴ pu.

It selects exactly the four branches expected. The next-smallest branch is 7.6 × 10⁻⁴ pu.

**Method:**
- each line becomes a closed zero-impedance bus–bus switch, which pandapower fuses into one node as it already does for the SUND11–SUND12 coupler;
- its charging is kept as a shunt;
- an observed outage of a merged line opens its switch. E2's outage detection removes `SUG1_SUG1_3` on some days, for example 1 Sep 2024. This was recorded in the config before any equivalence result.

The GENCO graph shrinks from 37 to 33 buses.

## 4. AC equivalence (same states, pandapower AC PF)

| Population | States | max \|ΔVm\| (pu) | max \|ΔVa\| (°) | max \|ΔP\| branch (MW) | max \|ΔQ\| branch (MVAr) | \|Δ slack P\| (MW) | \|Δ slack Q\| (MVAr) | Within tolerance |
|---|---|---|---|---|---|---|---|---|
| S1 real states (2024) | 2,829 | 1.05e-4 | 0.0072 | 0.0098 | 0.0074 | 0.0055 | 0.020 | **all 2,829** |
| Planning peak × 1.0 (89 MW) | 1 | 7.7e-5 | 0.0056 | 0.0078 | 0.0050 | 0.0034 | 0.012 | yes |
| × 1.25 (112 MW) | 1 | 1.2e-4 | 0.0081 | 0.0099 | 0.0087 | 0.0058 | 0.023 | yes |
| × 1.5 (134 MW) | 1 | 1.7e-4 | **0.0119** | 0.0121 | 0.0152 | 0.0095 | 0.043 | **no** (ΔVa) |
| × 1.75 (156 MW) | 1 | 2.9e-4 | **0.0194** | 0.0147 | 0.0291 | 0.0157 | **0.085** | **no** |
| × 2.0 (179 MW) | 1 | 8.2e-4 | **0.0562** | 0.0206 | **0.0980** | 0.0348 | **0.294** | **no** |
| **Tolerance** | | 1e-3 | 0.01 | 0.05 | 0.05 | 0.05 | 0.05 | |

The merged solution itself balances to 1.2e-6 MVA.

**Interpretation:**
- The differences grow faster than linearly with load: I²X in the removed cables, amplified as the network approaches its voltage limit (S0 states reach Vm ≈ 0.8 pu).
- **For the real 2024 operating range the merge would be harmless.** It is still rejected, as pre-registered, because:
  - the representation must hold for every family GENCO sees;
  - the synthetic adaptation data live in the heavy regime (100–179 MW).

## 5. Consequence for E5

- Every E5 result uses `SUNDON_ORIGINAL`: the network of E4, unchanged.
- The question "how much error is representation?" cannot be answered with an AC-equivalent alternative graph. It is addressed indirectly in [`e5_topology_adaptation.md`](e5_topology_adaptation.md) by locating where the adapted model's residual error sits.

## Attribution

UK Power Networks LTDS and operational data (CC BY 4.0).

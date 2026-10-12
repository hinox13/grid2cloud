# E4-A: GENCO zero-shot on Sundon (topology baseline)

_6 October 2026._
- Pre-registration: commit `6ebb60e`; amendment A1: `6df2ae8`.
- E3 baseline: `55ba739`.
- No GENCO weights were changed.

To reproduce:

```bash
uv run python scripts/run_genco_e4.py fetch
uv run python scripts/run_genco_e4.py reproduce                      # paper zero-shot, IEEE 118
uv run --env-file .env python scripts/build_synthetic_s0.py          # S0 (datakit, needs Julia)
uv run python scripts/run_genco_e4.py fit-normalizer                 # fixed per-unit base from S0
uv run python scripts/run_genco_e4.py predict --family S0_STANDARD_SYNTHETIC
uv run --env-file .env python scripts/evaluate_e4.py
```

Outputs:
- [`tables/e4_family_summary.csv`](tables/e4_family_summary.csv)
- [`tables/e4_scenario_metrics.parquet`](tables/e4_scenario_metrics.parquet)
- [`experiments/e4/`](experiments/e4/): reproduction, runs, families, evaluation.json
- [`../metadata/scenario_registry.yaml`](../metadata/scenario_registry.yaml)

## Answer

- **Zero-shot GENCO does not work on Sundon.** On the conventional synthetic family (S0), its average active power residual is **33.7 MW**. A DC power flow on the same states gives **0.23 MW**, about **150× better**. This is the pre-registered `topology_poor` condition.
- The failure is structural, not statistical:
  - GENCO predicts a grid import of about **−206 to −211 MW** (supply reversed) against about **+40–120 MW** in AC.
  - Its voltage predictions are barely related to the AC voltages.
  - Two-thirds of the power-balance residual sits on three 33 kV buses joined by extremely low-impedance branches.
- **Environment check passed first.** The same checkpoint and tooling reproduce the GENCO paper's own zero-shot result on IEEE 118 to within 0.03% on every metric.
- Following the pre-registered rule, this is **B — topology shift dominates**.

## 1. Model and environment

| Item | Value |
|---|---|
| Checkpoint | `gridfm/genco-pf-transfer` @ `e7a98e99221ba8241385e491787aedb0940d5130`, `pretraining/best_model_state_dict.pt` (run `1_h_100_32`, pretrained on 100 subgrids). This is the checkpoint the GENCO paper (§5.5.3) evaluates **zero-shot** on an unseen grid |
| Not used | E0's case14 checkpoint, which is grid-specific |
| Model | GNS_heterogeneous, hidden 48, 12 layers, 8 heads (paper `case118_eval.yaml` @ graphkit `genco-paper-repro` `95b90ee`) |
| Code | gridfm-graphkit `f104900` (0.9.0.3), gridfm-datakit 1.1.0 |
| Software | torch 2.11.0+cu126, torch-scatter 2.1.2, lightning 2.6.6, pandapower 3.5.5 |
| Hardware | 1 × GPU |
| Seeds | graphkit config seed 0; S0 datakit seeds 0, 1, 2 |
| Commit at evaluation | `6df2ae8` (+ working tree; final commit recorded in the cycle commit) |
| Inference | `python -m gridfm_graphkit predict`, unchanged CLI |

All scenarios are scored: the split files put every scenario in the test split.

**Normalizer.** The official zero-shot protocol fits a per-unit power base on the target data (`HeteroDataMVANormalizer`). Pre-registered, **one** base fitted on S0 (graphkit's own code) is reused for every family: 116.0 MVA. A per-family fit would differ wildly: S1's own base would be 24.5 MVA. That sensitivity is reported in [`e4_weather_generalisation.md`](e4_weather_generalisation.md) §5.

**Run-to-run spread:** a repeated S1 inference differs by 4 × 10⁻⁶ (relative) in family-mean PBE and by at most 0.19 MVA per scenario.

## 2. Reproduction of the paper's zero-shot number (IEEE 118, 9,952 scenarios)

| Metric | This repo | GENCO paper (`finetune_case118_0_eval`) | Relative difference |
|---|---|---|---|
| Avg. active residual (MW) | 11.0783 | 11.0783 | +1e-7 |
| Avg. reactive residual (MVAr) | 1.25505 | 1.25505 | +2e-6 |
| PBE Mean | 11.4440 | 11.4440 | +5e-7 |
| PBE Max | 197.39 | 197.44 | −3e-4 |

The same paper reports DC-PF at 2.30 MW on that set. **The paper's zero-shot model is itself worse than DC-PF on an unseen grid.** The Sundon result below is therefore consistent with the published behaviour, not an artefact of this pipeline.

## 3. Smoke test (Sundon)

| Check | Result |
|---|---|
| Graph loads | yes: 37 buses, 86 directed edges, 1 generator per scenario |
| Outputs finite | yes (all bus and branch columns) |
| Dimensions | consistent across all scenarios and families |
| GENCO targets equal the AC solution | |ΔVm| ≤ 6e-8 pu, |ΔPd| ≤ 3e-6 MW |
| AC references | converged and gated (§4) |
| Metrics computable | yes (`evaluation/genco_metrics.py`, graphkit residual definitions) |

## 4. S0_STANDARD_SYNTHETIC

The **official `pf_small` recipe** was applied unchanged: the case14 dataset's `args.log`.
- **Load:** `agg_load_profile` (default profile, σ 0.2, global range 0.4).
- **Admittance:** random perturbation, σ 0.2.
- **Topology:** random N-1 over branches and generators, 22 variants per load scenario.
- **Mode:** PF with DC results.

It ran on the E1 Sundon case (LTDS winter planning peak) with seeds 0, 1 and 2, at 43 load scenarios per seed.

| | Count |
|---|---|
| Requested (3 × 43 × 22) | 2,838 |
| Returned by datakit (PF converged) | 2,671 |
| Rejected by the AC gates | **374**, all `voltage_sanity` (Vm < 0.8 pu) |
| **Accepted** | **2,297**, in 129 load-scenario blocks |

- **Amendment A1** was logged before any Sundon inference. The E1 MATPOWER case carried the external grid with Qmin = Qmax = 0, which made datakit's dispatch OPF infeasible for every scenario. The slack now has ±270 MW/MVAr (3 × 90 MVA grid transformers) **in every family**.
- **S0 is a heavier operating regime than real Sundon.** Datakit scales the planning peak by 1.2–2.0× its feasible maximum, giving total load of 100–138 MW and median Vm 0.90 pu. Real 2024 states carry about 40–60 MW. Every S0 state is also an N-1 variant with perturbed admittances. S0 therefore measures **topology generalisation under conventional GridFM perturbations**, not Sundon's real operating distribution.

## 5. Zero-shot results

Means with 95% block-bootstrap CIs: blocks are load scenarios for S0 and days for S1.

| Family | n | PBE Mean (MVA) | Active residual (MW) | DC-PF active residual (MW) | GENCO/DC | Vm MAE (pu) | Va MAE (°) | Branch P MAE (MW) |
|---|---|---|---|---|---|---|---|---|
| **S0** standard synthetic | 2,297 | **45.3** [42.4, 48.2] | **33.7** [31.2, 36.2] | **0.225** [0.222, 0.228] | **149×** | 0.0373 | 7.10 | 29.3 |
| S1 real weather (for reference) | 2,829 | 49.0 [48.9, 49.1] | 28.9 [28.8, 29.0] | 0.098 [0.097, 0.099] | 296× | 0.0237 | 2.63 | 25.0 |

**Where the error is** (diagnosis on S1; the S0 pattern is the same):
- 67% of the per-bus PBE is on three 33 kV buses linked by branches with |Y_ft| up to 3.5 × 10⁵ pu (very short connections).
- Edge error correlates with log |Y| (r = 0.72).
- A uniform ~3° angle error across the 132/33 kV transformation becomes hundreds of MW of apparent flow on those branches.
- The REF-bus import is predicted at −211 ± 3 MW in every S1 state, against AC +49 ± 14 MW.
- Per-bus Vm correlation with AC: median 0.40 on S1 and −0.19 on S0.

**Operational detection:**
- Branch ratings are not in the GENCO graph; loadings use LTDS ratings.
- GENCO's implied loadings exceed 100% almost everywhere. On S1 that is 2,760 false-positive overload states out of 2,829, and all 69 true overloads are "detected" trivially.
- GENCO misses every AC voltage excursion outside ±6%: 0 of 417 on S1.
- **Neither detection is usable.**

## 6. Interpretation

The pretrained transfer model does not generalise to Sundon's topology:
- a 132/33/11 kV radial-meshed network;
- very short, near-zero-impedance 33 kV connections and tee junctions;
- a single slack supply.

This holds on conventional synthetic states before any weather is involved. **Any weather analysis on Sundon is therefore made on top of a topology failure** ([`e4_weather_generalisation.md`](e4_weather_generalisation.md)). The scientifically appropriate next step is **E5 topology-only adaptation**, followed by repeating E4. It has not been started.

## Attribution

UK Power Networks data (CC BY 4.0). GENCO checkpoints `gridfm/genco-pf-transfer` (Apache-2.0); Puech et al. (2026), arXiv:2608.09921. gridfm-datakit / gridfm-graphkit (Apache-2.0).

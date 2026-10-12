# E5d: checkpoint selection and freeze (synthetic only)

_12 October 2026. Written before any real state was opened. Rules: [`configs/experiments/e5d_selection.yaml`](../configs/experiments/e5d_selection.yaml) (pre-registered `17735ee`)._
- Registry: [`metadata/e5d_checkpoint_registry.yaml`](../metadata/e5d_checkpoint_registry.yaml).
- Evidence:
  - [`tables/e5d_seed_results.csv`](tables/e5d_seed_results.csv);
  - [`experiments/e5d/synthetic_evaluation.json`](experiments/e5d/synthetic_evaluation.json).

## Result

**No run satisfies all 23 pre-registered criteria.** The pre-registered fallback selects **`e5d_l1_s0`** (λ = 1, seed 0, best epoch 198 of 200). The selection is **FLAGGED**, and under the frozen verdict rules **E5D-A is therefore no longer reachable**, whatever the real-state result.

## Gate results (validation pairs for RS; E5c held-out test for ST/RT)

| Run | Passed | Static | PV resp. | Battery + load resp. | Retention | Failed criteria |
|---|---|---|---|---|---|---|
| E5c n10000 s0 | 3 | ✗ | ✗ | ✗ | ✗ | ST2–4, all RS, RT2–3 |
| E5c n10000 s1 | 8 | ✗ | ✗ | ✗ | ✓ | ST3–4, all pv RS, RS1/2/4 battery, all load RS |
| E5c n10000 s2 | 10 | ✗ | ✗ | ✗ | ✓ | ST3–4, all pv RS, RS1/2/4 battery, RS1/2/3 load |
| E5d λ0 s0 (control; not selectable) | 4 | ✗ | ✗ | ✗ | ✗ | ST2–4, all 15 RS, RT3 |
| E5d λ0.3 s0 | 19 | ✗ | ✓ | ✗ | ✓ | ST3, ST4, RS1 load (0.60), RS2 load (0.35) |
| **E5d λ1 s0** | **20** | ✗ | **✓** | **✓** | **✓** | **ST2 (0.672 vs 0.661 MW), ST3 (95.0 %), ST4 (14.2 MW)** |
| E5d λ1 s1 | 5 | ✗ | ✗ | ✗ | ✗ | ST2–5, RS3–5 pv/battery, all load RS, RT1–3 |
| E5d λ1 s2 | 12 | ✗ | ✗ | ✗ | ✗ | ST2–4, RS5 pv/battery, RS1/3/4/5 load, RT2–3 |
| E5d λ3 s0 | 15 | ✗ | ✓ | ✗ | ✗ | ST2–5, RS1/4 load, RT2–3 |

**Why each run is rejected:**
- **All runs:** ST3 and ST4 fail. No E5c or E5d model reaches ≥ 99 % import sign on |import| ≥ 5 MW, or ≤ 5 MW import MAE, on the broad E5c envelope.
- **ST2 (≤ 5 × DC-PF = 0.661 MW):** fails for every E5d run except λ0.3 (0.636 MW); E5c s1 and s2 pass it.
- **λ0.3:** misses the load response (slope ratio 0.60).
- **λ3:** misses load and retention.
- **λ1 s1 / s2:** fail distributed response and retention.

## Selection trace (pre-registered fallback, no new rule)

**Ranking keys:** lexicographic on (static pass, pv response pass, battery + load response pass, retention pass, number of criteria passed) descending, then E5c validation-pool PBE ascending. The λ = 0 control is excluded as pre-registered.

| Rank | Run | Static | PV | Batt + load | Retention | n | Val-pool PBE |
|---|---|---|---|---|---|---|---|
| 1 | **e5d_l1_s0** | ✗ | ✓ | ✓ | ✓ | 20 | 0.750 |
| 2 | e5d_l0.3_s0 | ✗ | ✓ | ✗ | ✓ | 19 | 0.723 |
| 3 | e5d_l3_s0 | ✗ | ✓ | ✗ | ✗ | 15 | 1.358 |
| 4 | e5d_l1_s2 | ✗ | ✗ | ✗ | ✗ | 12 | 1.457 |
| 5 | e5d_l1_s1 | ✗ | ✗ | ✗ | ✗ | 5 | 1.973 |

## Synthetic evidence for the selected checkpoint

| Quantity | E5d λ1 s0 | Frozen E5c (n10000 s2) |
|---|---|---|
| E5c test PBE / active residual (MVA / MW) | 0.795 / 0.672 | 0.614 / 0.528 |
| E5c validation-pool PBE | 0.750 | 0.584 |
| E5 / E5b re-encoded test PBE | 1.437 / 0.758 | 1.127 / 0.614 |
| Import MAE / sign ≥ 5 MW | 14.2 MW / 95.0 % | 13.6 MW / 93.6 % |
| Val. pairs: pv / battery / load import slope ratio | 0.997 / 0.997 / 0.948 | 0.014 / 0.731 / 0.626 |
| Val. pairs: pv import rel. error | 0.024 | 0.985 |
| Val. pairs: pv branch ΔP / ΔVm / ΔVa rel. error | 0.054 / 0.048 / 0.025 | 0.998 / 0.970 / 0.989 |
| Test pairs (held out): pv ratio / rel. error | 0.997 / 0.026 | 0.014 / 0.989 |

**SYN_PV_LEARNED** (selected run passes RS1 + RS2 for pv on the held-out test pairs): **true**. So E5D-C is excluded before any real state is seen. The remaining possible verdicts are B (if the real PV response fails R5) or D.

## Frozen artefacts

| Item | Value |
|---|---|
| Weights | `data/interim/e5d/checkpoints/e5d_l1_s0/best_model_state_dict.pt`, sha256 `45ab82525da0…7435` |
| Normalizer | own, fitted on its 10,000 E5c training states: baseMVA 36.741; sha256 `9ae23c469edd…5cec`, byte-identical to E5c n10000 s0's |
| Response scales σ | sha256 `6c87e81b28a0…59fd` (training pairs only; values in the registry) |
| Response-loss config | λ = 1, κ = 0.017519, Huber δ = 0.1, 8 pairs per type; graphkit config sha256 `fe52747b900e…216e` |
| Training | 200 epochs, best 198, 4.6 h on 1 GPU (shared with five other runs) |
| Configs, pair manifests, selection and response tables | sha256 in the registry |

The registry is committed before any real-state inference. `scripts/train_e5d.py predict` refuses S1 until the registry is frozen and the hashes match.

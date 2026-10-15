# Model card: Cloud2Grid E5c (`e5c_ft_n10000_s2`)

**What it is.** GENCO (GraphKit `GNS_heterogeneous`) fine-tuned on 10,000 synthetic AC power-flow states of the Sundon 33 kV network. It uses the generator-aware representation, with Leighton Buzzard generation as explicit generator nodes. It is the **frozen, selected E5c checkpoint**, kept as the **baseline** for E5d.

| | |
|---|---|
| Checkpoint sha256 | `31b824241880ffc6807f2dad478c34c5c211ee31c7f403092e586c6373ab4d8a` |
| Normaliser sha256 | `bb34d0b741d4715e1a4a9c133e291fbe1962237d1eaa4e855d7dc420c35d3f3e`. Use only with this checkpoint (baseMVA 36.722) |
| Selection | Pre-registered rule, synthetic validation only. **FLAGGED**: no run met every selection criterion, so the fallback rule chose it |
| Training | 200 epochs, best epoch 195. Pretrained init from `gridfm/genco-pf-transfer` (Apache-2.0). Recipe: lr 5e-4, batch 64, loss 0.1·physics + 0.9·masked MSE |
| Frozen record | `metadata/e5c_checkpoint_registry.yaml` in [hinox13/grid2cloud](https://github.com/hinox13/grid2cloud), tag `cloud2grid-submission-v1` |
| Formats | Original `torch.save` state_dict, unchanged (loads with `torch.load(weights_only=True)`) |
| Schema, licences | `IO_SCHEMA.md`, `LICENSE` (Apache-2.0), `NOTICE.md` |

## Verified results (synthetic; reproducible with `reproduce/verify_models.py`)

**E5c held-out test (2,804 states):**

| Metric | Value |
|---|---|
| PBE | 0.614 MVA |
| Active residual | 0.528 MW (DC-PF 0.132) |
| Vm error | 0.0121 pu |
| Import MAE | 13.6 MW |
| Import sign accuracy (\|AC\| ≥ 5 MW) | 93.6 % |

**Held-out E5d test pairs** (500 per type), GENCO response vs AC:

| | Import slope ratio | Import rel. error | Branch P | Vm | Va |
|---|---|---|---|---|---|
| **PV** | **0.014** | **0.989** | 1.00 | 0.97 | 0.99 |
| Battery | 0.724 | 0.276 | 0.49 | 0.59 | 0.47 |
| Load | 0.600 | 0.415 | 0.57 | 0.49 | 0.47 |

Relative error is Σ|Δpred − ΔAC| / Σ|ΔAC|; 0 is perfect, and 1 means no response.

**E5c is blind to PV.** It fits absolute states well, but a change in PV generation barely moves its predicted import, flows or voltages (1.4 % of the AC import response).

## Real-state results (not reproducible from this package)

On 2,829 real Sundon states from 2024 (UKPN measurements + satellite-derived PV), verdict **E5C-B**, generator-aware synthetic adaptation still insufficient:
- **State and import accuracy:** PBE 0.442 MVA, import MAE 7.74 MW (bias +7.7), import r 0.96.
- **PV response:** import responds to PV with slope **−0.04 MW/MW**, against −1.02 in AC.

These numbers depend on source data **not included** here (see the release notes).

## Licence and provenance

- **This package** (Cloud2Grid's fine-tuned weights, configuration, model card and schema): **Apache License 2.0**, see `LICENSE`. Copyright {{COPYRIGHT_HOLDER}}.
- **Base model:** fine-tuned from `gridfm/genco-pf-transfer` `pretraining/best_model_state_dict.pt` (sha256 `b2c9cf9b…5d41`, Apache-2.0; Puech et al. 2026, arXiv:2608.09921). **All of its weights were modified by fine-tuning;** the architecture is unchanged.
- **Training data:** synthetic states generated with gridfm-datakit (Apache-2.0) on a Sundon network model derived from UK Power Networks open data (CC BY 4.0). The attribution is in `NOTICE.md`.
- **Exact provenance:** `checkpoint_manifest.json` holds the file hashes, the frozen registry entry, the public source tag and the dependency versions.

## Reproducing the numbers

- **What can be reproduced:** `reproduce/verify_models.py` in [hinox13/grid2cloud](https://github.com/hinox13/grid2cloud) re-runs this checkpoint on the held-out synthetic verification set (release asset `cloud2grid-verification-synthetic-v1.tar.gz`). It recomputes every synthetic number in the "Verified results" section. **Independent numerical reproduction is synthetic-only:** the real-state numbers need data not in this release.
- **Numerical determinism:** GraphKit/PyG inference on GPU is not bit-for-bit deterministic (most likely the varying order of GPU scatter-add reductions; not isolated, and measured on one CUDA 12.6 GPU setup).
  - **How large the noise is:** two identical GPU runs differ by up to ~0.2 MW in decoded import and branch flows (mean ~0.03 MW); Vm and Va agree to ~1e-5. CPU inference is deterministic.
  - **Why:** the near-ideal branches of the network amplify float32 angle rounding into flows.
  - **Effect on the published numbers:** they come from one GPU run, so small response errors carry this noise.
  - **Tolerances:** the verifier's tolerances are set from it (`reproduce/README.md`). Claim thresholds are the pre-registered gates.

## Limitations

- **PV blindness:** the model does not respond to PV changes. Do not use it to assess PV impacts.
- **Generator-encoding issue:**
  - **Before E5c,** Leighton Buzzard generation reached GENCO as *negative load*. E5c made it an explicit generator.
  - **Still present:** GraphKit's internal physics decoder sets Pg = 0 at PQ buses, so the known generation at buses 8–10 is missing from the model's *internal* residual feedback (not from its inputs or evaluation).
  - **Found later:** this was found after freezing. Evaluation uses the correct generation, so the reported metrics are valid for the model as implemented; the effect of correcting it is not evaluated in this release.
- **One network:** Sundon 33 kV only; it does not transfer to other grids without retraining.
- **Synthetic training only:** no real data was used. The synthetic envelope comes from planning data (LTDS, ECR).
- **Absolute import error:** 13.6 MW MAE on synthetic test, and it fails the pre-registered ST3 / ST4 import gates.
- **Single selected seed;** the selection was flagged.
- **Research artefact, not validated for operational use.**

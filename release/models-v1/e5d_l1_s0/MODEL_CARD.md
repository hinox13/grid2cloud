# Model card: Cloud2Grid E5d (`e5d_l1_s0`)

**What it is.** GENCO (GraphKit `GNS_heterogeneous`) fine-tuned like E5c, plus a **paired-response loss**. Pairs of AC-solved states that differ in one input (PV, battery or load) teach the model the AC *change* in import, branch flows and voltages. λ = 1, seed 0. It is the **frozen, selected E5d checkpoint**: the final model in Cloud2Grid v1.1, shown alongside zero-shot, E5, E5b and E5c in its Explorer.

| | |
|---|---|
| Checkpoint sha256 | `45ab82525da00844a82a9526bc814de9290efc776159f0d8818703d5e9647435` |
| Normaliser sha256 | `9ae23c469edd4fe5cf894e2e02264d801013015fe5dcd170c7d35d18f69f5cec`. Use only with this checkpoint (baseMVA 36.741) |
| Response σ | `response_sigma.json` (sha256 `6c87e81b…59fd`): the training-time response-loss scale, provided for transparency and not needed for inference |
| Selection | Pre-registered rule, synthetic validation only. **FLAGGED**: no run passed all 23 criteria, so the fallback rule chose it. It passes all 15 response and 3 retention criteria |
| Training | 200 epochs, best epoch 198. Pretrained init from `gridfm/genco-pf-transfer` (Apache-2.0). Same data, splits, normaliser rule and recipe as E5c; loss = L_E5c + λ·κ·L_response |
| Frozen record | `metadata/e5d_checkpoint_registry.yaml` in [hinox13/grid2cloud](https://github.com/hinox13/grid2cloud), tag `cloud2grid-submission-v1` |
| Formats | Original `torch.save` state_dict, unchanged (loads with `torch.load(weights_only=True)`) |
| Schema, licences | `IO_SCHEMA.md`, `LICENSE` (Apache-2.0), `NOTICE.md` |

## Verified results (synthetic; reproducible with `reproduce/verify_models.py`)

**E5c held-out test (2,804 states):**

| Metric | Value |
|---|---|
| PBE | 0.795 MVA |
| Active residual | 0.672 MW |
| Vm error | 0.0125 pu |
| Import MAE | 14.2 MW |
| Import sign accuracy (\|AC\| ≥ 5 MW) | 95.0 % |

**Held-out E5d test pairs** (500 per type), GENCO response vs AC:

| | Import slope ratio | Import rel. error | Branch P | Vm | Va |
|---|---|---|---|---|---|
| **PV** | **0.997** | **0.026** | 0.057 | 0.049 | 0.026 |
| Battery | 0.998 | 0.010 | 0.18 | 0.26 | 0.28 |
| Load | 0.962 | 0.049 | 0.23 | 0.31 | 0.27 |

**E5d recovers the PV response.** The import ratio goes from 0.014 for E5c to 0.997, including small steps of 0.05–0.375 MW. The λ = 0 control trained with the same code stays blind (0.001), so the gain comes from the response loss.

## Real-state results (not reproducible from this package)

On 2,829 real Sundon states from 2024:
- **PV response:** import responds to satellite-derived PV with slope **−1.07 MW/MW**, against −1.02 in AC (E5c −0.04).
- **Load response:** slope ratio 0.99.
- **Import:** r 0.994.
- **Verdict E5D-D (partial / other):**
  - **Import offset:** a near-constant +13.1 MW offset (MAE 13.2 MW), R3 fails.
  - **Voltage:** Vm MAE 0.0109 pu against a 0.010 limit, R4 fails.
  - **Battery:** slope overshoots (ratio 1.17), R6 fails narrowly.

These numbers depend on source data **not included** here (see the release notes). The 2024 population was examined during development, so it is not an independent confirmation.

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

- **Partial transfer (E5D-D):** correct sensitivities, but the absolute import level carries a ~13 MW offset on real states. Synthetic import MAE is 14.2 MW; the ST3 / ST4 import gates fail.
- **Not seed-robust:** of three λ = 1 seeds, only this one learned the distributed (branch, voltage) response and the load response to gate level. The other seeds are much worse.
- **Generator-encoding issue (inherited from E5c):** GraphKit's internal physics decoder sets Pg = 0 at PQ buses, so the known LBUZ generation (buses 8–10) is missing from the model's *internal* residual feedback. It was found after freezing. Evaluation uses the correct generation, so the reported metrics are valid for the model as implemented; the effect of correcting it is not evaluated in this release.
- **One network, synthetic training only;** no real data was used for training or selection.
- **Research artefact, not validated for operational use.**

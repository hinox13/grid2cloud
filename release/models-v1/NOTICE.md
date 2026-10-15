# Notices: Cloud2Grid frozen models v1 (`cloud2grid-models-v1`)

## Licence of this package's own contribution

Copyright 2026 {{COPYRIGHT_HOLDER}}.

- **Model packages** (`cloud2grid-e5c-ft-n10000-s2`, `cloud2grid-e5d-l1-s0`: fine-tuned weights, configuration, model card, schema and manifest): **Apache License 2.0**, see `LICENSE`.
- **Verification dataset** (`cloud2grid-verification-synthetic-v1`): **Creative Commons Attribution 4.0 International (CC BY 4.0)**, see `LICENSE`. When you reuse it, credit "Cloud2Grid synthetic verification data v1" **and** the UK Power Networks attribution below, link the licence, and indicate any changes.

These licences cover only Cloud2Grid's contribution. They do not relicense the third-party material below, which keeps its own terms.

## Third-party material, and what was changed

| Material | Licence | Use here | Changes |
|---|---|---|---|
| GENCO transfer checkpoint, [`gridfm/genco-pf-transfer`](https://huggingface.co/gridfm/genco-pf-transfer), `pretraining/best_model_state_dict.pt` (sha256 `b2c9cf9b…5d41`). Puech et al. (2026), arXiv:2608.09921 | **Apache-2.0** (model card `license: apache-2.0`, re-checked 15 Oct 2026) | Initial weights for fine-tuning | **Modified:** all weights fine-tuned on Sundon synthetic data (E5c; E5d adds a response loss). Architecture unchanged |
| [gridfm-graphkit](https://github.com/gridfm/gridfm-graphkit) 0.9.0.3 | Apache-2.0 | Training, inference, model config | Not modified (used as a library) |
| [gridfm-datakit](https://github.com/gridfm/gridfm-datakit) 1.1.0 (Puech et al., 2025, arXiv:2512.14658) | Apache-2.0 | Generated the synthetic AC power-flow states | Not modified |
| pandapower (Thurner et al., 2018) | BSD-3-Clause | AC solutions of the paired states | Not modified |
| UK Power Networks open data (below) | **CC BY 4.0** (UKPN Open Data Portal catalogue, re-checked 15 Oct 2026) | Sundon network model (topology, impedances, ratings) and the planning bounds of the synthetic operating envelope | Network reconstructed, then synthetic states generated: **all data here are modified/derived** |

The base model, gridfm-graphkit and gridfm-datakit are Apache-2.0; the same licence text is in each model package's `LICENSE`.

**UK Power Networks attribution:**
- Contains UK Power Networks data (Long Term Development Statement Tables 1 Circuit data, 2a Transformer Data 2W, 2b Transformer Data 3W, 3a Observed Peak Demand, 5 Generation), licensed under CC BY 4.0.
- Contains UK Power Networks data (Grid and Primary Sites), licensed under CC BY 4.0. Contains data from Office for National Statistics licensed under the Open Government Licence v.3.0. Contains OS data © Crown copyright and database right [2019-].
- Contains UK Power Networks data (Embedded Capacity Register, 1 MW and above; under 1 MW), licensed under CC BY 4.0. Contains data from Office for National Statistics licensed under the Open Government Licence v.3.0. Contains OS data © Crown copyright and database right [2019-].
- **Licence:** https://creativecommons.org/licenses/by/4.0/

**Not included and not used in training:**
- **No raw third-party files.**
- **No real 2024 operating data.** UKPN half-hourly measurements are not used.
- **No satellite data.** EUMETSAT / LSA SAF products are not used.
- **Not used anywhere:** UKPN's LTDS Common Information Model, whose bespoke licence has not been reviewed.

# Datasheet: Cloud2Grid synthetic verification data v1

**Purpose.** To let anyone re-run the frozen E5c and E5d checkpoints on the **held-out synthetic data** used for their published results, and recompute the response and state metrics.

**Contents** (all synthetic, AC-solved, Sundon 33 kV, generator-aware GraphKit tables):

| Folder | What | Size |
|---|---|---|
| `e5d_test_pairs/` | The E5d **test** pair set: 1,500 pairs (500 each PV, battery, load), 3,000 states. `pairs.parquet` maps each pair (`probe_id`, `probe_type`, `magnitude_class`, `x_mw`) to its states A and B | held out from training, validation and selection |
| `e5c_test/` | The E5c held-out **test** pool: 2,804 states (scenarios 0–2803 of the E5c pool, unchanged ids) | held out from training and selection |
| `frozen_predictions/<run>/<set>/` | The frozen predictions of each model on each set, trimmed to the columns the metrics use, plus the weights hash they were made with | secondary cross-check |
| `MANIFEST.json` | sha256 of every file | |

**How the states were made.**
- **States:** gridfm-datakit 1.1.0 on the E1 Sundon planning case, with N-1 outages and admittance perturbations for the E5c pool.
- **Operating envelope:** loads, battery and generation within bounds from UKPN planning data (LTDS, ECR).
- **Pairs:** for the E5d pairs, each pair differs in exactly one controllable input.
- **Solver and filtering:** AC solutions by the datakit/pandapower pipeline; states failing the pre-registered AC sanity gates were dropped.

**Not included:**
- **No real measurements and no satellite data.**
- **Nothing used to train or select either model.**

**Licence.** **CC BY 4.0** (`LICENSE`), copyright 2026 {{COPYRIGHT_HOLDER}}.
- **Derived from** UK Power Networks open data (CC BY 4.0) using Apache-2.0 tools.
- **Credit when reusing:** credit Cloud2Grid **and** UK Power Networks as set out in `NOTICE.md`, link the licence, and indicate changes.
- **The frozen predictions** are outputs of the Apache-2.0 Cloud2Grid models and are included under the same CC BY 4.0 terms.

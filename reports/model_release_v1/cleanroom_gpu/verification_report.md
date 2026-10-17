# Cloud2Grid model verification (cloud2grid-models-v1)

Device: gpu. All checks pass: **True**. Total time 58.6 s.

| Claim | Criterion | Holds on fresh inference | Independently reproduced |
|---|---|---|---|
| C1 E5c is blind to PV: its import barely responds to a PV change | E5c pv import slope ratio < 0.1 and relative error > 0.9 | True | **True** |
| C2 E5d recovers the PV import response | E5d pv slope ratio in [0.8, 1.2] and relative error <= 0.25 (RS1, RS2) | True | **True** |
| C3 E5d reproduces the battery and load import responses | battery and load: slope ratio in [0.8, 1.2] and relative error <= 0.25 | True | **True** |
| C4 E5d reproduces the distributed response (branch P, Vm, Va) for PV, battery and load | relative error <= 0.5 for all nine (RS3–RS5) | True | **True** |
| C5 Both models keep an absolute import limitation on held-out synthetic states | import MAE > 5 MW (fails ST4) and sign accuracy on |AC| >= 5 MW < 0.99 (fails ST3), both models | True | **True** |

| Key metric | E5c published | E5c fresh | E5d published | E5d fresh |
|---|---|---|---|---|
| pv.import.slope_ratio | 0.0135 | 0.0137 | 0.9972 | 0.9975 |
| pv.import.rel_err | 0.9886 | 0.9869 | 0.0258 | 0.0269 |
| pv.branch_P.rel_err | 1.0001 | 1.0004 | 0.0568 | 0.0566 |
| pv.Vm.rel_err | 0.9718 | 0.9718 | 0.0486 | 0.0486 |
| pv.Va.rel_err | 0.9898 | 0.9897 | 0.0265 | 0.0265 |
| battery.import.slope_ratio | 0.7242 | 0.7243 | 0.9980 | 0.9979 |
| load.import.slope_ratio | 0.6002 | 0.6009 | 0.9621 | 0.9613 |
| import_mae_mw | 13.6050 | 13.6050 | 14.2136 | 14.2147 |
| import_sign_accuracy_big | 0.9357 | 0.9357 | 0.9496 | 0.9496 |
| PBE_mean | 0.6136 | 0.6138 | 0.7951 | 0.7951 |

**Not reproducible from this package:**
- Real 2024 Sundon results (e.g. PV → import slope AC −1.02, E5c −0.04, E5d −1.07 MW/MW; E5d +13 MW import offset; E5D-D transfer verdict): they require the real operating states (UKPN measurements + satellite-derived PV), which are not in this release.
- Training: this package verifies inference of frozen checkpoints; it does not retrain them.

# E5b: operating-state coverage (E5 vs E5b synthetic support vs real 2024 states)

_8 October 2026._
- The synthetic comparison was computed before the freeze.
- The real-state rows were computed **after** the recipe (`14ccda8`) and checkpoint (`e7c4abb`) were frozen. They are explanatory only, and nothing was changed afterwards.

To reproduce: `uv run python scripts/evaluate_e5b.py coverage`.

Outputs:
- [`tables/e5b_coverage_comparison.csv`](tables/e5b_coverage_comparison.csv)
- [`figures/e5b_coverage.png`](figures/e5b_coverage.png)
- [`experiments/e5b/coverage.json`](experiments/e5b/coverage.json)

## Answer

- **The E5b envelope covers operating modes that E5 never produced:** export to the grid, ±49.5 MW at the battery node, 33 kV generation export, and near-zero primary loads.
- **The real 2024 states lie almost entirely outside E5's pool and almost entirely inside E5b's.**

  | Variable | Real states inside E5's training range | Inside E5b's |
  |---|---|---|
  | Total net load | 0.1 % | 100 % |
  | Slack import | 0.1 % | 100 % |
  | CHAP31 | 0.6 % | 99.9 % |
  | Every primary load | ≤ 0.2 % | 99.6–100 % |
  | LBUZ generation | ≤ 0.4 % | 98.9–99.2 % |
  | Min / max bus Vm | 78 % / 0.2 % | 100 % / 94.9 % |

- **The pre-registered `coverage_achieved` flag is nevertheless FALSE** (rule: ≥ 95 % of S1 states inside the E5b training range on every variable). The two near-misses are:
  1. **Max bus Vm: 94.9 %.** Every E5b training state has some bus at ≥ 1.013 pu, while about 5 % of real states peak between 1.000 and 1.013 pu. The cause was not investigated, to avoid tuning on real data.
  2. **LBUZ nodes: 98.9–99.2 %.** These pass the threshold, but they miss full coverage only because the envelope draws solar and wind levels continuously and never produces *exactly* 0 MW. Real night states sit 0.04 MW outside the range. This quirk was noted before training and was not corrected, to keep the recipe frozen.

## Synthetic support (training pools)

| Variable | E5 pool min / median / max | E5b pool min / median / max | S1 (real) min / median / max |
|---|---|---|---|
| Total net load (MW) | 100.8 / 121.5 / 146.2 | −51.1 / 55.2 / 163.6 | −3.0 / 48.9 / 113.2 |
| Slack import (MW) | 101.9 / 123.6 / 149.1 | −51.0 / 55.6 / 165.5 | −2.7 / 49.2 / 114.0 |
| CHAP31 (MW) | 0 / 0 / 0 | −49.5 / 0.0 / 49.5 | −50.6 / 0.8 / 50.8 |
| PV / generation injection (MW) | 0 / 0 / 0 | 0.11 / 3.6 / 7.5 | 0 / 2.6 / 6.0 |
| CHAU51 (MW) | 22.7 / 30.2 / 38.3 | 0 / 12.6 / 27.8 | 7.2 / 14.2 / 20.1 |
| SURP5B (MW) | 4.1 / 5.4 / 6.9 | −0.43 / 5.0 / 11.7 | −0.81 / 2.3 / 4.97 |
| Min bus Vm (pu) | 0.800 / 0.905 / 0.957 | 0.800 / 0.960 / 0.993 | 0.904 / 0.950 / 0.979 |
| Max \|branch P\| (MW) | 35.6 / 47.8 / 87.6 | 0.7 / 31.2 / 95.2 | 9.1 / 17.3 / 50.8 |

**Not exactly covered:**
- S1's CHAP31 range (±50.6–50.8 MW) slightly exceeds the ECR 49.5 MW bound. E2's capacity-scaled meter interpretation makes this possible; 0.1 % of states fall outside.
- SURP5A/5B real minima (−0.71 / −0.81 MW) are slightly below the envelope's −0.43 MW (0.2–0.4 % of states).

**Joint check (reported):** the median nearest-neighbour distance from S1 states to the E5b pool, in standardised injections, is 0.89. The E5 pool's injection columns have zero variance, so its distance is undefined (it diverges). My pool-to-pool baseline drew from the pool itself and is therefore 0 by construction. A held-out-pool baseline would be the meaningful comparison and was not pre-registered.

## Attribution

UK Power Networks LTDS / ECR metadata and operational data (CC BY 4.0).

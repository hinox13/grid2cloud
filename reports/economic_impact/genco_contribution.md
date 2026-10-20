# What GENCO contributes to the economic estimate

**Question:** how accurately does each method reproduce the AC-based estimate of the import attributable to the plant and to clouds, and therefore its value? The models are frozen E5c and E5d; the reference is AC on the same states.

## Results (2,820 half-hours; APX prices)

Illustrative historical valuations, not savings, costs or forecasts. One valued half-hour, 2024-04-13 07:00 UTC (SP 17), has no APX price at source: its energy is counted, its value omitted (≤ £4.14). Contains BMRS data © Elexon Limited copyright and database right 2024.

| Method | PV-attributed value: error vs AC | Cloud-attributed value: error vs AC | Per-half-hour MAE of ΔI_pv (MW) | Per-half-hour MAE of ΔI_cloud (MW) |
|---|---:|---:|---:|---:|
| AC (reference; one solve per state, about 17 ms) | £234,226 | £93,286 | — | — |
| Injection accounting (lossless) | −£3,600 (**−1.54 %**) | −£1,404 (−1.50 %) | **0.040** | **0.02** |
| E5d (response-aware) | −£684 (**−0.29 %**) | +£60 (+0.06 %) | 0.05 | 0.04 |
| E5c (ordinary adaptation) | −£230,564 (**−98.4 %**) | −£91,807 (−98.4 %) | 2.82 | 1.22 |

The system-price scenario gives the same percentages (E5d −0.32 %, accounting −1.55 %, E5c −98.44 %).

**Diagnostic: valuing a model's absolute import directly** (the value of all imported energy):

| Model | Value | Error vs AC (£4.38 M) |
|---|---:|---:|
| E5c | £5.04 M | +£0.66 M |
| E5d | £5.55 M | **+£1.17 M (+27 %)** |

## What this shows

1. **Response-aware training turns an unusable economic estimate into a usable one.** A model with ordinary adaptation (E5c) attributes almost none of the plant's displaced import to it, so it misvalues it by 98 %. E5d is within 0.3 % over the season and 0.06 % for the cloud effect. This translates the main write-up's sensitivity result (PV slope −0.04 → −1.07) into money.
2. **Simple accounting is the right baseline, and E5d does not clearly beat it.**
   - Lossless accounting misses the loss reduction, a systematic −1.5 %.
   - E5d is closer over the season, partly because its per-half-hour errors cancel.
   - **Per half-hour, accounting is slightly more accurate than E5d.**
3. **Any analyst with the network model has the exact answer.** E5d needs the same network model and states. The AC reference itself, or loss-adjusted accounting, is the conventional calculation, and it is cheap on this 38-bus network. GENCO adds no information an analyst with the model lacks; its contribution is interpretive.
4. **Absolute GENCO outputs must not be used for money.** E5d's import bias (about +13 MW) becomes a +£1.17 M (+27 %) overstatement of the season's import value. Only predicted *changes*, anchored on a known state, are safe.

**Pre-registered classification: Outcome A.** The rule's conditions were met: E5d's season error is ≤ 50 % of E5c's, and smaller than lossless accounting's. Points 2–4 limit what Outcome A means in practice.

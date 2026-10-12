# E5b: ramp tracking and hero events — NOT EVALUATED (transfer criterion not met)

_8 October 2026._

**Pre-registered rule:** the E4-D ramp analysis is repeated only if REAL_TRANSFER_SUCCESS holds. That covers:
- the frozen E4 bins;
- the tracking ratio **and** the absolute ΔP, ΔVm and ΔVa transition errors;
- zero-shot vs E5 vs E5b;
- the heroes D01/B02, C01 and A02.

**Result:** REAL_TRANSFER_SUCCESS is false ([`e5b_real_transfer.md`](e5b_real_transfer.md)), so neither the ramp analysis nor the hero events were rerun.

**Indicator only (pre-registered import diagnostic, not a ramp result):** the slope of the frozen E5b model's predicted grid import on PV injection is −0.06 MW/MW, against −1.02 in AC. This suggests PV ramps would still be under-tracked at the network level.

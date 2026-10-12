# E5d: ramp tracking and hero events — NOT EVALUATED (transfer gate not met)

_12 October 2026._

**Pre-registered rule:** the frozen E4-D ramp analysis is repeated only on E5D-A. That covers:
- the E4 bins (low / medium / high / extreme);
- the tracking ratio **and** absolute ΔP, ΔVm and ΔVa transition errors;
- zero-shot, E5, E5b, E5c and E5d;
- the heroes D01/B02, C01 and A02.

**Result:** E5D-D ([`e5d_real_transfer.md`](e5d_real_transfer.md)). Neither the ramp analysis nor the hero events were rerun, and the Cloud2Grid Explorer bundles were not changed.

**Indicator only (half-hourly S1 regression, not a ramp result):**
- The frozen E5d model's import slope on PV injection is −1.07 MW/MW, against −1.02 in AC.
- Its median branch-level PV slope error is 0.014 MW/MW, against 0.074 for E5c.

This suggests PV ramps would now be tracked at network level. It is not tested here, and a tracking ratio would in any case need the absolute transition errors alongside it.

# E5b: weather generalisation — NOT EVALUATED (transfer criterion not met)

_8 October 2026._

**Pre-registered rule** ([`configs/experiments/e5b_adaptation.yaml`](../configs/experiments/e5b_adaptation.yaml) `weather_and_ramps`): the S1 − S2 weather-gap test is repeated **only if** REAL_TRANSFER_SUCCESS holds.

**Result:** REAL_TRANSFER_SUCCESS = false ([`e5b_real_transfer.md`](e5b_real_transfer.md)).
- Accuracy criteria R1 and R2 pass.
- Import tracking R3 and voltage tracking R4 fail.

**Consequences:**
- **Weather remains unresolved.** No new claim is made about S1 against S2.
- **The E4/E5 populations, donors and seeds stay untouched** for a future attempt.
- **Why a re-test now would be premature:** the frozen E5b model's predicted import is almost insensitive to PV injection (slope −0.06 MW/MW, against −1.02 in AC). A weather comparison now would mostly measure that insensitivity.

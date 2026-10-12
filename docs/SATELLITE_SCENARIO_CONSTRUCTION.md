# Satellite scenario construction (design note, before E4)

_2 October 2026. Design only: no weather scenario has been generated, and GENCO has not been run._

**Configuration:** [`configs/scenarios/sundon_weather_default.yaml`](../configs/scenarios/sundon_weather_default.yaml)

**Inputs:**
- [`reports/e3_pv_forcing.md`](../reports/e3_pv_forcing.md) for the PV model and historical capacity;
- [`reports/e2_operational_validation.md`](../reports/e2_operational_validation.md) for the baseline state.

## 1. Baseline definition

A Sundon baseline state **B(t)** is the E2 operating state at a historical timestamp *t* (half-hourly UKPN data), built with the recommended interpretation [`sundon_capacity_scaled_with_outages`](../configs/networks/sundon_capacity_scaled_with_outages.yaml). The preserved [`sundon_base_ltds`](../configs/networks/sundon_base_ltds.yaml) is run alongside it and reported.

| Element of B(t) | Source | Provenance class |
|---|---|---|
| Loads at the 11 kV primary busbars | observed primary-transformer active power (Sundon Primary, Leighton Buzzard); transformer current × assumed pf (Chaul End, Lewsey; A10) | OBSERVED / DERIVED |
| Battery customer (EPN:CHAP31) | `lne_SUND_CHAP` meter × 0.801 (capacity-scaled) | DERIVED |
| 33 kV-connected PV | **not represented** (E2 scenario V0: no unobserved injection) | — |
| Slack / import | Sundon 132/33 kV supply (balances the solution) | SIMULATED |
| Outages | observed-outage rule (historical timestamps only) | DERIVED |

The satellite slots are every 15 minutes and the UKPN data every 30 minutes. B(t) at :15 and :45 uses the preceding half-hour value (sample-and-hold, so no load interpolation is invented); README §14 calls for validation only at :00 and :30.

## 2. Two classes of PV, treated differently

The question for each asset is whether its historical output is already inside an observed quantity used to build B(t). The electrical link (E0 site FLOC) and the connection voltage decide it.

| Class | Assets (2024-active) | Where the real output appears | In B(t)? |
|---|---|---|---|
| **HV**: connected at 33 kV | ECR:955, 6 MW (Leighton Buzzard 33 kV busbars, E0 FLOC link) | Upstream of every primary-transformer meter. Only in 33 kV circuit flows and the import, which are validation targets, not inputs | **No** |
| **EMB**: connected at ≤11 kV | ECR:526, 2 MW (LBUZ 11 kV), plus 8 assets below 1 MW (0.945 MW) at LBUZ/CHAU/LEWS | Inside the observed primary-transformer flows: the loads are **net** of this PV | **Yes**, implicitly |

## 3. Construction rules (no double counting)

The sign convention follows pandapower:
- `sgen.p_mw ≥ 0` is an injection into its bus;
- `load.p_mw ≥ 0` is consumption;
- the PV perturbation ΔP = P_sat(e) − P_sat(t₀) reduces net demand when positive.

The two families below are named per README §17. They differ in which timestamp supplies the base state (t₀) and which supplies the weather (e).

**S1-sync: synchronous replay (t₀ = e, default)**

1. Take B(e).
2. **HV:** add one `sgen` per HV asset, with P = P_sat(asset, e), split equally over its E0 node set (LBUZ31/32/33; ASSUMED). This is the only new injection.
3. **EMB:** inject nothing. Their real output is already in the observed loads. Adding P_sat would count it twice.
   - P_sat(EMB, e) is still computed and stored, for reporting and the E4 sanity check.
   - Optional explicit representation: replace L(e) by L(e) + P_emb_sat(e) and add `sgen` P_emb_sat(e). Net injection at the node is unchanged by construction.

**S1-transplant: weather from event e on the base state of t₀ (t₀ ≠ e)**

1. Take B(t₀).
2. **HV:** `sgen` P = P_sat(asset, e). There is nothing to remove, because B(t₀) has no HV PV.
3. **EMB:** gross up, then replace, per load node *n*:
   **L(n) = L_obs(n, t₀) + Σ P_sat,EMB(n, t₀) − Σ P_sat,EMB(n, e)**
   This needs satellite data at t₀ too, so t₀ must be a slot with usable MDSSFTD at the EMB assets; otherwise the case is rejected.
4. Active capacity is evaluated **at e** for the injected terms and **at t₀** for the gross-up term (`solar.capacity.active_capacity`).

**Weather-free reference:** B(t) itself (unchanged E2 state). GENCO error on S1 is compared against this, never against a PV-tuned state.

## 4. Active historical capacity

Only capacity connected at the scenario time is used (`solar.capacity`). In the 2024 search period this is:
- **HV:** 6.0 MW;
- **EMB:** 2.945 MW;
- **total:** 8.945 MW.

The 15 MW farm (connected 25 Feb 2026) is `NOT_YET_CONNECTED`. The 20 MW farm (undated) is `EXCLUDED_BY_EVIDENCE`: LTDS Table 5, published 29 May 2026, lists 21.0 MW of connected 33 kV PV at Sundon, which equals 15 + 6 MW exactly. Any 2026-dated scenario must re-evaluate both.

A **future-fleet** scenario family (today's 43.9 MW on a 2024 base state) would be a counterfactual. It must be labelled as such and kept separate from historical replays.

## 5. Load assumptions and their effect

- **Sample-and-hold to 15 minutes** (§1). Cloud-driven PV changes within the half-hour are not reflected in the loads; for HV assets this is irrelevant (§2).
- **Current-derived loads** (Chaul End, Lewsey) carry the A10 pf assumption. Their sign is assumed to be import. The EMB PV there is below 1 MW in total, so a sign error cannot occur from PV alone.
- **Q of the PV sgen:** unity power factor (ASSUMED). Most GB PV runs at or near unity unless instructed.
- **Flexible (ANM) connections:** curtailment is not modelled. The HV asset active in 2024 is not flexible; the 20 MW farm that is flexible is not active in 2024.
- **Battery:** held at its observed (scaled) value. Weather does not move it.

## 6. Checks required before E4 results are used

1. **Sanity, not calibration.** On 2024 timestamps, compare P_sat(HV) with E2's import residual (observed − simulated, V0). E2 found only about −1.2 MW of midday signature (May–Aug, battery idle), against a 6 MW nominal HV asset. This must be reported. It must **not** be used to tune the PV model or to rescale P_sat.
2. **Energy balance.** In every scenario, Σ sgen + Σ load changes equals the slack change ± losses (AC PF residual check, as in E1).
3. **Node attribution sensitivity.** Rerun HV injection with the LTDS T5 alternative (EPN:SUND31, where LTDS lists the PV) and report the difference. The E0 link remains the default.
4. **Quality propagation.** A slot whose P_sat is NaN for any active asset (status INVALID/MISSING) is not converted into a scenario. It is never filled with zero.

## 7. What this does not do

There is no GENCO run, no shuffled controls (S2/S3), no Canterbury South network, and no event bundles. These are E4 and later.

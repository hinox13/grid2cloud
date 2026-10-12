# E1: Sundon 33 kV network reconstruction

_2 October 2026. Region selected post-audit (`selection.mode: post_audit_manual`); see [`e0_data_audit.md` §6a](e0_data_audit.md)._

To reproduce:

```bash
uv run --env-file .env python scripts/audit_ukpn.py --write-study-region      # freeze region
uv run --env-file .env python scripts/download_region_timeseries.py           # Sundon series only
uv run --env-file .env python scripts/build_network.py                        # this report's outputs
```

Machine-readable outputs:

- [`experiments/e1_network/summary.json`](experiments/e1_network/summary.json)
- [`structural_validation.json`](experiments/e1_network/structural_validation.json)
- [`network.json`](experiments/e1_network/network.json) (the pandapower network)
- [`tables/e1_parameter_provenance.csv`](tables/e1_parameter_provenance.csv)
- [`tables/e1_sanity_cases.csv`](tables/e1_sanity_cases.csv)
- [`tables/e1_solar_geometry.csv`](tables/e1_solar_geometry.csv)
- [`tables/e1_measurement_series.csv`](tables/e1_measurement_series.csv)

## Summary

**Sundon can be represented as one coherent 132/33/11 kV network built entirely from published UKPN identifiers and parameters.** Every structural check passes, and AC power flow converges in every case tried. Two independent solvers agree: pandapower, and gridfm-datakit's own PowerModels AC PF from a flat start. The network exports to a valid OpenGridFM dataset that gridfm-graphkit loads.

## 1. Study region and data retrieved

`configs/networks/study_region.yaml` freezes the selection, generated from identifiers only:

- **E0 region (exact):** 28 nodes and 29 branches (26 circuits and 3 grid transformers).
- **Model extension, by two deterministic rules:**
  - the three 132 kV GIS connections and the Sundon 132 kV busbars;
  - the 12 LTDS T2a transformers whose HV node is a region 33 kV node, plus their 11 kV busbars.
- **Total:** 38 nodes, 44 branches and 6 sites. 40 ECR assets are attached through identifiers, with no proximity matching.
- **Measurement series linked by LTDS identifiers:**
  - 16 circuits;
  - 3 grid transformers;
  - 12 primary transformers.

New sources were registered through the licence gate, all CC BY 4.0 and verified by catalogue API:

- grid and primary transformer **monthly** indexes, which link each `tx_id` to LTDS `hv_ltds_node`/`lv_ltds_node`;
- grid and primary transformer **half-hourly** series;
- LTDS Table 3a (demand, power factor);
- LTDS Table 5 (generation).

**Selective download.** Only Sundon's series were retrieved, using a server-side `where ltds_line_name in (…)` / `where tx_id in (…)` filter. That came to 1.38 M rows out of more than 140 M across the source datasets:

| Source | Rows |
|---|---|
| 33 kV EPN circuits | 579 k |
| 132 kV GIS circuits | 162 k |
| grid transformers | 140 k |
| primary transformers | 497 k |

Every extract has a hash and its filter recorded in `metadata/provenance.json`.

| Series class | Series |
|---|---|
| active power (P-capable) | 12 × 33 kV circuits, 3 × 132 kV GIS circuits, GT1–3, LBUZ T1–T3, Sundon Primary T1/T2 |
| current only | `SU33_SU11_2`; Chaul End T1–T3; Lewsey T1–T2 |
| no data | Sundon Primary T3/T4 (requested, absent from the dataset) |

**Identifier issues found and handled explicitly (none silently patched):**

- LTDS writes the Sundon Primary T1/T2 LV nodes as `SURP5A/5B`, while the transformer index writes `SUPR5A/5B`. These were linked by the unique HV node and flagged `lv_node_in_model: false`.
- The monthly index puts `SU33_SU11_4` at node `SUND30`, which doesn't exist in LTDS (LTDS says SUND31). It was linked by LTDS name and flagged `node_match: false`.
- The metered `SU33_LBUZT_2_(1)` (SUND31→MRFM3C) has no single LTDS record. It covers LTDS sections `_(5)` and `_(6)`, and was mapped by node path with the meter assumed at SUND31.

## 2. Reconstructed network

| | Count |
|---|---|
| Buses | **38** (132 kV: 5 · 33 kV: 25 · 11 kV: 8); IDs are licence-area-scoped (`EPN:SUND31`) |
| Lines | **29** (26 × 33 kV, 3 × 132 kV GIS connections) |
| Transformers | **15** (3 × 132/33 kV 90 MVA; 12 × 33/11 kV primary) |
| 3-winding transformers | 0 (none in LTDS T2b for this region) |
| Bus couplers | 1 (SUND11–SUND12, ASSUMED closed) |
| External grid | 1, at the Sundon GIS 132 kV busbar |
| Connected components | **1** |
| Load nodes | 9 (8 primary 11 kV busbars + customer node CHAP31) |

Figure: [`figures/e1_topology.png`](figures/e1_topology.png). Panel (a) is the full electrical schematic; its layout is **not** geographic. Panel (b) plots only the geolocated nodes at their real coordinates.

**Model boundary.** The external grid is the **Sundon GIS 132 kV busbar** (assumption A05). Sundon is itself the Grid Supply Point, so this busbar is the transmission/distribution boundary through which all Sundon 33 kV demand is supplied. Outside the model:

- NGET's 400/132 kV supergrid transformers;
- the other 132 kV circuits leaving Sundon;
- every 11 kV network below the primaries, represented by the observed transformer flows.

The busbar voltage is set to |V| = 1.00 pu, an ASSUMED value because the set-point isn't published.

## 3. Parameter provenance

Totals: **229 PUBLISHED · 117 DERIVED · 47 ASSUMED · 9 MISSING.** The per-element table is [`tables/e1_parameter_provenance.csv`](tables/e1_parameter_provenance.csv), and the conventions are in [`metadata/network_assumptions.yaml`](../metadata/network_assumptions.yaml).

| Element | PUBLISHED | DERIVED | ASSUMED | MISSING |
|---|---|---|---|---|
| bus (nominal kV, geodata) | 67 | 0 | 0 | 9 (geodata of unlocated junctions) |
| line (R/X/C, length, ratings) | 87 | 87 | 0 | 0 |
| transformer (ratings, voltages, taps, R/X) | 75 | 30 | 45 (tap position, magnetising branch, phase shift × 15) | 0 |
| bus coupler | 0 | 0 | 1 | 0 |
| external grid | 0 | 0 | 1 | 0 |

**No electrical parameter is missing.** The builder never fills a gap: a branch with missing R/X/rating would be left out, recorded as MISSING, and the structural check `all_region_branches_built` would fail. A test enforces this.

The most consequential assumption is **A01**: LTDS percentages are taken to be on a **100 MVA base**. That isn't stated by UKPN. The supporting evidence:

- 33 kV circuits come out at R, X ≈ 0.04–0.17 Ω/km and C ≈ 60–700 nF/km, which are typical cable values.
- Transformers come out at 17–24% reactance on their own rating. On an own-rating base, the primaries would have about 94% reactance, which is not physical.
- E2's parallel-path flow sharing, which depends on impedance ratios, reproduces the measurements.

Other conventions:

- A02: neutral taps.
- A03: no magnetising branch.
- A04: zero phase shift (parallel units share vector groups).
- A06: coupler closed.
- A07/A10: load reactive power from LTDS 3a power factors.

Each has its reason and sensitivity risk recorded.

## 4. Structural validation

All checks pass; see [`structural_validation.json`](experiments/e1_network/structural_validation.json). They cover:

- unique scoped bus IDs;
- every region branch built;
- line and transformer endpoints valid;
- line voltage consistency;
- transformer rated voltages within ±6% of bus nominal (off-nominal LV ratios such as 33/11.5 kV are published and kept);
- finite, positive R/X/ratings, with vkr < vk;
- one connected component and no isolated buses;
- every transformer connected to the slack;
- Y-bus finite (37×37 after the coupler fuses SUND11/12) with symmetric off-diagonals.

Reported for information:

- **Duplicate-looking LTDS records:** `SU33_LBUZT_1_(3A)` and `(3B)` share the same node pair and identical R/X/B, rating and length. They are modelled as published (two parallel sections). This may be a duplicated record; flow through this radial path is unaffected.
- **Leaf buses:** the customer/tee nodes CHAP31, GFSF31 and MFES31, plus the primary 11 kV busbars.

## 5. Load reconstruction (for E2 states)

The strongest available method uses **observed transformer flows at each primary 11 kV busbar**, summed per busbar. The model therefore has to predict how flow splits across parallel 33 kV circuits and grid transformers; that split is never given to it.

| Load node | Method | Class |
|---|---|---|
| LBUZ51 (T1+T2), LBUZ5A (T3) | transformer active power | OBSERVED |
| SURP5B (T1), SURP5A (T2) | transformer active power | OBSERVED |
| CHAU51 (T1+T2), CHAU52 (T3), LEWS51 (T1+T2) | transformer current × √3 × 11 kV × pf (A10) | DERIVED |
| SUPR52 (T3/T4, unpublished) | feeder circuits SU33_SU11_3 − SU33_SU11_4 | DERIVED from observed circuits (these circuits are inputs, never validation targets) |
| CHAP31 (customer on `lne_SUND_CHAP`) | metered circuit | OBSERVED |
| Unobserved 33 kV customers (tee nodes) | V0: 0 (primary scenario); V1: residual (diagnostic) | MISSING / DERIVED |

Q comes from P × tan(acos(pf)), using the LTDS 3a site power factor for the season (A07/A08).

**Sign conventions were derived from data, not assumed.** Each transformer's published convention was checked against an independently metered circuit on the same path:

- GT1–3: r = 0.97–0.98 against the GIS circuits;
- LBUZ T1–T3: |r| = 0.86–0.96;
- Sundon T1: r = 0.75;
- Sundon T2: same as T1 (ASSUMED; r = 0.94 between T1 and T2).

The conventions **differ between series**: GT and LBUZ report LV→HV as positive, while Sundon Primary reports HV→LV. The build aborts if any declared sign disagrees with its evidence.

## 6. AC power-flow sanity cases

| Case | Converged | Import | Demand | Losses | Balance residual | V range | Max line loading | Max transformer |
|---|---|---|---|---|---|---|---|---|
| LTDS 3a winter planning peak (customers = 0) | yes | 90.29 MW | 89.30 MW | 0.99 MW | 0.0 | 0.917–1.001 pu | 92% (`Lne_NESD_T1`, GT1 33 kV connection) | 79% |
| Observed state 2023-12-05 23:30 (median import) | yes | 53.81 MW (observed **54.52**) | 53.48 | 0.33 | 0.0 | 0.962–1.023 pu | 53% | 56% |

- **Signs.** External-grid P > 0 means import, the pandapower generator convention. Losses are positive, and power balance closes to numerical precision.
- **Low 11 kV voltage at the planning peak (0.917 pu)** is a consequence of A02. Real AVC and tap changers would raise it, so it is reported, not tuned away.
- **A planning-data inconsistency.** The sum of LTDS 3a primary peaks is 89.3 MW, while LTDS gives the Sundon 33 kV BSP itself a winter maximum demand of 127.1 MW. The 33 kV-connected customer (CHAP31, battery-like ±64 MW) is the likely reason.

## 7. Geography

29 of 38 nodes are geolocated, through site FLOC → Grid/Primary Site coordinates. **The 9 unresolved nodes keep `geolocation_status: unresolved` with no coordinates:**

- the tee junctions LBUZ3C, LBUZ3D, GFSF3A, MRFM3A/B/C;
- the customer nodes CHAP31, GFSF31, MFES31.

The 29 located nodes sit at only **5 distinct sites**, because each substation's 132/33/11 kV busbars share one location. That is enough for a schematic map. It is **not** a geographic drawing of the 33 kV routes: 11 branches touching unlocated nodes are not drawn in the geographic panel.

## 8. Solar spatial-diversity diagnostic (geometry only, no weather data)

Figure: [`figures/e1_solar_geometry.png`](figures/e1_solar_geometry.png).

| | Value |
|---|---|
| Connected solar (ECR, identifier-attributed) | 12 assets, **43.9 MW** |
| Assets carrying ≥95% of capacity | **4 farms = 43.0 MW (97.9%)**: 20, 15, 6 and 2 MW |
| Pairwise distances | 1.09–5.34 km (20↔6 MW: 1.1 km; 15↔2 MW: 5.3 km) |
| Bounding box / extent | 51.919–51.951 N, 0.621–0.564 W; ≈ 3.9 km E–W × 3.6 km N–S |
| Accepted, not yet connected | 75.1 MW (not modelled) |

**Preliminary H2 view: weak but not zero.**

- The four farms fit inside about 4 × 4 km, roughly one to two LSA SAF pixels (nominally 3 km, larger at 52°N). Satellite-derived irradiance at 15 min / 3 km will therefore usually force them almost identically.
- Only the 15 MW farm, about 3–5 km from the others, is likely to be resolved separately.
- Moving cloud edges could still produce staggered ramps at sub-pixel scale, but the 15-minute product cannot resolve that.
- Decisive for H2: **E2 shows the 33 kV PV leaves only a small trace in the observed import** (§6 of the E2 report).

No final H2 decision is made here.

## 9. OpenGridFM compatibility

**Successful**, using gridfm-datakit's own code end to end:

1. pandapower → MATPOWER `.m` (datakit `Network.to_mpc`).
2. `load_net_from_file`, including PowerModels normalisation.
3. **datakit `run_pf`**: PowerModels AC PF from a **flat start**.
4. `pf_post_processing` → `save_node_edge_data`.

Two scenarios were exported (planning peak; observed state) to `data/processed/opengridfm/sundon_33kv/` (gitignored, regenerable).

| Check | Result |
|---|---|
| datakit PF vs pandapower | max \|ΔV\| 9e-9 pu, max \|Δθ\| 5e-7°, max \|ΔP\| on any branch 7e-7 MW (branches matched by identity, because PowerModels reorders and reorients branches) |
| AC power balance recomputed from exported `bus_data` + `y_bus_data` | ≤ 1.3e-6 MW, ≤ 9e-7 MVAr |
| gridfm-graphkit `HeteroGridDatasetDisk` + `HeteroDataPerSampleMVANormalizer` | processes and loads both scenarios: 37 bus nodes, 1 gen node, 88 directed bus edges, 15 bus features, all finite |

Notes:

- The SUND11/SUND12 coupler is fused into one bus in the export.
- There is exactly one generator (the slack). Embedded generation appears only through net demand.
- Generator costs are zero (OPF is not meaningful for this export).
- MATPOWER `VMIN`/`VMAX` are written as 0.9/1.1 (ASSUMED; unused by PF).
- datakit's Julia backend needs `PYTHON_JULIAPKG_EXE` pointing at a real Julia binary (see `.env.example`). The system `/usr/local/bin/julia` symlink breaks juliacall.
- No GENCO inference or training was run.

## 10. Limitations

1. **Planning topology.** Switch states are not published. E2 found operational departures; see the E2 report §5.
2. **A01 base assumption.** Supported by plausibility checks and by E2 flow sharing, but not by a UKPN statement.
3. **Taps (A02).** Voltages are indicative only.
4. **Unresolved customer connections.** The tee customers GFSF31/MFES31 have no identifier link to specific ECR assets.
5. **Battery attribution conflict.** ECR site FLOC places the battery and PV at Leighton Buzzard. LTDS Table 5 places them at Sundon 33 kV. Operational data indicate the battery is on `lne_SUND_CHAP`. None of these is resolvable from identifiers alone.

## Attribution

Contains UK Power Networks data licensed under CC BY 4.0. The datasets used are LTDS Tables 1, 2a, 3a and 5; Grid and Primary Sites; the Embedded Capacity Registers; the 132 kV and 33 kV (EPN) circuit operational data; and the grid and primary transformer power-flow data.

Site coordinates contain Ordnance Survey data © Crown copyright and database right [2019-], and Office for National Statistics data under the Open Government Licence v3.0.

Derived tables in `reports/` contain no customer-identifying ECR fields.

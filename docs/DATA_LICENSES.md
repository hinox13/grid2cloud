# Data and software licences

Status as of **2 October 2026** (E0-L licence audit, Phase 0; updated for the E1 sources and the E3 satellite products).

The source of truth is machine-readable:

- [`metadata/data_sources.yaml`](../metadata/data_sources.yaml): one entry per source, giving the licence, the evidence for it, flags and attribution text.
- [`metadata/licence_manifest.yaml`](../metadata/licence_manifest.yaml): what each licence permits.
- [`src/cloud2grid/licensing/`](../src/cloud2grid/licensing/): the **fail-closed licence gate**. It rejects sources that are unregistered or `UNVERIFIED`, sources whose licence is not in the manifest, uses the licence or source flags do not allow, and sources with no stored attribution.

Re-run the audit (adds a live re-check of provider-declared licences where machine-readable):

```bash
uv run python scripts/audit_licences.py --check-remote
```

## Rules

1. **No dataset enters the pipeline until its licence is verified** (README §6). A licence counts as verified only when it was read from the provider's own declaration: a licence file, the dataset information tab or API metadata, or the provider's data policy page. The date and the exact evidence are recorded in `licence_evidence`.
2. **Values are never guessed.** If the authoritative source does not state a licence clearly, the entry is `licence: UNVERIFIED` with `licence_verified: null`, and the gate blocks every use.
3. **UKPN licences are dataset-specific.** Each UKPN dataset was checked individually through the Opendatasoft catalogue API (`metas.default.license`, the same field as the dataset's Information tab). One LTDS product (`ukpn-ltds-cim`) is under a different, bespoke licence. See below.
4. **Raw third-party data is never committed** (README §40). `data/raw/`, `data/interim/` and `data/processed/` are gitignored. Provenance (URL, revision, timestamp, licence, size, SHA-256) is committed in [`metadata/provenance.json`](../metadata/provenance.json). The one exception is `data/demo/`: the Explorer's derived, cropped and re-encoded bundles are committed so the app can be deployed. They are built only from sources that pass the licence gate for `redistribute_derived` (decisions in `data/demo/attribution.json`) and contain no raw files or model weights.
5. **Do not use the UKPN logo** without permission (README §1).
6. **The project's own licences do not cover third-party material.** Cloud2Grid source code and released model weights are Apache-2.0 and the synthetic verification dataset is CC BY 4.0 (see [`LICENSE`](../LICENSE) and [`NOTICE`](../NOTICE)); these apply to Cloud2Grid's own contribution only. The datasets, imagery, checkpoints and derived assets listed here stay under their own licences.

## Verified

| Source ID | Provider / identifier | Licence | Evidence |
|---|---|---|---|
| `genco_paper` | arXiv:2608.09921 | CC-BY-4.0 | The arXiv abstract page links CC BY 4.0 |
| `gridfm_datakit` | github.com/gridfm/gridfm-datakit | Apache-2.0 | LICENSE file, pyproject, GitHub API |
| `gridfm_graphkit` | github.com/gridfm/gridfm-graphkit @ `f104900` | Apache-2.0 | LICENSE file, GitHub API |
| `genco_pf_datakit_checkpoints`* | HF `gridfm/genco-pf-datakit` @ `7014f14` | Apache-2.0 | Model card `license: apache-2.0` |
| `opengridfm_pf_small_case14_ieee`* | HF `gridfm/pf_small_case14_ieee` @ `5669b8c` | Apache-2.0 | Dataset card `license: apache-2.0` |
| `lsa_saf_mdssftd` | LSA SAF MDSSFTD / LSA-207 | CC-BY-4.0 | LSA SAF data-usage policy page; EUMETSAT Data Policy (amended 2025-01-01) Annex I: SAF Derived Products are "Core" |
| `eumetsat_eview` | EO:EUM:DAT:MSG:EVIEW (E-View / European HRV RGB) | CC-BY-4.0 | EUMETSAT Data Policy (amended 2025-01-01): Annex I "All SEVIRI … Advanced Image Products" = Core; Annex II RGB definition; Art. 5.1 (CC-BY-4.0), 6.1 (redistribution), 6.3 (attribution). Verified in E3 prep |
| `eumetsat_ncl_enh` | EO:EUM:DAT:MSG:NCL_ENH (Natural Colour Enhanced RGB) | CC-BY-4.0 | Same basis as E-View. Verified in E3 prep |
| `genco_pf_transfer_checkpoints` | gridfm/genco-pf-transfer (subgrid-pretrained GENCO; IEEE 118 eval set) | Apache-2.0 | Model card front matter (Hub API cardData, rev e7a98e9). Used zero-shot in E4 |
| `lsa_saf_msg_static` | LSA SAF MSG static grid (lat/lon, land/water mask) | CC-BY-4.0 | LSA SAF data-service README licence statement for its products; EUMETSAT Data Policy Annex I/II (SAF products = Core). Used for geometry verification only |
| `ukpn_grid_and_primary_sites` | `grid-and-primary-sites` | CC-BY-4.0 (+ ONS OGL v3, OS ©) | ODS API licence field; attribution field |
| `ukpn_ltds_table_1_circuit_data` | `ukpn-ltds-table-1-circuit-data` | CC-BY-4.0 | ODS API licence field |
| `ukpn_ltds_table_2a_transformer_2w` | `ukpn-ltds-table-2a-transformer-2w` | CC-BY-4.0 | ODS API licence field |
| `ukpn_ltds_table_2b_transformer_3w` | `ukpn-ltds-table-2b-transformer-data-3w` | CC-BY-4.0 | ODS API licence field |
| `ukpn_ecr_1mw_and_above` | `ukpn-embedded-capacity-register` | CC-BY-4.0 (+ ONS OGL v3, OS ©) | ODS API licence field; attribution field |
| `ukpn_ecr_under_1mw` | `ukpn-embedded-capacity-register-1-under-1mw` | CC-BY-4.0 | ODS API licence field |
| `ukpn_132kv_operational_half_hourly` | `ukpn-132kv-circuit-operational-data-half-hourly` | CC-BY-4.0 | ODS API licence field; open-data.org.uk index |
| `ukpn_132kv_operational_monthly`* | `ukpn-132kv-circuit-operational-data-monthly` | CC-BY-4.0 | ODS API licence field |
| `ukpn_33kv_operational_half_hourly_spn` | `ukpn-33kv-circuit-operational-data-half-hourly-spn` | CC-BY-4.0 | ODS API licence field |
| `ukpn_33kv_operational_half_hourly_epn`* | `ukpn-33kv-circuit-operational-data-half-hourly-epn` | CC-BY-4.0 | ODS API licence field (registered in E0-D) |
| `ukpn_33kv_operational_monthly`* | `ukpn-33kv-circuit-operational-data-monthly` | CC-BY-4.0 | ODS API licence field |
| `ukpn_grid_transformer_monthly`* | `ukpn-grid-transformer-operational-data-monthly` | CC-BY-4.0 | ODS API licence field (registered in E1) |
| `ukpn_grid_transformer_half_hourly`* | `ukpn-grid-transformer-operational-data-half-hourly` (region extract only) | CC-BY-4.0 | ODS API licence field (registered in E1) |
| `ukpn_primary_transformer_monthly`* | `ukpn-primary-transformer-power-flow-historic-monthly` | CC-BY-4.0 | ODS API licence field (registered in E1) |
| `ukpn_primary_transformer_half_hourly_epn`* | `ukpn-primary-transformer-power-flow-historic-half-hourly-epn` (region extract only) | CC-BY-4.0 | ODS API licence field (registered in E1) |
| `ukpn_ltds_table_3a_observed_demand`* | `ukpn-ltds-table-3a-load-data-observed` | CC-BY-4.0 | ODS API licence field (registered in E1) |
| `ukpn_ltds_table_5_generation`* | `ukpn-ltds-table-5-generation` | CC-BY-4.0 | ODS API licence field (registered in E1) |
| `pvlib` | pvlib/pvlib-python | BSD-3-Clause | GitHub API |
| `pandapower` | e2nIEE/pandapower | BSD-3-Clause | LICENSE text (GitHub API says NOASSERTION because of the multi-holder header) |
| `elexon_bmrs_market_index`* | Elexon Insights Market Index Data (APXMIDP) | Elexon BMRS data licence | Elexon "Licence to use BMRS open data" page (registered for the Cloud Impact page) |
| `elexon_bmrs_system_prices`* | Elexon Insights system prices | Elexon BMRS data licence | Same licence |
| `ukpn_flexibility_dispatches`*, `ukpn_flexibility_tender_data`*, `ukpn_gsp_narrative`*, `ukpn_dnoa`* | UKPN flexibility and network-planning datasets | CC-BY-4.0 | ODS API licence field (read only; no record redistributed) |

\* Added beyond the README registry. The reason for each is in its `notes` field:

- The checkpoints and the case14 dataset are the official artefacts of the GENCO paper's reproduction guide.
- The monthly operational datasets are, per the half-hourly datasets' own descriptions, the index of which circuits are redacted.
- The E1 transformer datasets link half-hourly `tx_id` series to LTDS transformer nodes, and supply observed nodal demand and the BSP import. The LTDS 3a/5 tables give planning demand, power factor and generation. Only the study region's half-hourly series are retrieved, using a server-side `where` filter.
- The Elexon BMRS prices value energy on the Cloud Impact page (`reports/economic_impact/`). Required attribution: "Contains BMRS data © Elexon Limited copyright and database right [year]"; no implied endorsement by Elexon. The UKPN flexibility datasets were read only to test whether any dispatch belongs to the modelled network.
- The research bundles in `data/demo/research/` and the second-network tables in `reports/g2/` are derived results (metrics, fitted slopes, counts, Embedded Capacity Register asset attributes and validation statistics) computed from UK Power Networks open data (CC BY 4.0), Elexon BMRS prices (BMRS licence, attribution above), EUMETSAT LSA SAF-derived PV (CC BY 4.0) and GENCO predictions (Apache-2.0). They contain no raw time series and no model weights.
- The EPN 33 kV half-hourly dataset is the EPN counterpart of the README's SPN dataset. It was registered in E0-D because most grid-fed 33 kV networks with published data are in EPN.

## Unresolved (blocked by the gate)

| Source ID | Why it is `UNVERIFIED` | Smallest next action |
|---|---|---|
| `ukpn_ltds_cim` | Declares the bespoke **"UK Power Networks Shared Data Licence - Common Information Model"**. The terms are a PDF on UKPN SharePoint that returned HTTP 403 anonymously. | Only needed if the CIM model is ever preferred over LTDS Tables 1/2a/2b. Obtain and review the licence PDF first. |
| `genco_challenge` | The Hugging Face Space declares no licence. It is a rules page, not a data source, and nothing is redistributed. | None required. |

## Satellite products (E3 readiness)

The full decision table is in [`reports/e3_satellite_readiness.md`](../reports/e3_satellite_readiness.md) §7. In summary:

- **LSA SAF MDSSFTD, E-View and Natural Colour Enhanced RGB are all CC BY 4.0.** Derived values and image frames may be packaged in public demo bundles with attribution, a licence link and a "modified" notice.
- **Attribution for EUMETSAT imagery:** "Contains modified EUMETSAT Meteosat data [year]" (Data Policy Art. 6.3).
- **Attribution for LSA SAF:** "EUMETSAT LSA SAF [MDSSFTD, LSA-207]".
- **Previously UNVERIFIED.** Phase 0 blocked both EUMETSAT RGB collections because only the catalogue code `NoConditions` was available. They are now resolved from the authoritative EUMETSAT Data Policy document (PDF sha256 `7198d34b3818af972b35053c7bda44b001369f37d232c5e8d34ee2bc7d5859c3`), not from the README example.
- **Access.** LSA SAF requires a free registration (`LSASAF_USERNAME`/`LSASAF_PASSWORD`). This is an access prerequisite, not a licence restriction.
- **Correction (E3 ingestion).** The EUMETSAT RGB collections are distributed only through anonymous EUMETView WMS: the catalogue records state 'Free and unrestricted - CC-BY-4.0'. The Data Store API keys are not needed for them.
- **LSA SAF static grid data** (`lsa_saf_msg_static`: native lat/lon, land/water mask; public shares) is CC-BY-4.0 on the same basis as the products. It is used only to verify geometry and never redistributed raw.
- **Not covered:** real-time (< 1 h latency) Level 1 SEVIRI data, which is "Recommended Data" with redistribution prohibited. The project does not use it.

## Attribution text

The gate refuses any source that requires attribution but has none stored. To generate a combined attribution block for a set of sources:

```python
from cloud2grid.licensing import Registry, attribution_block

print(attribution_block(["ukpn_grid_and_primary_sites", "lsa_saf_mdssftd"], Registry.load()))
```

UKPN Grid and Primary Sites and the ECR (≥ 1 MW) declare third-party attributions: ONS data under OGL v3, and Ordnance Survey © Crown copyright. Both are included in their stored attribution text and must accompany any derived output.

## Data-protection note

The Embedded Capacity Registers contain customer names, addresses and MPAN/MSIDs. Cloud2Grid only needs technology, capacity, coordinates and connection substation. Customer-identifying columns must not be carried into derived or demo outputs.

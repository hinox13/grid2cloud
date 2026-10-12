# E3 satellite ingestion: access, product structure, real pixel geometry, visual layer

_2 October 2026; completed 6 October 2026 with real MDSSFTD data. Code commit at run time: `9a5c46d` (working tree dirty: E3 code not yet committed)._

To reproduce:

```bash
uv run --env-file .env python scripts/download_satellite_sample.py   # first-file gate + RGB sample
uv run python scripts/satellite_geometry.py                          # real pixel geometry
uv run python scripts/satellite_storage.py                           # storage report / cleanup
```

Outputs:

- [`experiments/e3_satellite/first_file_gate.json`](experiments/e3_satellite/first_file_gate.json)
- [`experiments/e3_satellite/geometry.json`](experiments/e3_satellite/geometry.json)
- [`tables/e3_asset_pixel_mapping.csv`](tables/e3_asset_pixel_mapping.csv)
- [`tables/e3_time_matching.csv`](tables/e3_time_matching.csv)
- [`figures/e3_asset_pixels.png`](figures/e3_asset_pixels.png)
- [`figures/e3_rgb_sample.png`](figures/e3_rgb_sample.png)

## Answer

| Question | Result |
|---|---|
| LSA SAF MDSSFTD access | **Works (6 Oct 2026)** with a re-enabled/new account. History: on 2 Oct no credentials were set; on 3 Oct the supplied account was rejected (HTTP 401 on every endpoint; the account was disabled). After the update, the first-file gate passed (§2a) and the full search period was acquired (§4a). Access is rate-limited by design: one request per slot, sequential, at least 1 s apart, stop on 401/403. |
| EUMETSAT RGB access | **Works, anonymously** (EUMETView WMS, the products' only distribution channel). Four real cropped frames were fetched (E-View and NCL_ENH, 2024-06-15 12:00/12:15 UTC). Served time was confirmed by the server for each. |
| Format decision | **NetCDF4, regular 0.05° grid** for sampling. **Native-pixel geometry** is used for independence and acquisition time (§2). |
| Real pixel geometry | Computed from the official LSA SAF grid files, not the earlier approximation. The projection was validated against the official native lat/lon on 6,258 pixels, with max error 0.005°, which is the files' own 0.01° precision. |
| Sundon | The four major farms occupy **2 native pixels**, with 3 of 4 in **one**. The 2024-active farms at ≥1 MW (6 + 2 MW) share **one** native pixel physically. Read through the NetCDF they sample **two adjacent** native pixels (a resampling artefact, §3a). **H2 stays WEAK.** |
| Canterbury South | Four major farms in **4 distinct native pixels**, with 4 of 6 pairs at least 2 pixels apart. Through the NetCDF: 3 distinct samples. **H2 stays PLAUSIBLE.** |
| Hero visual layer | **E-View** (§5) |

## 1. Access and credentials

| Service | Product | Access path | Auth | Status (6 Oct 2026) |
|---|---|---|---|---|
| LSA SAF data service | MDSSFTD (LSA-207) NetCDF/HDF5 | HTTPS archive; THREDDS/OpenDAP (subsetting) | HTTP basic: `LSASAF_USERNAME`, `LSASAF_PASSWORD` | Listing public; files with credentials → **OK** (blocked 2–3 Oct, see Answer) |
| LSA SAF Nextcloud (public shares) | PUM/ATBD; static MSG grid and land/water mask | WebDAV public link | none | **OK** (3 static files) |
| EUMETView WMS | E-View `msg_fes:rgb_eview`, NCL_ENH `msg_fes:rgb_naturalenhncd` | WMS 1.3.0 GetMap, EPSG:4326 bbox | none | **OK** (4 frames) |
| EUMETSAT Data Store | — | — | `EUMETSAT_CONSUMER_KEY`/`SECRET` | **Not needed**: see below |

**Correction to the E3-readiness report.** The EUMETSAT catalogue records for both RGB collections list a single distribution channel, "EUMETView" (WMS; GeoTIFF), with policy "Free and unrestricted - CC-BY-4.0". The Data Store OpenSearch returns "Not found" for both. So the Data Store consumer key/secret are **not** required for the visual layer. The source registry has been corrected.

**Secrets.**
- Credentials are read from environment variables only and held in memory (`satellite/credentials.py`).
- Errors list variable **names** only, and every download error is passed through redaction.
- Provenance records URLs without credentials.

## 2. MDSSFTD product structure and format decision

The structure below was first taken from the authoritative documentation; §2a confirms it on a real file:
- PUM `SAF/LAND/MF/PUM_MDSSFTD/1.0` issue 3, sha256 `0db9d4f1…`;
- the algorithm change record;
- the official LSA SAF tutorial outputs, which print the NetCDF structure.

The gate script **checks the real file against it and stops on any mismatch**.

| | NetCDF4 ("MSG-Disk") | HDF5 (native) |
|---|---|---|
| Grid | regular lat/lon, **0.05°**, lat 80 → −80 (descending), lon −80 → 80, 3201 × 3201, CF-1.6 | native geostationary 3712 × 3712, COFF/LOFF 1857, CFAC/LFAC 13642337 |
| Variables | `DSSF_TOT`, `FRACTION_DIFFUSE`, `quality_flag` (+ `crs`) | `DSSF_TOT`, `FRACTION_DIFFUSE`, `Q_FLAG`, `Z_ANCILLARY/AOD`, `Z_ANCILLARY/OPACITY_INDEX` |
| Units / packing | CF-decoded; units to be read from the file | DSSF_TOT W/m², int16, scale 10, missing −1; FRACTION_DIFFUSE scale 100, missing −1; Q_FLAG uint8 |
| Size (2024-06-15 12:00) | **5,446 KB** | 15,577 KB |
| Server-side subsetting | **yes** (THREDDS/OpenDAP) | no |
| Asset sampling | direct lat/lon lookup | needs separate lat/lon files |

**Decision: NetCDF4 for sampling.**
- It carries the three variables needed.
- It maps directly onto asset coordinates, can be subset on the server, and is a third of the size.
- No format conversion is done.

**Caveats that come with it:**

- **The NetCDF is a reprojection of the native grid.** The LSA SAF NetCDF land/water mask on the same grid has `history = "NetCDF reprojected product … Original product file created: HDF5_…MSG-Disk"`.
  - The 0.05° cells (3.44 km E–W × 5.56 km N–S at 52°N) are **finer N–S** than the native pixel (3.19 × 6.35 km).
  - Adjacent cells can therefore carry the same native value.
  - Independence is counted on **native pixels**.
- **Timing.** Each line is acquired after the nominal slot (PUM §6.3: Δt = 760 − Y/5 s). For native line 306 (Sundon) this is **+11.65 min**, and **+11.61 min** at Canterbury South.
  - Solar position is evaluated at the acquisition time.
  - Slot labels in file names are scan **start** times.
- **File-level `license` attribute.** The LSA SAF NetCDF static file carries `license = "Data is freely available for users registered at the LSA SAF website"`.
  - This is an access statement.
  - The licence remains CC BY 4.0 per the LSA SAF data-usage policy and the EUMETSAT Data Policy (registry entry `lsa_saf_mdssftd`).

**Quality control.** This is PUM Table 4, implemented in `satellite/quality.py` and decoded per pixel.

| Bits | Field | Codes |
|---|---|---|
| 0–1 | land/sea | 00 ocean, 01 land, 10 space, 11 continental water |
| 2–4 | cloud mask | 000 unprocessed, 001 clear, 010 contaminated, 011 cloud filled, 100 snow/ice, 101 undefined |
| 5–7 | algorithm | 000 cloudy ok, 001 clear low quality, 010 cloudy ATOA out of limits, 011 cloudy failure, 100 clear ok, 101 night, 110 beyond view angle, 111 not processed |

Statuses: **GOOD**, **LOW_QUALITY**, **NIGHT**, **INVALID**, **MISSING** and **OUT_OF_RANGE**.
- GOOD and NIGHT drive the PV model. LOW_QUALITY does so only if `allow_low_quality` (default false).
- NIGHT forces irradiance to 0. Algorithm v1.0.11+ writes DSSF = 0 at night; the SZA limit is 90° since v1.0.12.
- Everything else becomes NaN and is carried as a status, never as zero.
- The tutorial's accepted-flag set (133, 13, 9) decodes as GOOD.

**Still to verify on the first real file** (the gate does this automatically):
- the exact `units` attribute;
- CF packing and fill values;
- whether quality flag values outside Table 4 occur;
- the product `algorithm_version` (recorded in provenance).

## 2a. First-file gate on a real file (6 Oct 2026)

File `NETCDF4_LSASAF_MSG_MDSSFTD_MSG-Disk_202406151200.nc`: 5,446,485 bytes, one download, kept in `data/raw/satellite/lsasaf/netcdf/`, with SHA-256 in `metadata/provenance.json`. Every check in the gate passed (`first_file_gate.json`).

| Item | Documented assumption | Real file | Match |
|---|---|---|---|
| Variables | DSSF_TOT, FRACTION_DIFFUSE, quality_flag | DSSF_TOT, FRACTION_DIFFUSE, quality_flag, crs | yes |
| Units | W/m² | `units = "W m-2"` | yes |
| DSSF_TOT packing | int16, ×0.1 (PUM scale 10), missing −1 | int16, `scale_factor 0.1`, `_FillValue −1`, valid 0..15000 | yes |
| FRACTION_DIFFUSE | int16, ×0.01, missing −1 | int16, `scale_factor 0.01`, `_FillValue −1`, valid 0..100 | yes |
| quality_flag | uint8 bitfield (PUM Table 4) | uint8, `long_name Q_FLAG`, **`_FillValue 255`** | yes; **new detail:** 255 is the fill value |
| Grid | 3201 × 3201, 0.05°, lat 80 → −80, lon −80 → 80 | identical; CF `crs` = latitude_longitude, WGS84 | yes |
| Time | nominal slot (scan start) | one value = slot; `units "seconds since 2024-06-15T12:00:00Z"`; `image_reference_time` = slot | yes |
| Version | change record lists v1.0.12 | `algorithm_version 2.0.0`, `base_algorithm_version v1.0.1`, platform MSG3, processing level 03 | **naming differs** from the PUM change record; recorded as is |
| History | NetCDF reprojected from HDF5 | `"NetCDF reprojected product ; … Original product file created: HDF5_LSASAF_MSG_MDSSFTD_MSG-Disk_202406151200"` | yes |

Flags observed in the context box at 12:00:
- 9 (contaminated, ok), 13 (cloud filled, ok) and 133 (clear, ok);
- the continental-water equivalents 11, 15 and 135;
- 75 and 79 (ATOA out of limits → LOW_QUALITY);
- 0 over the sea, with DSSF missing: the product is land-only.

No flag outside PUM Table 4 occurred. **No mismatch, so no parser change was needed** beyond the 255 fill value, which CF decoding already handles.

## 3a. Real-file geometry check

- **Resampling.** Where several 0.05° cells map to the same native pixel under the validated CGMS projection, they carry identical values in **99.8%** of 663 such pixels. The NetCDF is therefore a nearest-neighbour reprojection of native pixels, and the projection used here is consistent with the real data.
  - 13% of N–S neighbours are duplicates, against 0.3% E–W, as expected from 5.56 km cells versus 6.35 km native pixels.
- **What an asset actually receives.** The value of a cell comes from the native pixel containing the **cell centre**, which can differ from the native pixel containing the asset.
  - ECR:955 (6 MW) and ECR:526 (2 MW) sit in the same native pixel (n1844_306). Through their cells they read n1844_306 and the neighbouring pixel: 764.1 and 796.6 W/m² at the gate slot.
  - The mapping table now carries `sampled_native_pixel_id`.
- **Independent samples through the NetCDF (capacity-weighted effective count):**

| | Sundon (4 major) | Sundon 2024 ≥1 MW | Canterbury (4 major) |
|---|---|---|---|
| Native pixels containing the assets | 2 (1.83) | **1** (1.00) | 4 (3.06) |
| Native pixels sampled via the NetCDF | 3 (2.04) | **2** (1.60) | 3 (2.93) |

The H2 classes are unchanged. Sundon's second 2024 sample is an artefact of the resampling, adjacent and highly correlated, not genuine spatial resolution.

## 3. Real pixel geometry (replaces the approximate model)

**Sources.**
- **Native pixel centres:** the CGMS normalized geostationary projection with the PUM constants. Validated against the official LSA SAF native lat/lon file on **6,258 pixels over the context box: max |Δ| = 0.0050°**, which is the rounding of the file's 0.01° storage. Exact agreement.
- **Regular-grid cells:** read from the LSA SAF NetCDF land/water mask on the product grid. 80.0 / −0.05° / −80.0 / 0.05° / 3201 × 3201, matching the documentation.

### Sundon 33 kV (major farms = 95% of today's connected MW)

| Asset | MW | lat | lon | 0.05° cell (row, col) | cell centre | Native (ncol, nlin) | native centre | Asset→native centre | Edge distance (px) | 2024 |
|---|---|---|---|---|---|---|---|---|---|---|
| ECR:953 | 20 | 51.9333 | −0.6190 | 561, 1588 | 51.948, −0.595 | 1844, 306 | 51.947, −0.606 | 1.75 km | 0.21 | not active |
| ECR:449 | 15 | 51.9188 | −0.5639 | 562, 1589 | 51.898, −0.545 | 1845, 306 | 51.947, −0.559 | 3.12 km | **0.01** | not active |
| ECR:955 | 6 | 51.9248 | −0.6113 | 561, 1588 | 51.948, −0.595 | 1844, 306 | 51.947, −0.606 | 2.48 km | 0.11 | **active** |
| ECR:526 | 2 | 51.9513 | −0.6214 | 561, 1587 | 51.948, −0.645 | 1844, 306 | 51.947, −0.606 | 1.17 km | 0.17 | **active** |

- **Distinct native pixels: 2.** ECR:953, ECR:955 and ECR:526 share pixel n1844_306. ECR:449 is in the adjacent column, with all three of its pairs 1 column apart. No pair is ≥ 2 pixels apart.
- The capacity-weighted effective number of independent pixels is **1.83**, against 2.1 in the approximate model.
- **All four farms are within the PUM ⅓-pixel georeference uncertainty of an edge.** ECR:449 sits 0.01 pixel from an edge. Its separate pixel is not robust.
- The NetCDF grid shows 3 distinct cells. Because of the N–S oversampling, this overstates independence.
- **2024-active assets at ≥1 MW (6 + 2 MW): one native pixel.** In 2024, Sundon's PV forcing is effectively a **single satellite sample**. The sub-1 MW assets add 5 more native pixels, but only 0.945 MW.

### Canterbury South 33 kV (metadata only, no reconstruction)

| Asset | MW | 0.05° cell | Native (ncol, nlin) | Edge distance (px) | 2024 |
|---|---|---|---|---|---|
| ECR:308 | 15 | 574, 1623 | 1882, 318 | 0.39 | active (dated) |
| ECR:130 | 12 | 573, 1622 | 1881, 317 | 0.12 | active |
| ECR:913 | 9.5 | 575, 1625 | 1885, 319 | 0.10 | active |
| ECR:617 | 1 | 575, 1625 | 1884, 318 | 0.35 | active |

- **4 distinct native pixels** (effective 3.06; approximate model 3.0). Pair separations are 1, 3, 2, 4, 3 and 1 pixels, so **4 of 6 pairs are ≥ 2 pixels apart**, which survives the ⅓-pixel uncertainty.
- The E–W span is **4 native columns (11.0 km)**. At 5 / 10 / 15 m/s a front needs **37 / 18 / 12 min** to cross, which is 1.2 frames at 10 m/s. That makes staggered ramps resolvable over one or two consecutive slots.
- **NetCDF caveat:** ECR:913 and ECR:617 are in different native pixels but the **same** 0.05° cell. Sampled from NetCDF, Canterbury has 3 independent cells. An H2 analysis there should sample the **native HDF5 grid**, using the static lat/lon files already in hand.
- All four are dated before 2024, so the 2024 geometry equals today's.

### H2 update (same pre-declared criteria; only the pixel count replaced)

| Region | Effective pixels (approx. → real) | H2 (E3-readiness) | H2 (real geometry) |
|---|---|---|---|
| Sundon 33 kV | 2.10 → **1.83** (2024 at ≥1 MW: **1.0**) | WEAK | **WEAK**: also fails the PLAUSIBLE pixel criterion (< 2) |
| Canterbury South 33 kV | 2.99 → **3.06** | PLAUSIBLE | **PLAUSIBLE** (unchanged) |

Sundon is not promoted. Option B stands.

## 4. Study-area boxes and storage plan

| Box | Extent | Purpose | Regular-grid size |
|---|---|---|---|
| Context | 50.5–53.5 N, 3.5 W–2.0 E | Sundon and Canterbury, about 200 km of upstream (westerly) weather, for the animation | 61 × 111 cells |
| Analysis | 51.65–52.25 N, 1.05–0.15 W | event search around the Sundon assets | 13 × 19 cells |

Volume estimates for the pre-registered search period (Apr–Sep 2024: **9,078** daylight slots with elevation ≥ 10°; uncompressed int16/uint8 sizes):

| Item | Mode | Transfer | Stored |
|---|---|---|---|
| Analysis-box series | OpenDAP subset (default) | ≈ 11 MB of data (+ protocol overhead) | ≤ 11 MB (compressed NetCDF, one file per day) |
| Same, fallback | HTTPS full file → crop → delete | ≈ 40 GB transfer | same as above; raw never accumulates |
| Event context boxes (≈ 15 events × 12 slots) | OpenDAP | ≈ 6 MB | ≈ 6 MB |
| RGB frames (≈ 180 PNG) | WMS crop | ≈ 30 MB | ≈ 30 MB |

Current storage (`scripts/satellite_storage.py`):

| Item | Size |
|---|---|
| raw (static geometry, 3 files) | **3.24 MB** |
| RGB frames (4) | **0.47 MB** |
| MDSSFTD crops / processed | **0** |
| full product files | **0** |

The cleanup command deletes only regenerable categories, and is a dry run unless `--yes` is given.

## 4a. Acquisition and storage (6 Oct 2026)

Mode: one DAP ASCII request per slot.
- The analysis box is 13 × 19 cells; each response is about 6 KB.
- Values are decoded with the packing verified on the gate file. A test on the gate slot reproduced the gate file exactly.
- THREDDS NCSS is not enabled (HTTP 404). pydap would have needed about 7 requests per slot.
- The public listing is read first, so absent slots are never requested.

| | Value |
|---|---|
| Days acquired | 183 / 183 (2024-04-01 … 2024-09-30) |
| Daylight slots expected / retrieved | 9,078 / **9,040** (38 absent from the archive or returning 404, recorded per day) |
| Authenticated requests | ≈ 9,100 over three resumable runs, plus 1 gate download and 4 night-check requests |
| Interruptions | Run 1 stopped on 27 Jun and run 2 on 17 Aug. Both hit 3 consecutive slots **absent from the archive** (27 Jun 07:00–07:30; 17 Aug 12:45–17:15, 19 slots), confirmed by the public listing. Fixed so that 404s on listed slots are recorded as gaps and never abort; partial days are refetched only for their missing slots. No 401/403 and no throttling was ever returned. |

| Storage | Size |
|---|---|
| Raw | **8.7 MB**: static geometry 3.2 MB + the one gate file 5.4 MB (no other full file was downloaded) |
| Cropped MDSSFTD (183 daily files + gate crop) | **18.1 MB** |
| Processed series (`data/processed/satellite/sundon/`) | **14.7 MB** |
| RGB frames (4 samples + 120 event frames) | **20.5 MB** |
| **Total** | **≈ 62 MB** |

## 5. EUMETSAT RGB visual layer

The frames are real and cropped to the context box. They are georeferenced as EPSG:4326 plate carrée, the same frame as the MDSSFTD NetCDF grid.

**Georeferencing check:** the LSA SAF land/water-mask coastline overlays the dark sea along the south coast and the Thames estuary ([`figures/e3_rgb_sample.png`](figures/e3_rgb_sample.png)).

| | E-View (HRV + IR10.8) | Natural Colour Enhanced (NIR1.6/VIS0.8/VIS0.6) |
|---|---|---|
| Sampling | HRV, about 1 km: resolves individual cumulus cells | 3 km: visibly blocky at this zoom |
| Day/night | both (IR component) | daytime only |
| Archive | from 2022-03-29 (covers 2024) | from 2020-09-01 |
| Frame size (1100 × 600 PNG) | about 175 KB | about 60 KB |
| Readability | yellow-tinted low cloud; strong texture | intuitive colours (green land, white cloud) |

**Selected hero layer: E-View.** It gives the best cloud readability and texture for animating cloud fronts and broken cumulus, and works at all hours. NCL_ENH is kept as an optional explanatory layer: its 3 km blocks show roughly what the radiation product "sees". Both cost the same to access.

## 6. Time matching

Both products label frames by the **nominal SEVIRI slot** (scan start). Over the study area, both are observed **+11.65 min** later on the same scan line.

The rule ([`configs/data/eumetsat.yaml`](../configs/data/eumetsat.yaml)):
- pair by nominal slot;
- read the RGB time from the server's `Warning: 99 Nearest value used: time=…` header, never from the request or a file name;
- reject a pair if |Δ| > 7.5 min.

| requested | radiation slot | RGB served | Δ (min) | accepted |
|---|---|---|---|---|
| 2024-06-15 12:00 | 12:00 (listed in catalog) | 12:00 (E-View, NCL_ENH) | 0 | yes |
| 2024-06-15 12:15 | 12:15 | 12:15 (E-View, NCL_ENH) | 0 | yes |
| 2024-06-15 12:00 | 12:00 | 12:15 (demonstration) | 15 | **rejected** |

The `radiation_time` and `rgb_acquisition_time` columns in [`tables/e3_time_matching.csv`](tables/e3_time_matching.csv) carry the +11.65 min line offset.

## 7. Provenance

Every acquired file is gated by the licence registry and recorded in `metadata/provenance.json` with:
- source ID, provider, product, URL (no credentials), and requested and served time;
- retrieval timestamp, local path, size and SHA-256;
- processing level, and the git commit plus dirty flag.

| File | Size | SHA-256 (prefix) |
|---|---|---|
| `hdf5_lsasaf_msg_lat_msg-disk.bz2` | 968,258 | `cf3de86d…` |
| `hdf5_lsasaf_msg_lon_msg-disk.bz2` | 2,055,817 | `d2ce49a3…` |
| `NETCDF_LSASAF_USGS-IGBP_LWMASK_MSG-Disk_202001270900.nc` | 216,904 | `50b3cb15…` |
| E-View 2024-06-15 12:00 / 12:15 | 175,232 / 175,296 | `2cc6d53a…` / `aa4026ef…` |
| NCL_ENH 2024-06-15 12:00 / 12:15 | 60,695 / 60,131 | `6b13bd25…` / `b22f0c15…` |

**RGB frames are not byte-reproducible.** Re-fetching the identical request for E-View 12:15 returned different bytes (174,713 → 175,296); the other three frames were identical. EUMETView renders server-side.
- A frame is therefore identified by **layer + served time + bbox + size**.
- Its SHA-256 identifies the specific fetched file.
- Event bundles must store the fetched frame rather than rely on a re-fetch reproducing the hash.

## 8. Access status

Resolved on 6 Oct 2026. The account history (no credentials → disabled account → working account) is recorded above. Future runs reuse the same rate limits (`configs/data/lsasaf.yaml` `access.politeness`).

## Attribution

Data source: EUMETSAT LSA SAF, MSG Total and Diffuse Downward Surface Shortwave Flux, MDSSFTD, LSA-207 (CC BY 4.0). Contains modified EUMETSAT Meteosat data 2024 (E-View and Natural Colour Enhanced RGB via EUMETView; CC BY 4.0). Product geometry from the EUMETSAT LSA SAF static MSG grid (CC BY 4.0). Asset locations contain UK Power Networks data (Embedded Capacity Register), licensed under CC BY 4.0.

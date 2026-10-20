# Economic impact: data sources

_Retrieved 20 October 2026. Raw responses stay local (`data/interim/economic_impact/`, not redistributed); counts are in `prices_retrieval.json`, and the 24 periods the Explorer shows are in `data/demo/cloud_impact/`. `scripts/economic_impact/fetch_prices.py` re-fetches the Elexon prices without a key._

## Elexon Insights (BMRS), no API key required

| | Market Index Data (MID) | System prices (imbalance) |
|---|---|---|
| Endpoint | `GET https://data.elexon.co.uk/bmrs/api/v1/balancing/pricing/market-index?from=…&to=…` (7-day windows) | `GET …/balancing/settlement/system-prices/{settlementDate}` (one call per date) |
| Coverage, 31 Mar – 1 Oct 2024 | 8,879 half-hours for APXMIDP (**one gap at source: 2024-04-13 SP 17, 07:00 UTC, has no APX row**; it is inside the valued sample, so its energy is counted and its value omitted, ≤ £4) and 8,857 for N2EXMIDP. **N2EX rows carry price 0 and volume 0, so they are not used** | 8,878 half-hours |
| Resolution | settlement period (30 min) | settlement period (30 min) |
| Fields used | `startTime` (UTC), `settlementDate`, `settlementPeriod`, `price` (GBP/MWh), `volume` (MWh) | `startTime`, `settlementDate`, `settlementPeriod`, `systemSellPrice` = `systemBuyPrice` (GBP/MWh; single price in 100 % of periods), `createdDateTime` |
| Range, 2024 season | −£61.09 to £147.86 per MWh; no zero-volume APX period | −£91.82 to £200.00 per MWh |
| Economic meaning | A volume-weighted index of short-term (prompt) wholesale trades on the APX/EPEX exchange in each period. **The clearest available reference for the market value of 1 MWh in that half-hour.** It is not a retail tariff and not a price anyone at Sundon paid | The **imbalance cash-out price** that parties pay or receive for deviations from their contracted positions. **Not a wholesale trading price**, and used only as a separate scenario |
| Revisions | Not revised in normal operation | Values can change in later settlement runs. The `createdDateTime` values are from 2024, so the endpoint served 2024 publications |
| Alignment | `startTime` equals the S1 slot (the period start, UTC). Settlement period 1 starts at 23:00 UTC during BST; there are no clock changes inside 1 Apr – 30 Sep 2024 (BST ran 31 Mar – 27 Oct) | same |

**Licence:** [Elexon BMRS data licence](https://www.elexon.co.uk/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/).
- **Terms:** worldwide, royalty-free reuse, including commercial use. Use must not imply endorsement or mislead about the data.
- **Required attribution:** "Contains BMRS data © Elexon Limited copyright and database right 2024."
- **Related:** [BSC Open Data Licence](https://www.elexon.co.uk/bsc/data/open-data-requests/bsc-open-data-licence/).

## UK Power Networks open data (CC BY 4.0; record access with the project's UKPN API key)

| Dataset | Use | Finding |
|---|---|---|
| [`ukpn-flexibility-dispatches`](https://ukpowernetworks.opendatasoft.com/explore/dataset/ukpn-flexibility-dispatches/information/) (51,068 records; fields include zone, product, technology, start and end times in UTC and local time, MW requested, availability and utilisation prices, dispatch type) | Documented dispatches | Zone **"Sundon Little Barford"** has 636 dispatches (2023–2026), **22 in April–September 2024**. These are midday (12:00–17:00 UTC) "Dynamic" and "Day-Ahead" utilisations of gas or engine generation turning up, plus some EV-charging demand turn-downs: 0.5–5 MW, £288–360 per MWh utilisation, no availability payment. Zones named after primaries in our network (**Lewsey**, **Leighton Buzzard**, **Luton North Grid**) have dispatches **only in July–August 2023** |
| `ukpn-flexibility-tender-data` (zone ↔ postcode) | Zone extent | "Sundon Little Barford" postcodes are overwhelmingly **Bedford (MK40–MK45)**: about 4,900 of 5,276 records. **Only 14 are LU postcodes**, scattered and partly un-geolocated. Our network's area (Luton north, Dunstable, Houghton Regis, Leighton Buzzard) falls mainly under "Luton North Grid" (1,031 LU postcodes) and "Cheddington" (253) |
| `ukpn-gsp-narrative` | GSP context | **Sundon GSP** (4 × 240 MVA 400/132 kV): "constrained from an import and export perspective", with **fault-level** issues; no technical limits; a new GSP is needed; Reverse Power Flow requirement |
| `ukpn-dnoa` | Constraint register | No record mentions Sundon |

**Conclusion on flexibility:** no documented 2024 UKPN flexibility dispatch is shown to belong to the modelled Sundon 33 kV network.
- **Sundon Little Barford:** its zone is named after the Sundon and Little Barford supply points but is populated with Bedford-area postcodes, and its electrical definition (which circuits and substations) is not published in these datasets.
- **How its prices may be used:** only as **contextual examples from another zone**, never as a Sundon cost.
- **How UKPN describes the GSP:** the Sundon GSP narrative is about fault-level constraints at the 400/132 kV level, not a thermal constraint that our 33 kV import changes would relieve.

## Cloud2Grid (frozen, unchanged)

- **States:** S1_WEATHER_ALIGNED, 2,829 AC-reconstructed half-hourly states; 2,820 with no line out are used.
- **Explicit 33 kV PV:** the 6 MW plant ECR:955, equal to `p_hv_injected_mw`.
- **Clear-sky PV:** the E3 per-asset PV estimate and the same pvlib chain under Ineichen.
- **Models:** frozen E5c (`e5c_ft_n10000_s2`) and E5d (`e5d_l1_s0`) with their normalisers.
- **Licences:** UKPN and EUMETSAT/LSA SAF data CC BY 4.0; GENCO Apache-2.0.

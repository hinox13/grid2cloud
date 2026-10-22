import { useState } from "react";
import { DayChart, HalfHourLedger, SeasonView, useCloudImpact, type Scenario } from "../scenes/visuals";
import { Claim, DataError, Loading } from "../data/load";
import { gbp, hhmm, ms, num } from "../data/format";
import { Callout, PageHead, Prov, Section, Seg, Tiles } from "./ui";

const ATTRIB = "Contains BMRS data © Elexon Limited copyright and database right 2024";

export function Value() {
  const { data: ci, error } = useCloudImpact();
  const [scenario, setScenario] = useState<Scenario | "both">("both");
  const [sel, setSel] = useState(12);
  if (error) return <DataError what="the economic study" detail={error} />;
  if (!ci) return <Loading />;
  const P = ci.periods;
  const D = ci.derived;
  const S = ci.season;
  const pa = S.pv_attributed as Record<string, Record<string, number>>;
  const dc = S.daily_context as Record<string, number | string>;
  return (
    <>
      <PageHead
        title="Cloud impact: from clouds to grid to value"
        lead="One explicit 6 MW solar plant, not all of Sundon's solar: how satellite-observed clouds changed its estimated generation, the reconstructed grid import and the illustrative value of that energy, on one real day (15 June 2024) and across the April–September 2024 season."
      >
        <Callout tone="warn">
          <strong>Illustrative valuations.</strong> Historical Elexon APX prices applied to AC-reconstructed energy: not realised costs, savings, bills, revenues or forecasts. GENCO does not predict prices, and a national price is not a local nodal price.
        </Callout>
      </PageHead>

      <Section title="Two counterfactuals, two questions" scope={{ kind: "economic", span: "season" }}>
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Table, scrolls sideways on small screens">
          <table className="ex-table">
            <caption>Both vary only the same 6 MW plant; everything else in each AC state is held fixed</caption>
            <thead>
              <tr>
                <th scope="col">Question</th>
                <th scope="col">Compared</th>
                <th scope="col" className="num">
                  15 June 2024
                </th>
                <th scope="col" className="num">
                  All <Claim id="season_periods" bare /> evaluated half-hours
                </th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>
                  <strong>What did the clouds add?</strong> Cloud-attributed import
                </td>
                <td>observed sky against a hypothetical clear sky over the plant</td>
                <td className="num">
                  <Claim id="day_cloud_mwh" />, <Claim id="day_cloud_gbp" />
                </td>
                <td className="num">
                  <Claim id="season_cloud_attributed_mwh" />, <Claim id="season_cloud_attributed_gbp" />
                </td>
              </tr>
              <tr>
                <td>
                  <strong>What did the plant displace?</strong> PV-attributed import
                </td>
                <td>the plant as observed against no plant at all</td>
                <td className="num">
                  <Claim id="day_pv_attr_mwh" />, <Claim id="day_pv_attr_gbp" />
                </td>
                <td className="num">
                  <Claim id="season_pv_attributed_mwh" />, <Claim id="season_pv_attributed_gbp" />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="note">Different questions, not one number at two scales: the cloud figure is the gap to a clear-sky estimate, the plant figure the plant's whole contribution. Illustrative values at historical APX prices.</p>
      </Section>

      <Section title="15 June 2024: observed sky against a hypothetical clear sky" scope={{ kind: "economic", span: "day" }}>
        <Seg
          label="Scenario"
          value={scenario}
          onChange={setScenario}
          options={[
            ["observed", "Observed sky"],
            ["clear", "Clear sky (hypothetical)"],
            ["both", "The gap"],
          ]}
        />
        <div className="ex-daychart">
          <DayChart ci={ci} scenario={scenario} sel={sel} onSel={setSel}>
            <HalfHourLedger ci={ci} i={sel} />
          </DayChart>
        </div>
        <Tiles
          items={[
            { k: "Extra import caused by clouds", v: <Claim id="day_cloud_mwh" />, s: <>observed − clear sky, <Claim id="day_periods" bare /> half-hours, <Claim id="day_first" bare />–<Claim id="day_last" bare /> UTC</> },
            { k: "Illustrative value at historical prices", v: <Claim id="day_cloud_gbp" />, s: "extra import × APX price, per half-hour, summed" },
            { k: "The 11:00 half-hour alone", v: <Claim id="one_cloud_gbp" />, s: <><Claim id="one_cloud_mwh" /> × <Claim id="one_apx" /></> },
          ]}
        />
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Table, scrolls sideways on small screens">
          <table className="ex-table">
            <caption>Four numbers, four different things</caption>
            <thead>
              <tr>
                <th scope="col">Number</th>
                <th scope="col">What it measures</th>
                <th scope="col">Interval</th>
                <th scope="col">Source</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>
                  <Claim id="fleet_pv_delta" />
                </td>
                <td>change in satellite-derived PV, all local plants (8.945 MW fleet)</td>
                <td>11:00 → 11:30 UTC, 15-minute estimates</td>
                <td>
                  <Prov kind="derived" />
                </td>
              </tr>
              <tr>
                <td>
                  <Claim id="import_ac_1100" bare /> → <Claim id="import_ac_1130" />
                </td>
                <td>historical AC import; loads, battery and solar all changed</td>
                <td>11:00 and 11:30 half-hours</td>
                <td>
                  <Prov kind="simulated" />
                </td>
              </tr>
              <tr>
                <td>
                  <Claim id="cf_E5d_1100" /> (AC <Claim id="cf_AC_1100" />)
                </td>
                <td>
                  E5d-predicted import change if the 6 MW plant had its clear-sky output (<Claim id="plant_pv_cf_delta" />), loads fixed
                </td>
                <td>11:00 half-hour only</td>
                <td>
                  <Prov kind="predicted" /> <Prov kind="hypothetical" />
                </td>
              </tr>
              <tr>
                <td>
                  <Claim id="day_cloud_gbp" />
                </td>
                <td>illustrative value of the extra import caused by clouds, at APX prices</td>
                <td>24 half-hours, 05:00–16:30 UTC</td>
                <td>AC counterfactual × observed price</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Every half-hour of 15 June" scope={{ kind: "economic", span: "day" }} aside={<p className="note">Energy = MW difference × 0.5 h per settlement period; value = energy × the same period's APX price. Computed by the export pipeline from the frozen bundle. E5c and E5d columns are frozen predictions for the same two states.</p>}>
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Table, scrolls sideways on small screens">
          <table className="ex-table dense">
            <thead>
              <tr>
                <th scope="col">UTC</th>
                <th scope="col" className="num">
                  SP
                </th>
                <th scope="col" className="num">
                  Plant obs. (MW)
                </th>
                <th scope="col" className="num">
                  Plant clear (MW)
                </th>
                <th scope="col" className="num">
                  AC import obs. (MW)
                </th>
                <th scope="col" className="num">
                  AC import clear (MW)
                </th>
                <th scope="col" className="num">
                  Extra import (MWh)
                </th>
                <th scope="col" className="num">
                  APX (£/MWh)
                </th>
                <th scope="col" className="num">
                  Value (£)
                </th>
                <th scope="col" className="num">
                  E5c extra (MWh)
                </th>
                <th scope="col" className="num">
                  E5d extra (MWh)
                </th>
              </tr>
            </thead>
            <tbody>
              {P.slot.map((s, i) => (
                <tr key={s} className={i === sel ? "is-sel" : ""} onClick={() => setSel(i)}>
                  <td>{hhmm(s)}</td>
                  <td className="num">{P.settlement_period[i]}</td>
                  <td className="num">{num(P.plant_pv_mw[i], 2)}</td>
                  <td className="num">{num(P.plant_pv_clear_mw[i], 2)}</td>
                  <td className="num">{num(P.import_AC_observed_mw[i], 1)}</td>
                  <td className="num">{num(P.import_AC_clear_sky_mw[i], 1)}</td>
                  <td className="num">{num(D.cloud_AC_mwh[i], 2, true)}</td>
                  <td className="num">{num(P.apx_gbp_per_mwh[i], 2)}</td>
                  <td className="num">{gbp(D.cloud_AC_gbp[i])}</td>
                  <td className="num">{num(D.cloud_E5c_mwh[i], 2, true)}</td>
                  <td className="num">{num(D.cloud_E5d_mwh[i], 2, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Across the season" scope={{ kind: "economic", span: "season" }}>
        <p className="ex-p">
          <Claim id="season_periods" /> AC-reconstructed half-hours of April–September 2024, not every daylight interval. One of them, 13 April 07:00 UTC (settlement period 17), has no APX price at source; its energy is counted and its value (at most £{num(ci.apx_gap.value_bound_gbp, 2)}) is omitted.
        </p>
        <Tiles
          items={[
            { k: "Extra import caused by clouds (vs clear sky)", v: <Claim id="season_cloud_attributed_mwh" />, s: <><Claim id="season_cloud_attributed_gbp" /> at APX prices (illustrative), net of negative half-hours</> },
            { k: "A different question: import the plant displaced (vs no plant)", v: <Claim id="season_pv_attributed_mwh" />, s: <><Claim id="season_pv_attributed_gbp" /> at APX prices (illustrative)</> },
            { k: "Daily cloud value, 136 days", v: gbp(dc.cloud_value_apx_gbp_median as number), s: `median; 90th percentile ${gbp(dc.cloud_value_apx_gbp_p90 as number)}; largest ${gbp(dc.cloud_value_apx_gbp_max as number)} on ${new Date(ms(String(dc.max_day) + "T00:00:00Z")).toLocaleDateString("en-GB", { day: "numeric", month: "long", timeZone: "UTC" })}` },
          ]}
        />
        <div className="ex-season">
          <SeasonView ci={ci} />
        </div>
        <ul className="ex-list">
          <li>
            <strong>Uneven coverage.</strong> The evaluated half-hours fall on <Claim id="season_days" bare /> of the <Claim id="season_days_span" bare /> days of April–September, between <Claim id="periods_day_min" bare /> and <Claim id="periods_day_max" bare /> per day; they are the states that could be reconstructed (daylight, complete data, no line out). The totals are sums over these half-hours, not seasonal totals.
          </li>
          <li>
            <strong>Signed contributions.</strong> In <Claim id="cloud_neg_periods" bare /> half-hours the satellite-derived output exceeded the modelled clear-sky estimate, so their contribution is negative (<Claim id="cloud_neg_mwh" /> against <Claim id="cloud_pos_mwh" /> positive). That is not proof that clouds raised generation in each of them: it can also reflect disagreement between the satellite-derived estimate and the clear-sky model. <Claim id="apx_neg_periods" bare /> valued half-hours had negative APX prices (as low as <Claim id="apx_season_min" />). Both enter with their signs: <Claim id="season_cloud_attributed_gbp" /> is the net illustrative valuation across the evaluated half-hours, not a sum of cloud-related losses.
          </li>
        </ul>
        <p className="note">
          The season total is the same calculation repeated over every evaluated half-hour, not the 15 June total multiplied. Only the 6 MW plant is varied: the other <Claim id="other_pv_capacity" /> of local PV sits inside the reconstructed loads and was never changed, so these values do not transfer to other plants or to the network's total solar capacity.
        </p>
      </Section>

      <Section title="How accurately do the models reproduce these valuations?" scope={{ kind: "economic", span: "season" }} aside={<p className="note">The accuracy of an energy valuation, not price prediction. GENCO does not predict prices.</p>}>
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Table, scrolls sideways on small screens">
          <table className="ex-table">
            <caption>Error against the AC reference, all <Claim id="season_periods" bare /> evaluated half-hours</caption>
            <thead>
              <tr>
                <th scope="col" rowSpan={2}>
                  Method
                </th>
                <th scope="colgroup" colSpan={2} className="num">
                  Clouds vs clear sky
                </th>
                <th scope="colgroup" colSpan={2} className="num">
                  Plant vs no plant
                </th>
              </tr>
              <tr>
                <th scope="col" className="num">
                  Season value
                </th>
                <th scope="col" className="num">
                  Per half-hour (MW)
                </th>
                <th scope="col" className="num">
                  Season value
                </th>
                <th scope="col" className="num">
                  Per half-hour (MW)
                </th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>AC reference</td>
                <td className="num">
                  <Claim id="season_cloud_attributed_gbp" />
                </td>
                <td className="num">—</td>
                <td className="num">{gbp(pa.AC.value_apx_gbp)}</td>
                <td className="num">—</td>
              </tr>
              <tr>
                <td>Simple injection accounting (lossless)</td>
                <td className="num">
                  <Claim id="season_cloud_err_accounting" />
                </td>
                <td className="num">
                  <strong>
                    <Claim id="cloud_hh_mae_accounting" bare />
                  </strong>
                </td>
                <td className="num">
                  <Claim id="season_pv_err_accounting" />
                </td>
                <td className="num">
                  <strong>
                    <Claim id="pv_hh_mae_accounting" bare />
                  </strong>
                </td>
              </tr>
              <tr>
                <td>Response-aware GENCO (E5d)</td>
                <td className="num">
                  <strong>
                    <Claim id="season_cloud_err_E5d" />
                  </strong>
                </td>
                <td className="num">
                  <Claim id="cloud_hh_mae_E5d" bare />
                </td>
                <td className="num">
                  <strong>
                    <Claim id="season_pv_err_E5d" />
                  </strong>
                </td>
                <td className="num">
                  <Claim id="pv_hh_mae_E5d" bare />
                </td>
              </tr>
              <tr>
                <td>Generator-aware GENCO (E5c)</td>
                <td className="num">
                  <Claim id="season_cloud_err_E5c" />
                </td>
                <td className="num">
                  <Claim id="cloud_hh_mae_E5c" bare />
                </td>
                <td className="num">
                  <Claim id="season_pv_err_E5c" />
                </td>
                <td className="num">
                  <Claim id="pv_hh_mae_E5c" bare />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="ex-p">
          Season values are signed totals, so E5d's small total errors partly come from errors cancelling. <strong>Per half-hour, simple accounting is more accurate</strong>: closer to AC than E5d in <Claim id="cloud_acc_closer" /> of half-hours for the cloud effect and <Claim id="pv_acc_closer" /> for the plant's contribution, with a lower mean error in both. The AC calculation itself is exact and cheap on this network. The learned response matters (ordinary adaptation would miss almost all of the value), but this is not evidence that GENCO outperforms physics or accounting. Never price GENCO's absolute import: E5d's bias would overstate the value of all imported energy by <Claim id="abs_mode_E5d_gbp" /> (<Claim id="abs_mode_E5d_pct" />).
        </p>
        <p className="note">All values are for the one 6 MW plant on Sundon. No economic value is computed for the second network (Aylesbury East): it has no validated reconstruction to value.</p>
      </Section>

      <Section title="What these numbers are, and are not">
        <Callout tone="warn">
          Historical prices are authentic (Elexon APX Market Index). PV is satellite-derived; electrical states are AC reconstructions; clear sky is a counterfactual. The amounts are illustrative valuations of energy, <strong>not</strong> realised savings, costs, bills, revenues or forecasts. GENCO does not predict electricity prices. A national market price is not a local nodal price. Only the 6 MW plant is varied; smaller plants inside the metered loads are not. {ATTRIB}.
        </Callout>
        <ul className="ex-list">
          <li>
            <strong>Satellite:</strong> EUMETSAT Meteosat E-View imagery (observed) and LSA SAF surface radiation → pvlib (derived PV estimate, not metered).
          </li>
          <li>
            <strong>Grid:</strong> AC power flow on the Sundon network rebuilt from UK Power Networks open data, validated against metered circuits; states reconstructed from metered half-hourly loads plus satellite PV.
          </li>
          <li>
            <strong>Counterfactual:</strong> {ci.definitions.clear_sky}.
          </li>
          <li>
            <strong>Prices:</strong> Elexon Insights APX Market Index per settlement period (BST: period 1 starts 23:00 UTC); frozen in the site, no runtime API call.
          </li>
          <li>
            <strong>Models:</strong> frozen E5c and E5d checkpoints (release cloud2grid-models-v1); E5d is not a validated operational model.
          </li>
          <li>
            <strong>Method:</strong> pre-registered (configs/economic_impact/prereg.yaml). scripts/economic_impact/verify_economic.py re-checks the 15 June numbers from the frozen bundle and the season totals from the released per-half-hour table; re-solving the AC counterfactuals and re-running GENCO needs local research data that is not redistributed.
          </li>
        </ul>
      </Section>
    </>
  );
}

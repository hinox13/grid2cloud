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
        <div className="table-wrap">
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
        <div className="table-wrap">
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
            { k: "Import displaced by the 6 MW plant", v: <Claim id="season_pv_attributed_mwh" />, s: <><Claim id="season_pv_attributed_gbp" /> at APX prices (illustrative)</> },
            { k: "Extra import caused by clouds", v: <Claim id="season_cloud_attributed_mwh" />, s: <><Claim id="season_cloud_attributed_gbp" /> at APX prices (illustrative)</> },
            { k: "Daily cloud value, 136 days", v: gbp(dc.cloud_value_apx_gbp_median as number), s: `median; 90th percentile ${gbp(dc.cloud_value_apx_gbp_p90 as number)}; largest ${gbp(dc.cloud_value_apx_gbp_max as number)} on ${new Date(ms(String(dc.max_day) + "T00:00:00Z")).toLocaleDateString("en-GB", { day: "numeric", month: "long", timeZone: "UTC" })}` },
          ]}
        />
        <div className="ex-season">
          <SeasonView ci={ci} />
        </div>
        <p className="note">
          The season total is the same calculation repeated over every evaluated half-hour, not the 15 June total multiplied. Only the 6 MW plant is varied: the other <Claim id="other_pv_capacity" /> of local PV sits inside the reconstructed loads and was never changed, so these values do not transfer to other plants or to the network's total solar capacity.
        </p>
      </Section>

      <Section title="How accurately do the models reproduce this valuation?" scope={{ kind: "economic", span: "season" }} aside={<p className="note">The accuracy of an energy valuation, not price prediction. GENCO does not predict prices.</p>}>
        <div className="table-wrap">
          <table className="ex-table">
            <thead>
              <tr>
                <th scope="col">Method</th>
                <th scope="col" className="num">
                  Season value (import displaced)
                </th>
                <th scope="col" className="num">
                  Error vs AC
                </th>
                <th scope="col" className="num">
                  Per-half-hour error (MW)
                </th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>AC reference</td>
                <td className="num">{gbp(pa.AC.value_apx_gbp)}</td>
                <td className="num">—</td>
                <td className="num">—</td>
              </tr>
              <tr>
                <td>Simple injection accounting (lossless)</td>
                <td className="num">{gbp(pa.accounting.value_apx_gbp)}</td>
                <td className="num">
                  <Claim id="season_pv_err_accounting" />
                </td>
                <td className="num">{num(pa.accounting.period_mae_mw, 3)}</td>
              </tr>
              <tr>
                <td>Response-aware GENCO (E5d)</td>
                <td className="num">{gbp(pa.E5d.value_apx_gbp)}</td>
                <td className="num">
                  <Claim id="season_pv_err_E5d" />
                </td>
                <td className="num">{num(pa.E5d.period_mae_mw, 3)}</td>
              </tr>
              <tr>
                <td>Generator-aware GENCO (E5c)</td>
                <td className="num">{gbp(pa.E5c.value_apx_gbp)}</td>
                <td className="num">
                  <Claim id="season_pv_err_E5c" />
                </td>
                <td className="num">{num(pa.E5c.period_mae_mw, 2)}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="ex-p">
          Signed season totals. E5d's small total error partly comes from errors cancelling: <strong>per half-hour, simple accounting is slightly more accurate</strong>, and the AC calculation itself is exact and cheap on this network. The learned response matters (ordinary adaptation would miss almost all of the value), but this is not evidence that GENCO outperforms physics or accounting. Never price GENCO's absolute import: E5d's bias would overstate the value of all imported energy by <Claim id="abs_mode_E5d_gbp" /> (<Claim id="abs_mode_E5d_pct" />).
        </p>
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

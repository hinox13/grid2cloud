import { Bars } from "../components/charts";
import { Claim, Loading, useClaims, useData } from "../data/load";
import { MODEL_EXP, MODEL_NAME, num } from "../data/format";
import type { ModelId, ModelsData } from "../data/types";
import { ScopeTag } from "../components/Scope";
import { Callout, ModelName, PageHead, Prov, Section } from "./ui";

const REPO = "https://github.com/hinox13/grid2cloud";
const STEP = ["Start", "Step 1", "Step 2", "Step 3", "Step 4"];

export function Science() {
  const { data } = useData<ModelsData>("models.json");
  const c = useClaims();
  if (!data) return <Loading />;
  const evo = Object.fromEntries(data.evolution.map((r) => [r.model, r])) as Record<string, Record<string, number>>;
  return (
    <>
      <PageHead
        title="The scientific story"
        lead="Can a neural power-flow foundation model (GENCO) stand in for a physical AC solver on a real distribution network when the weather drives the grid?"
      >
        <Callout>
          <strong>Short answer: partly.</strong> Out of the box GENCO cannot read this grid. After four fine-tuning steps on synthetic data only, it learned how the real grid responds to solar, battery and load (solar sensitivity <Claim id="slope_E5d" />, physics <Claim id="slope_AC" />), but it still overestimates how much power Sundon draws (<Claim id="bias_E5d" />), so real transfer is only partial and the weather question stays open.
        </Callout>
      </PageHead>

      <Section title="Three kinds of number">
        <p className="ex-p">Every figure on this site belongs to one of three evaluation scopes, labelled wherever it appears. They answer different questions and are never interchangeable.</p>
        <ul className="scope-list">
          <li>
            <ScopeTag kind="aggregate" />
            <p>Averages and fitted sensitivities over the same <Claim id="n_states" bare /> AC-reconstructed half-hours: mean import, import bias, power-balance error, MW of import per MW of solar. How the models behave in general.</p>
          </li>
          <li>
            <ScopeTag kind="event" />
            <p>The 15 June 2024 cloud clearing, and its controlled counterfactual at 11:00 UTC in which only the 6 MW plant changes. What happened at one moment, in MW.</p>
          </li>
          <li>
            <ScopeTag kind="economic" span="season" />
            <p>One explicit 6 MW plant, valued at historical prices: one half-hour, one day (<Claim id="day_periods" bare /> half-hours) or the season (<Claim id="season_periods" bare /> half-hours). Illustrative, retrospective MWh and £, not costs or savings.</p>
          </li>
        </ul>
      </Section>

      <Section title="What we built">
        <ol className="pipeline">
          <li>
            <Prov kind="observed" />
            <strong>Satellite and grid data</strong>
            <span>Meteosat E-View imagery every 15 minutes; UK Power Networks half-hourly operational load data.</span>
          </li>
          <li>
            <Prov kind="derived" />
            <strong>Satellite solar forcing</strong>
            <span>LSA SAF irradiance sampled at every registered solar asset and converted to estimated output with pvlib. Never metered solar.</span>
          </li>
          <li>
            <Prov kind="simulated" />
            <strong>Physics reference</strong>
            <span>
              The Sundon network rebuilt from public LTDS tables (<Claim id="n_buses" bare /> buses, <Claim id="n_branches" bare /> branches), validated against operational metering, solved with a full AC power flow.
            </span>
          </li>
          <li>
            <Prov kind="predicted" />
            <strong>GENCO</strong>
            <span>Frozen GENCO checkpoints predicting the same states: the original model, then four fine-tuning steps.</span>
          </li>
          <li>
            <Prov kind="hypothetical" />
            <strong>Counterfactuals</strong>
            <span>The same AC state re-solved with one input changed, for example the 6 MW plant under a clear sky.</span>
          </li>
        </ol>
      </Section>

      <Section
        title="From the original model to four fine-tuning steps"
        aside={
          <p className="note">
            Frozen results on the same <Claim id="n_states" bare /> real half-hourly 2024 states. Real-state error: mean power-balance error (MVA; 0 for the physics). Solar response: MW of import per MW of solar. Import: mean power drawn at the grid supply point, offset from the physics (<Claim id="import_mean_AC" />) in brackets.
          </p>
        }
      >
        <div className="table-wrap">
          <table className="ex-table ladder">
            <thead>
              <tr>
                <th scope="col">Step</th>
                <th scope="col">Model</th>
                <th scope="col">What changed</th>
                <th scope="col">Outcome</th>
                <th scope="col" className="num">
                  Real-state error
                </th>
                <th scope="col" className="num">
                  Solar response
                </th>
                <th scope="col" className="num">
                  Import (offset)
                </th>
              </tr>
            </thead>
            <tbody>
              {data.models.map((m, k) => {
                const e = evo[m.id];
                return (
                  <tr key={m.id}>
                    <td>{STEP[k]}</td>
                    <td>
                      <ModelName m={m.id} />
                    </td>
                    <td>{m.ladder_added}</td>
                    <td>
                      <strong>{m.ladder_outcome}</strong>
                    </td>
                    <td className="num">{num(e.PBE_mean, e.PBE_mean < 1 ? 2 : 1)} MVA</td>
                    <td className="num">{m.id === "E5" ? <span title={`fitted ${num(e.genco_slope_pv, 2, true)}, import r ${num(e.import_corr, 2)}`}>not usable</span> : <Claim id={`slope_${m.id}`} bare />}</td>
                    <td className="num">
                      <Claim id={`import_mean_${m.id}`} /> (<Claim id={`bias_${m.id}`} bare />)
                    </td>
                  </tr>
                );
              })}
              <tr className="ref-row">
                <td />
                <td>
                  <ModelName m="AC" />
                </td>
                <td colSpan={2}>physics reference: full AC power flow</td>
                <td className="num">0 MVA</td>
                <td className="num">
                  <Claim id="slope_AC" bare />
                </td>
                <td className="num">
                  <Claim id="import_mean_AC" />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="ex-p">
          The original GENCO predicted <Claim id="import_mean_zero_shot" />, meaning Sundon would be exporting: the wrong direction in <Claim id="zero_shot_wrong_sign" /> of real states. Sampling load, battery and generation over their physical ranges (step 2) cut the real-state error by <Claim id="pbe_cut_E5b_vs_E5" />. Step 3 improved import and battery tracking (r = {num(evo.E5c.import_corr, 2)}), but the solar response stayed near zero. Step 4 trained on pairs of synthetic states that differ in one input; it learned the response, but its offset grew to <Claim id="bias_E5d" />, between <Claim id="e5d_offset_q25" /> and <Claim id="e5d_offset_q75" /> in half of all states and too high in <Claim id="e5d_offset_pos" /> of them.
        </p>
        <div className="ex-figure">
          <Bars
            title="Solar response by step against the physics"
            desc="Fitted import change per MW of solar for each model, with the AC physics as a dashed target."
            domain={[-1.4, 0.2]}
            unit="MW of import per MW of solar, fitted over all real states"
            target={{ value: c.slope_AC.value ?? 0, label: "AC physics" }}
            rows={(["zero_shot", "E5b", "E5c", "E5d"] as ModelId[]).map((m) => ({
              key: m,
              label: (
                <>
                  <span className="ml-name">{MODEL_NAME[m]}</span>
                  <span className="ml-sub">{MODEL_EXP[m]}</span>
                </>
              ),
              value: c[`slope_${m}`].value ?? 0,
              display: <Claim id={`slope_${m}`} />,
              colour: `var(--m-${m})`,
            }))}
          />
          <p className="note">Grid-tuned (E5) is left out: its fitted slope ({num(evo.E5.genco_slope_pv, 2, true)}) is not a usable response because its import barely follows the physics (r = {num(evo.E5.import_corr, 2)}).</p>
        </div>
        <Callout tone="warn">
          <strong>Bottom line.</strong> Synthetic-to-real transfer needs topology and operating-envelope coverage, and explicit learning of physically meaningful sensitivities. Correct sensitivity is still not a calibrated model: the final step fails the full pre-registered real-transfer gate, so the original weather question stays unresolved. Nothing here shows that weather has no effect, or that GENCO is weather-robust. The AC calculation itself is exact and cheap on this network.
        </Callout>
      </Section>

      <Section title="How the evidence was kept honest">
        <ul className="ex-list">
          <li>
            <strong>Pre-registration.</strong> Every experiment's gates, selection rule, transfer criteria and verdict rules were committed before its data, training or evaluation existed.
          </li>
          <li>
            <strong>Synthetic-only selection.</strong> Checkpoints were chosen on synthetic data and frozen, with their SHA256 hashes committed, before any real 2024 state was opened.
          </li>
          <li>
            <strong>Events chosen by weather, not by model.</strong> The showcase events come from a pre-registered meteorological ranking. None was chosen for how GENCO behaved on it.
          </li>
          <li>
            <strong>Same real states for every model.</strong> All five models are scored on the same <Claim id="n_states" bare /> half-hourly 2024 states, with confidence intervals from a day-block bootstrap.
          </li>
          <li>
            <strong>No real data in training.</strong> The response-aware model learned its sensitivities from paired synthetic states only. The real solar response was never a training or selection target.
          </li>
          <li>
            <strong>Stop rules respected.</strong> The weather re-test was pre-registered to run only if real transfer succeeded. It did not, so it was not run for steps 2 to 4.
          </li>
        </ul>
      </Section>

      <Section title="Limits of this site">
        <ul className="ex-list">
          <li>
            <strong>Half-hourly grid states.</strong> Grid states are half-hourly (UKPN data); satellite and solar are 15-minute. Between grid states the site holds the last state and says so. Nothing is interpolated.
          </li>
          <li>
            <strong>Estimated solar, simulated flows.</strong> Solar is a satellite-derived estimate, not metered output. Flows are a simulation on a reconstructed network, validated against operational metering but not identical to it.
          </li>
          <li>
            <strong>Schematic network.</strong> Several junctions have no published coordinates, so they appear only in the schematic. The drawing merges a coupled 132 kV busbar pair and two double-section cables, hence 37 drawn nodes and 42 drawn edges for the model's <Claim id="n_buses" bare /> buses and <Claim id="n_branches" bare /> branches.
          </li>
          <li>
            <strong>Average sensitivities.</strong> Solar, load and battery responses are averages over all real states; per-step attributions apply those averages to one event.
          </li>
          <li>
            <strong>No 15-minute predictions for step 4.</strong> Every model is shown on the frozen half-hourly real states behind its published metrics.
          </li>
          <li>
            <strong>Not an operational tool.</strong> The response-aware model is a research model, not a validated state estimator.
          </li>
        </ul>
      </Section>

      <Section title="Possible follow-up">
        <ul className="ex-list">
          <li>
            <strong>Calibration correction</strong> of the absolute import level (<Claim id="bias_E5d" />), learned from synthetic data only.
          </li>
          <li>
            <strong>Seed stability:</strong> response-aware training gave very different real accuracy across seeds.
          </li>
          <li>
            <strong>Joint response and state training</strong> that balances absolute accuracy and sensitivities in one objective.
          </li>
          <li>
            <strong>A second network</strong> where solar spans many satellite pixels, to test the spatial structure of weather.
          </li>
          <li>
            <strong>Weather re-test</strong> with the frozen protocol once a model passes the complete real-transfer gate.
          </li>
        </ul>
        <p className="note">Each would need its own pre-registration.</p>
      </Section>

      <Section title="Open and reproducible">
        <ul className="ex-links">
          <li>
            <a href={REPO} target="_blank" rel="noopener">
              Source code
            </a>
            <span>Pipeline, pre-registrations and this site. Apache-2.0.</span>
          </li>
          <li>
            <a href={`${REPO}/releases/tag/cloud2grid-models-v1`} target="_blank" rel="noopener">
              Frozen models
            </a>
            <span>Generator-aware and response-aware checkpoints, SHA256 hashes, synthetic test data.</span>
          </li>
          <li>
            <a href={`${REPO}/blob/cloud2grid-models-v1/reproduce/README.md`} target="_blank" rel="noopener">
              Verify the models
            </a>
            <span>
              <code>uv sync --extra genco</code>, then <code>uv run python reproduce/verify_models.py</code>. CPU, about 2 to 3 minutes.
            </span>
          </li>
          <li>
            <a href="#/explore/data">Data and verification on this site</a>
            <span>Every exported file, its frozen source, licence and checks.</span>
          </li>
        </ul>
      </Section>
    </>
  );
}

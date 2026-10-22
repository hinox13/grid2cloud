import { useState } from "react";
import { Bars } from "../components/charts";
import { SlopeScatter } from "../scenes/visuals";
import { Claim, Loading, useData } from "../data/load";
import { MODEL_EXP, MODEL_NAME, hhmm, num } from "../data/format";
import type { EventData, ModelId, ModelsData } from "../data/types";
import { Callout, ModelName, PageHead, Section, Seg, Tiles } from "./ui";

const GENCO: ModelId[] = ["zero_shot", "E5", "E5b", "E5c", "E5d"];

export function Response({ params }: { params: URLSearchParams }) {
  const mods = useData<ModelsData>("models.json");
  const ev = useData<EventData>("events/jun15_cloud_clearing/event.json");
  const [model, setModel] = useState<ModelId>((params.get("m") as ModelId) ?? "E5d");
  const [step, setStep] = useState<number | null>(null);
  if (!mods.data || !ev.data) return <Loading />;
  const evo = Object.fromEntries(mods.data.evolution.map((r) => [r.model, r])) as Record<string, Record<string, number>>;
  const co = mods.data.ols_coefficients_s1;
  const dec = ev.data.decomposition;
  const best = dec.reduce((bi, d, i) => (Math.abs(d.delta.pv_injection_mw) > Math.abs(dec[bi].delta.pv_injection_mw) ? i : bi), 0);
  const j = step ?? best;
  const d = dec[j];
  const e5d = evo.E5d;

  return (
    <>
      <PageHead title="The PV blind spot, and what closed it" lead={
          <>
            Every earlier GENCO version was nearly blind to solar. The response-aware model (E5d) learned the physical sensitivity from paired synthetic AC states, and it transferred to the <Claim id="n_states" bare /> reconstructed real half-hours. Its absolute level did not, and only one of three training seeds learned the response this well.
          </>
        }>
        <Tiles
          items={[
            { k: "AC reference · physics", v: <Claim id="slope_AC" />, s: "import falls almost one-for-one with solar" },
            { k: <ModelName m="E5c" />, v: <Claim id="slope_E5c" />, s: `${num(evo.E5c.pv_slope_ratio * 100, 0)} % of the AC reference response: blind to solar` },
            { k: <ModelName m="E5d" />, v: <Claim id="slope_E5d" />, s: `${num(evo.E5d.pv_slope_ratio * 100, 0)} % of the AC reference response: learned and transferred` },
          ]}
        />
      </PageHead>

      <Section title="One extra MW of solar: what happens to the import?" scope={{ kind: "aggregate" }}>
        <div className="ex-scatter">
          <SlopeScatter models={["E5c", "E5d"]} />
        </div>
        <p className="note">Each point is one real half-hourly 2024 state. Neither model saw a real state, a satellite value or a real slope in training or selection. Frozen values from the published regression; nothing is re-fitted here.</p>
      </Section>

      <Section title="Beyond the grid import: the response across the network" scope={{ kind: "aggregate" }}>
        <Tiles
          items={[
            { k: "Branch flows · solar-response error", v: <><Claim id="branch_resp_E5c" bare /> → <Claim id="branch_resp_E5d" /></>, s: "E5c → E5d, median over branches" },
            { k: "Bus voltage angles · solar-response error", v: <><Claim id="va_resp_E5c" bare /> → <Claim id="va_resp_E5d" bare /> ° per MW</>, s: <>E5c → E5d, median over buses; the AC angle response itself is <Claim id="va_resp_AC" bare /> ° per MW</> },
          ]}
        />
        <p className="ex-p">
          The same regression as for the grid import, fitted to every branch's active-power flow and every bus's voltage angle: the error is the absolute difference between the model's and the AC reference's slope per MW of solar, then the median over branches or buses. Response-aware training moved these too, so it learned a distributed sensitivity rather than correcting one number at the substation. It does not show that the absolute states are accurate: E5d's import level is still off by <Claim id="bias_E5d" />.
        </p>
        <p className="note">Same <Claim id="n_states" bare /> reconstructed half-hours. The branch result was computed with the real-transfer evaluation; the bus-angle result is a post-verdict, report-only diagnostic (reports/e5d_real_transfer.md §2 and §5).</p>
      </Section>

      <Section title="…but the real grid is not yet calibrated" scope={{ kind: "aggregate" }}>
        <Tiles
          items={[
            { k: "Import bias · E5d", v: <Claim id="bias_E5d" />, s: <>predicted import too high in <Claim id="e5d_offset_pos" /> of states (E5c <Claim id="bias_E5c" />)</> },
            { k: "Import error · E5d", v: `${num(e5d.import_mae_mw, 1)} MW`, s: `criterion ≤ 5 MW: fails, yet it follows the variation (r ${num(e5d.import_corr, 3)})` },
            { k: "Voltage error · E5d", v: `${num(e5d.V_error, 4)} pu`, s: "criterion ≤ 0.010 pu: fails (closest so far)" },
            { k: "Battery response · E5d", v: `${num(co.E5d.chap31, 2, true)}`, s: `per MW of battery output, AC ${num(co.AC.chap31, 2, true)}: overshoots` },
          ]}
        />
        <Callout tone="warn">
          <strong>Correct physical sensitivity does not imply calibrated real-grid transfer.</strong> The response-aware model tracks how much the import should move when solar and load change (the battery response overshoots), but not where the import level sits. Pre-registered verdict <strong>E5D-D, partial</strong>: the solar and load criteria pass; import, voltage and battery criteria fail. The selected seed is the best of three: seeds 1 and 2 reach <Claim id="e5d_s1_ratio" bare /> and <Claim id="e5d_s2_ratio" bare /> of the solar response with offsets <Claim id="e5d_s1_bias" /> and <Claim id="e5d_s2_bias" />.
        </Callout>
      </Section>

      <Section title="15 June 2024: what moved the import, half-hour by half-hour" scope={{ kind: "event" }}>
        <div className="ev-controls">
          <div className="field">
            <span>Compare AC with</span>
            <Seg label="Model" value={model} onChange={setModel} options={GENCO.map((m) => [m, MODEL_NAME[m]])} />
          </div>
          <div className="field">
            <span>Half-hour step</span>
            <Seg label="Step" value={String(j)} onChange={(v) => setStep(Number(v))} options={dec.map((x, i) => [String(i), `${hhmm(x.from)}→${hhmm(x.to)}`])} />
          </div>
        </div>
        <Bars
          title={`Import change ${hhmm(d.from)} to ${hhmm(d.to)} split by driver`}
          desc="Published regression coefficients times this step's input changes, for AC and the selected model, with the actual total change."
          domain={[Math.min(-25, ...Object.values(d.terms.AC), ...Object.values(d.terms[model])) * 1.1, Math.max(5, ...Object.values(d.terms.AC), ...Object.values(d.terms[model])) * 1.1]}
          unit="MW change in grid import"
          rows={(
            [
              ["pv", `Solar (${num(d.delta.pv_injection_mw, 1, true)} MW)`],
              ["load", `Load (${num(d.delta.load_mw, 1, true)} MW)`],
              ["battery", `Battery (${num(d.delta.chap31_mw, 1, true)} MW)`],
              ["total", "Actual total change"],
            ] as const
          ).flatMap(([k, lab]) =>
            (["AC", model] as ModelId[]).map((m) => ({
              key: `${k}-${m}`,
              label: (
                <>
                  <span className="ml-name">{lab}</span>
                  <span className="ml-sub">{m === "AC" ? "AC" : `${MODEL_NAME[m]} ${MODEL_EXP[m]}`}</span>
                </>
              ),
              value: d.terms[m][k],
              display: `${num(d.terms[m][k], 1, true)} MW`,
              colour: `var(--m-${m})`,
            })),
          )}
        />
        <p className="note">
          Terms are the published coefficients across all <Claim id="n_states" bare /> states × this step's input changes, computed by the export pipeline; they need not add up exactly to the actual change (the remainder is non-linearity and model error). Grid states are the frozen half-hourly states behind every published metric.
        </p>
      </Section>

      <Section title="Across all real states, every model" scope={{ kind: "aggregate" }}>
        <div className="ex-scatter">
          <SlopeScatter models={["zero_shot", "E5", "E5b", "E5c", "E5d"]} />
        </div>
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Table, scrolls sideways on small screens">
          <table className="ex-table">
            <caption>How strongly each driver moves the grid import (MW per MW), published regression</caption>
            <thead>
              <tr>
                <th scope="col">Model</th>
                <th scope="col" className="num">
                  Solar
                </th>
                <th scope="col" className="num">
                  Load
                </th>
                <th scope="col" className="num">
                  Battery
                </th>
              </tr>
            </thead>
            <tbody>
              {(["AC", ...GENCO] as ModelId[]).map((m) => (
                <tr key={m}>
                  <td>
                    <ModelName m={m} />
                  </td>
                  <td className="num">{num(co[m].pv, 2, true)}</td>
                  <td className="num">{num(co[m].load, 2, true)}</td>
                  <td className="num">{num(co[m].chap31, 2, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="ex-list">
          <li>
            <strong>AC reference:</strong> about −1 MW of import per MW of solar, as energy balance requires in the reconstructed network, where the plant's satellite-estimated output is injected explicitly. It is not a metered response (Methods, Limits).
          </li>
          <li>
            <strong>Generator-aware (E5c)</strong> tracks the battery almost one-for-one ({num(co.E5c.chap31, 2, true)} vs {num(co.AC.chap31, 2, true)}) and load partially ({num(co.E5c.load, 2, true)} vs {num(co.AC.load, 2, true)}), but its solar response is {num(co.E5c.pv, 2, true)}. Its synthetic paired probes showed the same blind spot before any real data entered.
          </li>
          <li>
            <strong>Response-aware (E5d)</strong> was trained with an extra loss on pairs of synthetic AC states that differ in one input. Its real solar response is {num(co.E5d.pv, 2, true)} and its load response {num(co.E5d.load, 2, true)} (AC {num(co.AC.load, 2, true)}). The battery response overshoots ({num(co.E5d.chap31, 2, true)}) and the import level is biased by <Claim id="bias_E5d" />, so the full transfer gate fails.
          </li>
          <li>
            <strong>Grid-tuned (E5)</strong> shows a solar slope of {num(co.E5.pv, 2, true)}, but with an import error of {num(evo.E5.import_mae_mw, 0)} MW and import correlation r = {num(evo.E5.import_corr, 2)}: it does not track real operation, so this slope is not a usable response.
          </li>
          <li>
            <strong>Why solar was hard:</strong> the 6 MW plant varies by at most 6 MW, while primary load swings by tens of MW and the battery by up to ±49.5 MW. In the ordinary training loss such a small signal barely counts; normalising the response error per MW of perturbation is what made it count.
          </li>
        </ul>
      </Section>
    </>
  );
}

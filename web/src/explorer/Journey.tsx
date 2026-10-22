import { useEffect, useState } from "react";
import { ImportAxis, STAGES, STAGE_TEXT, Scoreboard, TradeOff, type Stage } from "../components/journey";
import type { Research } from "../components/replication";
import { SlopeScatter } from "../scenes/visuals";
import { Callout, PageHead, Section, Seg, setParams } from "./ui";
import { EventTimeline } from "./Events";
import { SatelliteView } from "../components/SatelliteView";
import { Claim, Loading, useData } from "../data/load";
import { num } from "../data/format";
import type { EventData, ModelId, ModelsData, Network } from "../data/types";

/** "How did we teach GENCO to understand this network?": the five published stages, one at a time. */
export function Journey({ params }: { params: URLSearchParams }) {
  const want = params.get("stage") as Stage | null;
  const [i, setI] = useState(Math.max(0, want ? STAGES.indexOf(want) : 0));
  const stage = STAGES[i];
  const t = STAGE_TEXT[stage];
  useEffect(() => {
    setParams("/explore/journey", { stage });
  }, [stage]);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowRight") setI((x) => Math.min(STAGES.length - 1, x + 1));
    if (e.key === "ArrowLeft") setI((x) => Math.max(0, x - 1));
  };

  return (
    <>
      <PageHead
        title="How we taught GENCO to understand this network"
        lead="Can a grid foundation model, pretrained on synthetic networks, understand a real distribution network it has never seen, and respond correctly to weather-driven changes in generation?"
      >
        <Callout>
          <strong>Two models, two different strengths.</strong> First we taught GENCO the network: the offset of its average import fell from <Claim id="bias_zero_shot" /> (original) to <Claim id="bias_E5b" /> (E5b). Then we taught it to respond to solar: its sensitivity went from <Claim id="slope_E5c" /> (E5c) to <Claim id="slope_E5d" /> (E5d; physics <Claim id="slope_AC" bare />). E5d's level is off by <Claim id="bias_E5d" />: no model yet does both.
        </Callout>
      </PageHead>

      <Section title="Five stages, one at a time" scope={{ kind: "aggregate" }}>
        <div className="jr" onKeyDown={onKey}>
          <ol className="jr-track" role="tablist" aria-label="Adaptation stages">
            {STAGES.map((m, k) => (
              <li key={m} role="presentation" className={k < i ? "done" : k === i ? "on" : ""}>
                <button role="tab" aria-selected={k === i} tabIndex={k === i ? 0 : -1} onClick={() => setI(k)} style={{ ["--c" as string]: `var(--m-${m})` }}>
                  <span className="jr-tag">{STAGE_TEXT[m].tag}</span>
                  <span className="jr-name">{STAGE_TEXT[m].name}</span>
                  <span className="jr-mini">
                    <span>
                      offset <Claim id={`bias_${m}`} />
                    </span>
                    <span>
                      PBE <Claim id={`pbe_${m}`} />
                    </span>
                    <span>solar {m === "E5" ? "not usable" : <Claim id={`slope_${m}`} bare />}</span>
                  </span>
                </button>
              </li>
            ))}
          </ol>

          <div className="jr-panel" role="tabpanel" aria-label={t.name} key={stage}>
            <div className="jr-visual">
              <ImportAxis rows={i === 0 ? ["zero_shot"] : ["zero_shot", stage]} focus={stage} />
              <div className="jr-meters">
                <div className="jr-meter">
                  <span className="k">State accuracy · import offset</span>
                  <span className="v">
                    <Claim id={`bias_${stage}`} />
                  </span>
                  <span className="s">
                    power-balance error <Claim id={`pbe_${stage}`} />
                  </span>
                </div>
                <div className="jr-meter">
                  <span className="k">Response accuracy · solar slope</span>
                  <span className="v">{stage === "E5" ? "not usable" : <Claim id={`slope_${stage}`} />}</span>
                  <span className="s">
                    physics <Claim id="slope_AC" />
                  </span>
                </div>
              </div>
            </div>
            <dl className="jr-text">
              <div>
                <dt>What changed</dt>
                <dd>{t.change}</dd>
              </div>
              <div>
                <dt>What it fixed</dt>
                <dd>{t.fixed}</dd>
              </div>
              <div>
                <dt>What was still wrong</dt>
                <dd>{t.left}</dd>
              </div>
              <div>
                <dt>Why the next step</dt>
                <dd>{t.next}</dd>
              </div>
              {t.caveat && <div className="jr-caveat">{t.caveat}</div>}
            </dl>
            <div className="jr-nav">
              <button className="btn btn-secondary" onClick={() => setI((x) => x - 1)} disabled={i === 0}>
                Previous step
              </button>
              <button className="btn btn-primary" onClick={() => setI((x) => x + 1)} disabled={i === STAGES.length - 1}>
                Next step
              </button>
            </div>
          </div>
        </div>
      </Section>

      <Section title="Two models, two different strengths" scope={{ kind: "aggregate" }} aside={<p className="note">Each model on the same real states. Selection used synthetic data only; checkpoints were frozen before any real state was evaluated.</p>}>
        <TradeOff />
        <MetricByMetric />
        <p className="ex-p">
          <strong>Why can a model learn the change but not the level?</strong> A published post-hoc diagnostic on <Claim id="cancel_n" bare /> held-out synthetic pairs that differ only in solar: the frozen E5d model's import errors in the two states of a pair are almost identical (r <Claim id="cancel_r" bare />, <Claim id="cancel_level" /> per state), so they largely cancel in the difference, which is what the response loss supervises (<Claim id="cancel_delta" /> error in the predicted change). This is a measured observation consistent with the trade-off, not an established cause of it.
        </p>
        <div className="ex-figure">
          <Scoreboard />
        </div>
      </Section>

      <Section title="One seed, one setting" scope={{ kind: "aggregate" }}>
        <SeedTable />
      </Section>

      <Section title="See it happen on 15 June" scope={{ kind: "event", cf: true }}>
        <SeeItHappen />
      </Section>

      <Section title="The solar response, state by state" scope={{ kind: "aggregate" }}>
        <div className="ex-scatter">
          <SlopeScatter models={["E5c", "E5d"]} />
        </div>
      </Section>

      <Section title="What this does and does not show">
        <ul className="ex-list">
          <li>
            The evaluation is aggregate over all <Claim id="n_states" bare /> reconstructed real half-hours of 2024 on this one network; it is not the 15 June 11:00 counterfactual. A second network repeated the pattern on synthetic states only (<a href="#/explore/replication">second network</a>); it is not evidence about real operation elsewhere.
          </li>
          <li>The reference is an AC reconstruction informed by observed loads and satellite PV, validated against measured circuits, not a directly measured complete grid state.</li>
          <li>States and sensitivities did not improve together. No stage passes the full pre-registered real-transfer gate, the response-aware result depends on one training seed, and GENCO does not outperform AC power flow, which is exact and cheap on this network.</li>
          <li>{STAGE_TEXT.E5c.caveat}</li>
        </ul>
        <p className="ex-p">
          Full metrics with confidence intervals, verdicts and checkpoints: <a href="#/explore/models">Model metrics</a>. Per-step attributions on 15 June: <a href="#/explore/response">PV response</a>.
        </p>
      </Section>
    </>
  );
}

/** The aggregate findings on the real event: two observed frames and the AC-vs-GENCO import timeline. */
function SeeItHappen() {
  const ev = useData<EventData>("events/jun15_cloud_clearing/event.json");
  const net = useData<Network>("network.json");
  const [model, setModel] = useState<ModelId>("E5d");
  if (!ev.data || !net.data) return <Loading />;
  const E = ev.data;
  const i11 = E.frames.findIndex((f) => f.t === "2024-06-15T11:00:00Z");
  const i1130 = E.frames.findIndex((f) => f.t === "2024-06-15T11:30:00Z");
  return (
    <div className="see">
      <div className="see-frames">
        {[i11, i1130].map((k) => (
          <figure key={k} className="see-frame">
            <SatelliteView event={E} frame={k} camera="sundon" network={net.data} />
          </figure>
        ))}
        <p className="note">Meteosat E-View, observed, 11:00 and 11:30 UTC: the field clears over the study area. © EUMETSAT 2024, CC BY 4.0, modified.</p>
      </div>
      <div className="see-chart">
        <Seg
          label="Model"
          value={model}
          onChange={setModel}
          options={[
            ["E5c", "Generator-aware (E5c)"],
            ["E5d", "Response-aware (E5d)"],
          ]}
        />
        <EventTimeline ev={E} model={model} t="2024-06-15T11:30:00Z" g="2024-06-15T11:30:00Z" />
        <p className="note">
          Half-hourly AC and frozen GENCO import on the real 15 June states. Both models follow the drop when the sky clears, the generator-aware one mostly through the demand and battery changes rather than solar. Both sit above the physics; the response-aware one by about its usual offset (<Claim id="bias_E5d" /> on average over all states).
        </p>
      </div>
    </div>
  );
}

/** E5b against E5d on every published real-state metric: which is closer to the AC reference. */
function MetricByMetric() {
  const { data } = useData<ModelsData>("models.json");
  if (!data) return <Loading />;
  const e = Object.fromEntries(data.evolution.map((r) => [r.model, r])) as unknown as Record<string, Record<string, number>>;
  const B = e.E5b;
  const D = e.E5d;
  // [label, value(model), format, lower-is-better | target]
  const rows: [string, (m: Record<string, number>) => number, (x: number) => string, "low" | "high" | number, "state" | "response"][] = [
    ["Import bias (MW)", (m) => m.import_bias_mw, (x) => num(x, 1, true), 0, "state"],
    ["Import MAE (MW)", (m) => m.import_mae_mw, (x) => num(x, 1), "low", "state"],
    ["Power-balance error (MVA)", (m) => m.PBE_mean, (x) => num(x, 3), "low", "state"],
    ["Active residual (MW)", (m) => m.P_residual, (x) => num(x, 2), "low", "state"],
    ["Branch P error (MW)", (m) => m.branch_P_error, (x) => num(x, 2), "low", "state"],
    ["Voltage-angle error (°)", (m) => m.angle_error, (x) => num(x, 2), "low", "state"],
    ["Voltage-magnitude error (pu)", (m) => m.V_error, (x) => num(x, 4), "low", "state"],
    ["Import correlation r", (m) => m.import_corr, (x) => num(x, 3), "high", "state"],
    ["Solar slope (MW/MW)", (m) => m.genco_slope_pv, (x) => num(x, 2, true), B.ac_slope_pv, "response"],
    ["Load slope (MW/MW)", (m) => m.genco_slope_load, (x) => num(x, 2, true), B.ac_slope_load, "response"],
    ["Battery slope (MW/MW)", (m) => m.genco_slope_chap31, (x) => num(x, 2, true), B.ac_slope_chap31, "response"],
  ];
  const better = (t: "low" | "high" | number, b: number, d: number) => (t === "low" ? (b < d ? "E5b" : "E5d") : t === "high" ? (b > d ? "E5b" : "E5d") : Math.abs(b - t) < Math.abs(d - t) ? "E5b" : "E5d");
  const wins = (kind: "state" | "response", m: "E5b" | "E5d") => rows.filter(([, f, , t, k]) => k === kind && better(t, f(B), f(D)) === m).length;
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label="Table, scrolls sideways on small screens">
      <table className="ex-table">
        <caption>Metric by metric, the same {B.n.toLocaleString("en-GB")} states: which model is closer to the AC reference</caption>
        <thead>
          <tr>
            <th scope="col">Metric</th>
            <th scope="col" className="num">
              E5b
            </th>
            <th scope="col" className="num">
              E5d
            </th>
            <th scope="col">Closer</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([lab, f, fmt, t, kind]) => {
            const w = better(t, f(B), f(D));
            return (
              <tr key={lab} data-kind={kind}>
                <td>
                  {lab}
                  {typeof t === "number" && <span className="ci"> AC {fmt(t)}</span>}
                </td>
                <td className="num">{w === "E5b" ? <strong>{fmt(f(B))}</strong> : fmt(f(B))}</td>
                <td className="num">{w === "E5d" ? <strong>{fmt(f(D))}</strong> : fmt(f(D))}</td>
                <td>{w}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="note">
        E5b is closer on {wins("state", "E5b")} of the {rows.filter((r) => r[4] === "state").length} absolute-state metrics; E5d on the other {wins("state", "E5d")} (voltage magnitude and import correlation) and on {wins("response", "E5d")} of the {rows.filter((r) => r[4] === "response").length} responses (its battery response overshoots, but by less than E5b's undershoot). Means over states; confidence intervals on the Model metrics page.
      </p>
    </div>
  );
}

/** Every E5d run on the same states: the selected seed is the best of three, and the response weight trades level against response. */
function SeedTable() {
  const { data } = useData<Research>("research.json");
  if (!data) return <Loading />;
  const runs = data.sundon_runs.runs;
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label="Table, scrolls sideways on small screens">
      <table className="ex-table">
        <caption>
          Every E5d run on the <Claim id="n_states" bare /> reconstructed states: post-freeze diagnostics, never used for selection
        </caption>
        <thead>
          <tr>
            <th scope="col">Run</th>
            <th scope="col" className="num">
              λ
            </th>
            <th scope="col" className="num">
              Seed
            </th>
            <th scope="col" className="num">
              Import bias (MW)
            </th>
            <th scope="col" className="num">
              PBE (MVA)
            </th>
            <th scope="col" className="num">
              Solar response (÷ AC)
            </th>
            <th scope="col">Note</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.run} className={r.selected ? "is-sel" : ""}>
              <td>{r.experiment === "E5c" ? "E5c (frozen)" : r.run}</td>
              <td className="num">{r.lambda ?? "–"}</td>
              <td className="num">{r.seed ?? "–"}</td>
              <td className="num">{num(r.import_bias_mw, 1, true)}</td>
              <td className="num">{num(r.PBE_mean, 2)}</td>
              <td className="num">{r.run === "e5d_l0_s0" ? <span title={`fitted ${num(r.pv_slope_ratio, 2, true)}`}>not interpretable</span> : num(r.pv_slope_ratio, 2)}</td>
              <td>{r.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="note">
        The selected run (highlighted) was chosen on synthetic validation before any real state was opened; it happens to be the best of the three λ = 1 seeds on real states. A weaker response weight (λ = 0.3) gives a smaller offset (<Claim id="e5d_l03_bias" />) with <Claim id="e5d_l03_ratio" bare /> of the physical response: a hint of a trade-off frontier, from a single seed.
      </p>
    </div>
  );
}

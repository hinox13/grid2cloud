import { useEffect, useState } from "react";
import { ImportAxis, STAGES, STAGE_TEXT, Scoreboard, type Stage } from "../components/journey";
import { SlopeScatter } from "../scenes/visuals";
import { Callout, PageHead, Section, Seg, setParams } from "./ui";
import { EventTimeline } from "./Events";
import { SatelliteView } from "../components/SatelliteView";
import { Claim, Loading, useData } from "../data/load";
import type { EventData, ModelId, Network } from "../data/types";

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
          <strong>Two different problems.</strong> First we taught GENCO the network: the offset of its average import fell from <Claim id="bias_zero_shot" /> to <Claim id="bias_E5b" />. Then we taught it to respond to solar: its sensitivity went from <Claim id="slope_E5c" /> to <Claim id="slope_E5d" /> (physics <Claim id="slope_AC" />). Its level is still off by <Claim id="bias_E5d" />.
        </Callout>
      </PageHead>

      <Section title="Five steps, one at a time" scope={{ kind: "aggregate" }}>
        <div className="jr" onKeyDown={onKey}>
          <ol className="jr-track" role="tablist" aria-label="Adaptation stages">
            {STAGES.map((m, k) => (
              <li key={m} className={k < i ? "done" : k === i ? "on" : ""}>
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

      <Section title="Two different problems" scope={{ kind: "aggregate" }} aside={<p className="note">Each model on the same real states. Selection used synthetic data only; checkpoints were frozen before any real state was evaluated.</p>}>
        <Scoreboard focus={["E5b", "E5d"]} />
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
          <li>The evaluation is aggregate over all real half-hours of 2024 on this one network; it is not the 15 June 11:00 counterfactual, and it does not generalise beyond this network and implementation.</li>
          <li>The reference is an AC reconstruction informed by observed loads and satellite PV, validated against measured circuits, not a directly measured complete grid state.</li>
          <li>States and sensitivities did not improve together. No stage passes the full pre-registered real-transfer gate, and GENCO does not outperform AC power flow, which is exact and cheap on this network.</li>
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

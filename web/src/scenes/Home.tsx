import type { ReactNode } from "react";
import { NetworkView } from "../components/NetworkView";
import { ThemeToggle } from "../components/theme";
import { Claim, DataError, Loading, asset, useData } from "../data/load";
import { hhmm } from "../data/format";
import type { EventData, Network } from "../data/types";
import { GUIDED_SECONDS } from "./beats";
import { ImportAxis } from "../components/journey";
import { useReveal } from "../components/reveal";
import { Wordmark } from "../components/Wordmark";
import { ScopeMark, ScopeTag, type ScopeKind } from "../components/Scope";

const REPO = "https://github.com/hinox13/grid2cloud";

// The masthead is a mosaic of the real observations of 15 June 2024, read left to right in time,
// ending on the network they drive. Tiles crop the frames around the study area; nothing is retouched.
const TILES: { t: string; area: string; zoom: number }[] = [
  { t: "08:45", area: "a", zoom: 1.9 },
  { t: "10:00", area: "c", zoom: 2.6 },
  { t: "11:00", area: "e", zoom: 2.6 },
  { t: "11:30", area: "f", zoom: 2.6 },
  { t: "12:15", area: "g", zoom: 1.9 },
];

// Five numbers from four kinds of evidence. Each moment names where its number comes from, so the
// historical fleet estimate, the one-plant counterfactual, the fitted model sensitivity and the
// one-plant valuation never read as one experiment.
const MOMENTS: { ch: string; name: string; line: ReactNode; claim: string; scope: ScopeKind; where: ReactNode }[] = [
  { ch: "clouds", name: "Clouds", line: "Real Meteosat images, fifteen minutes apart, watch the deck break.", claim: "n_frames", scope: "event", where: "observed imagery · 15 June 2024" },
  {
    ch: "energy",
    name: "Energy",
    line: <>The satellite-estimated output of the local solar fleet (<Claim id="fleet_capacity" />) rises from 11:00 to 11:30 UTC, while demand and the battery also change.</>,
    claim: "fleet_pv_delta",
    scope: "event",
    where: "15 June 2024 · satellite-estimated · local fleet",
  },
  {
    ch: "grid",
    name: "Grid",
    line: <>Freeze the reconstructed grid at 11:00 and give only one <Claim id="plant_capacity" bare /> MW plant its clear-sky output: the import change, all else fixed.</>,
    claim: "cf_AC_1100",
    scope: "event",
    where: "11:00 counterfactual · one 6 MW plant · AC-reconstructed grid",
  },
  {
    ch: "genco",
    name: "GENCO",
    line: <>Fitted solar sensitivity of the response-aware model (E5d), against <Claim id="slope_AC" bare /> for the AC reference; ordinary fine-tuning (E5c) gave <Claim id="slope_E5c" bare />.</>,
    claim: "slope_E5d",
    scope: "aggregate",
    where: <>Sundon model evaluation · <Claim id="n_states" bare /> reconstructed states</>,
  },
  {
    ch: "value",
    name: "Value",
    line: "The extra grid import while clouds held one plant below its clear-sky output, across the day, at historical prices.",
    claim: "day_cloud_gbp",
    scope: "economic",
    where: "one Sundon 6 MW plant · illustrative counterfactual valuation",
  },
];

export function Home() {
  const ev = useData<EventData>("events/jun15_cloud_clearing/event.json");
  const net = useData<Network>("network.json");
  useReveal([ev.data]);
  if (ev.error || net.error) return <DataError what="the 15 June event" detail={(ev.error ?? net.error)!} />;
  const frames = new Map((ev.data?.frames ?? []).map((f) => [hhmm(f.t), f]));
  return (
    <div className="home">
      <header className="home-head">
        <Wordmark />
        <nav className="home-tab" aria-label="Main">
          <a href="#/experience">The experience</a>
          <a href="#/explore">The science</a>
          <a href="#/explore/data">Data and sources</a>
        </nav>
        <ThemeToggle />
      </header>

      <div className="masthead" aria-label="Meteosat observations of 15 June 2024 and the Sundon network">
        {TILES.map(({ t, area, zoom }) => {
          const f = frames.get(t);
          return (
            <figure key={t} className="tile tile-photo" style={{ gridArea: area }}>
              {f && <img src={asset(f.file)} alt={`Meteosat E-View, 15 June 2024, ${t} UTC`} style={{ transform: `scale(${zoom})` }} fetchPriority={t === "11:00" ? "high" : "auto"} />}
              <figcaption>{t} UTC</figcaption>
            </figure>
          );
        })}
        <figure className="tile tile-sun" style={{ gridArea: "b" }}>
          {ev.data && <SolarSpark ev={ev.data} />}
          <figcaption className="sun-title">
            Satellite-estimated solar
            <span className="sun-sub">
              local fleet (<Claim id="fleet_capacity" />), 15 June
            </span>
          </figcaption>
          <p className="sun-fig">
            <Claim id="fleet_pv_1100" bare /> → <Claim id="fleet_pv_1130" />
            <span className="sun-when">11:00 → 11:30 UTC</span>
          </p>
        </figure>
        <figure className="tile tile-net" style={{ gridArea: "d" }}>
          {ev.data && net.data ? <NetworkView net={net.data} state={ev.data.flows.AC["2024-06-15T11:30:00Z"]} compact title="Sundon network, AC power flow at 11:30 UTC" /> : <Loading label="" />}
          <figcaption>
            Sundon network · <Claim id="n_buses" bare /> buses · AC flows 11:30 UTC
          </figcaption>
        </figure>
      </div>
      <p className="masthead-key">
        <strong className="key-day">One single day: 15 June 2024</strong>
        <span className="key-rest">
          observed Meteosat imagery · satellite-estimated output of the local solar fleet<span className="d-only"> · reconstructed Sundon network</span>
        </span>
      </p>

      <section className="home-title">
        <h1 className="display">
          <span className="line">
            <span>
              One cloud. <br className="m-only" />
              One grid.
            </span>
          </span>
          <span className="line">
            <span>A chain of consequences.</span>
          </span>
        </h1>
        <div className="home-row">
          <ul className="home-facts" aria-label="What this is">
            <li>
              <strong>Real Meteosat observations</strong> of a cloud deck clearing, 15 June 2024
            </li>
            <li>
              <strong>A real UK network, reconstructed:</strong> Sundon, <Claim id="n_buses" bare /> buses, <Claim id="n_branches" bare /> branches
            </li>
            <li>
              <strong>GENCO, adapted on synthetic data only,</strong> evaluated on <Claim id="n_states" bare /> reconstructed 2024 states, then replicated on a second, synthetic network
            </li>
          </ul>
          <div className="home-stand">
            <p className="lead question">What happens when a grid foundation model trained on synthetic networks encounters a real electricity grid affected by satellite-observed weather?</p>
            <p className="sublead">On 15 June 2024, clouds cleared above a real UK electricity network. Follow what happened, from sunlight to electricity to potential economic value.</p>
            <div className="home-actions">
              <a className="btn btn-primary btn-large" href="#/experience">
                <span aria-hidden="true" className="play-glyph">
                  ▶
                </span>
                Experience the story
              </a>
              <a className="btn btn-secondary btn-large" href="#/explore/journey">
                Follow the model journey
              </a>
            </div>
            <p className="home-meta">
              Move on with Next, at your own pace; Play advances on its own, about {GUIDED_SECONDS} seconds in all. Or <a href="#/explore">explore the science</a>.
            </p>
          </div>
        </div>
      </section>

      <section className="impact" aria-labelledby="impact-h">
        <p className="impact-eyebrow reveal">Why it matters</p>
        <h2 id="impact-h" className="impact-h reveal">
          One solar plant makes a measurable difference to what a network imports, and the weather changes it.
        </h2>
        <ScopeTag kind="economic" span="season" className="reveal" />
        <div className="impact-pair">
          <article className="impact-card reveal" data-cf="plant">
            <p className="impact-k">
              <span className="impact-letter">A</span> What one solar plant contributes
            </p>
            <p className="impact-q">The plant as estimated, against no plant at all</p>
            <p className="impact-big">
              <Claim id="impact_pv_mwh" />
            </p>
            <p className="impact-gbp">
              <Claim id="season_pv_attributed_gbp" /> <span className="impact-gbp-note">illustrative, at historical wholesale prices</span>
            </p>
            <p className="impact-say">
              less electricity imported from the wider grid than if the plant were absent: about <Claim id="impact_pv_share" /> of the import the network would have had without the plant, over the same evaluated half-hours.
            </p>
          </article>
          <article className="impact-card reveal" data-cf="clouds">
            <p className="impact-k">
              <span className="impact-letter">B</span> What changing sunlight means
            </p>
            <p className="impact-q">The same plant as estimated, against a modelled clear sky</p>
            <p className="impact-big">
              <Claim id="impact_cloud_mwh" />
            </p>
            <p className="impact-gbp">
              <Claim id="season_cloud_attributed_gbp" /> <span className="impact-gbp-note">illustrative, at historical wholesale prices</span>
            </p>
            <p className="impact-say">
              more electricity imported because clouds held the plant below its clear-sky estimate. A net figure: in <Claim id="cloud_neg_periods" bare /> half-hours the plant beat that estimate, and those count against it.
            </p>
          </article>
        </div>
        <ul className="impact-read reveal" aria-label="How to read these two numbers">
          <li>
            <strong>Two questions, one plant.</strong> A and B are different comparisons for the same <Claim id="plant_capacity" bare /> MW plant, not the whole local fleet. Never add them.
          </li>
          <li>
            <strong>Reconstructed, not metered.</strong> Each is an AC power-flow import difference over the <Claim id="season_periods" bare /> half-hours that could be reconstructed, on <Claim id="season_days" bare /> of the <Claim id="season_days_span" bare /> days, priced half-hour by half-hour. Sums are signed: <Claim id="apx_neg_periods" bare /> of those half-hours had negative prices.
          </li>
          <li>
            <strong>Illustrations, not savings.</strong> Not revenue, a bill, avoided fossil generation, or money saved by GENCO. The AC reference computes these numbers;{" "}
            <a href="#/explore/value">exact values and method</a>.
          </li>
        </ul>

        <div className="challenge reveal">
          <div className="challenge-text">
            <h3 className="challenge-h">Why the grid's response matters</h3>
            <p>
              Solar output changes how electricity flows through a network, not only how much is imported. As clouds move, generation rises and falls, and the whole network responds. As more renewable generation connects, operators need to anticipate those responses to plan storage and flexibility, and to make room for more of it.
            </p>
            <p>
              A clear sky cannot be engineered, so no grid model can recover energy that clouds blocked. Curtailment, when available renewable output cannot be accepted, is a different problem, and this study did not measure it.
            </p>
          </div>
          <ul className="challenge-list" aria-label="What changes in the network when solar output changes">
            <li>
              <strong>Imports</strong> from the wider grid
            </li>
            <li>
              <strong>Power flows</strong> on each line
            </li>
            <li>
              <strong>Voltages</strong> at each substation
            </li>
            <li>
              <strong>Congestion:</strong> the headroom left on each circuit
            </li>
            <li>
              <strong>Storage and flexibility</strong> decisions
            </li>
            <li>
              <strong>Room for more</strong> renewable connections
            </li>
          </ul>
        </div>

        <div className="vision reveal" aria-labelledby="vision-h">
          <h3 id="vision-h" className="vision-h">
            From forecasting the weather to preparing the grid
          </h3>
          <p className="vision-lead">What if tomorrow's solar generation could be anticipated, along with how the network would respond, before the clouds arrive?</p>
          <p className="vision-p">
            Satellites such as Meteosat show where clouds are and how they move; weather prediction extends that view to the day ahead. Combined with a model of the network's response, such forecasts could let operators examine tomorrow's conditions and plan storage, flexible generation and demand in advance. Cloud2Grid researches one building block of that chain.
          </p>
          <ol className="vision-steps" aria-label="A possible future chain, from weather to grid operations">
            <li data-step="weather">
              <VIcon kind="weather" />
              <span className="vs-n">1</span>
              <strong>Anticipate the weather</strong>
              <span className="vs-d">Satellite cloud motion for the next few hours; numerical weather prediction for the day ahead. Uncertainty grows with the horizon.</span>
              <span className="vs-tag">Existing forecasting · not part of this study</span>
            </li>
            <li data-step="generation">
              <VIcon kind="generation" />
              <span className="vs-n">2</span>
              <strong>Forecast renewable output</strong>
              <span className="vs-d">A PV model turns forecast irradiance into expected output, plant by plant. Wind would need its own forecasts and models.</span>
              <span className="vs-tag">Cloud2Grid converts past satellite irradiance, not forecasts</span>
            </li>
            <li data-step="response" className="is-ours">
              <VIcon kind="response" />
              <span className="vs-n">3</span>
              <strong>Predict the grid's response</strong>
              <span className="vs-d">Imports and exports, line flows, voltages, circuit loading and possible constraint violations.</span>
              <span className="vs-tag">What Cloud2Grid investigates: can a grid foundation model learn this response?</span>
            </li>
            <li data-step="planning" className="is-future">
              <VIcon kind="planning" />
              <span className="vs-n">4</span>
              <strong>Plan operations</strong>
              <span className="vs-d">When to charge or discharge storage, shift flexible demand, schedule imports or dispatchable generation, and manage constraints, chosen by a separate decision-support layer.</span>
              <span className="vs-tag">Future application · not demonstrated</span>
            </li>
          </ol>
          <div className="vision-cols">
            <div className="vision-example">
              <p className="vision-k">An illustrative day ahead</p>
              <p>
                Tomorrow's forecast shows a sunny morning and thick cloud in the afternoon. A future system could forecast solar output across the network, predict how flows and voltages change, flag when storage or flexible generation would be needed, and test operating plans before the afternoon arrives. On a very sunny day it could flag when to charge storage or shift demand to take up the output, which under suitable conditions could help accept more renewable power and reduce curtailment.
              </p>
              <p className="vision-note">The day-ahead horizon is illustrative. Better planning could only help accept output that is available; it cannot recover sunlight that clouds block.</p>
            </div>
            <div className="vision-results">
              <p className="vision-k">Why our results matter for this</p>
              <p>
                A model for step 3 must get both the operating state and how it changes with solar right. E5b came closest on the state but barely responds to solar (<Claim id="slope_E5b" />). E5d reproduced the response, line flows included (median branch error <Claim id="branch_resp_E5c" bare /> → <Claim id="branch_resp_E5d" />, E5c → E5d), but its import is <Claim id="bias_E5d" /> off and only one of three seeds learned it this well. On Aylesbury East the response replicated in <Claim id="g2_D_ok_seeds" bare /> seeds, on synthetic states only. <strong>Accurate responses alone do not make safe decisions.</strong>
              </p>
            </div>
          </div>
          <div className="vision-limits">
            <p className="vision-k">Not demonstrated by Cloud2Grid</p>
            <p>
              Forecasting clouds, solar output or grid states at any horizon; real-time control; better dispatch or storage schedules; avoided curtailment; fossil-fuel or emissions reductions; or savings delivered by GENCO. The values above are reconstructed past scenarios for one plant, not what a forecasting system would earn. An operational system would also need demand forecasts, the current topology and constraints, storage state, asset availability, market rules and uncertainty handling. Any future GENCO-based system would need to be benchmarked against AC power flow and linear-sensitivity methods; on Sundon, AC power flow is already accurate and inexpensive.
            </p>
          </div>
        </div>
      </section>

      <section className="research" aria-labelledby="research-h">
        <div className="research-text reveal">
          <h2 id="research-h" className="research-h">
            What GENCO learned: two models, two different strengths
          </h2>
          <p>GENCO is a grid foundation model pretrained on synthetic networks. We fine-tuned it on synthetic states only, then evaluated it on real operating conditions it had never seen. On Sundon it first predicted power flowing the wrong way.</p>
          <p className="research-bridge">One historical day illustrates the mechanism. Thousands of reconstructed operating states test the models. A second network tests whether response-aware learning replicates, under synthetic conditions.</p>
          <ol className="findings">
            <li className="finding" data-finding="1">
              <span className="finding-k">Finding 1 · learning the grid state</span>
              <ScopeMark kind="aggregate">
                Sundon · <Claim id="n_states" bare /> reconstructed states
              </ScopeMark>
              <p>
                Mean import bias <Claim id="bias_zero_shot" /> (original GENCO) → <Claim id="bias_E5b" /> (E5b). <strong>E5b is the strongest model on most absolute-state metrics.</strong>
              </p>
            </li>
            <li className="finding" data-finding="2">
              <span className="finding-k">Finding 2 · learning the solar response</span>
              <ScopeMark kind="aggregate">Sundon · E5c → E5d · the same states</ScopeMark>
              <p>
                Fitted solar sensitivity <Claim id="slope_E5c" bare /> (E5c) → <Claim id="slope_E5d" /> (E5d); the AC reference on the reconstructed network gives <Claim id="slope_AC" bare />. <strong>E5d recovered the physical response</strong>, but its import bias is <Claim id="bias_E5d" />, and only one of its three training seeds learned the response this well.
              </p>
            </li>
            <li className="finding" data-finding="3">
              <span className="finding-k">Finding 3 · testing another topology</span>
              <ScopeMark kind="synthetic">Aylesbury East · synthetic AC states only</ScopeMark>
              <p>
                On a separately trained <Claim id="g2_buses" bare />-bus network, the share of the AC solar response recovered was <Claim id="g2_C_pv_slope_ratio" bare /> with ordinary fine-tuning and <Claim id="g2_D_pv_slope_ratio_ok" bare /> with response-aware training, in <Claim id="g2_D_ok_seeds" bare /> seeds: ratios, not MW per MW. Its real-data reconstruction failed validation, so real operation there was not tested.
              </p>
            </li>
          </ol>
          <p className="research-close">
            <strong>Not one model improving on every metric:</strong> no model yet gets both the amount and the response right.
          </p>
          <a className="btn btn-primary" href="#/explore/journey?stage=E5b">
            Explore the five stages
          </a>
        </div>
        <div className="research-figure reveal">
          <p className="research-figure-k">Finding 1 in one picture: the average import of each Sundon stage</p>
          <ImportAxis rows={["zero_shot", "E5", "E5b", "E5c", "E5d"]} />
        </div>
      </section>

      <section className="moments" aria-labelledby="moments-h">
        <h2 id="moments-h" className="moments-h reveal">
          The chain in five moments
        </h2>
        <p className="moments-sub reveal">Five numbers from four kinds of evidence. Each says where it comes from; they are not one experiment.</p>
        <ul className="moments-list">
          {MOMENTS.map((m, i) => (
            <li key={m.ch} className="reveal" style={{ transitionDelay: `${i * 70}ms` }}>
              <a href={`#/experience/${m.ch}`} className="moment">
                <span className="moment-name">{m.name}</span>
                <span className="moment-line">{m.line}</span>
                <span className="moment-fig">
                  <Claim id={m.claim} />
                </span>
                <span className="moment-scope">
                  <ScopeMark kind={m.scope}>{m.where}</ScopeMark>
                </span>
              </a>
            </li>
          ))}
        </ul>
      </section>

      <SiteFooter />
    </div>
  );
}

export function SiteFooter() {
  const att = useData<{ footer: string }>("attribution.json");
  useReveal([]);
  return (
    <footer className="site-foot">
      <p className="foot-name reveal" aria-hidden="true">
        Cloud2Grid
      </p>
      <div className="foot-row">
        <ul className="foot-places">
          <li>
            <a href={REPO} target="_blank" rel="noopener">
              Source code
            </a>
          </li>
          <li>
            <a href={`${REPO}/releases/tag/cloud2grid-models-v1`} target="_blank" rel="noopener">
              Frozen models
            </a>
          </li>
          <li>
            <a href="#/explore/data">Data and licences</a>
          </li>
          <li>
            <a href="https://cloud2grid.streamlit.app/" target="_blank" rel="noopener">
              Original Streamlit explorer (alternative)
            </a>
          </li>
        </ul>
        <p className="foot-credits">
          {att.data?.footer ?? ""} Contains BMRS data © Elexon Limited copyright and database right 2024.
        </p>
      </div>
    </footer>
  );
}

/** Small line icons for the four steps of the possible future chain (decorative; the step titles carry the meaning). */
function VIcon({ kind }: { kind: "weather" | "generation" | "response" | "planning" }) {
  return (
    <svg className="vs-icon" viewBox="0 0 32 32" width="32" height="32" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      {kind === "weather" && (
        <>
          <circle cx="12" cy="11" r="4.5" />
          <path d="M12 2.5v2M3.5 11h2M6 5l1.4 1.4M18 5l-1.4 1.4" />
          <path d="M10 25h13a4.5 4.5 0 0 0 0-9 6 6 0 0 0-11.4 1.8A3.6 3.6 0 0 0 10 25z" />
        </>
      )}
      {kind === "generation" && (
        <>
          <path d="M5 20l4-11h16l4 11z" />
          <path d="M11.5 9L10 20M17 9v11M22.5 9L24 20M7 14.5h20" />
          <path d="M17 20v6M12 26h10" />
        </>
      )}
      {kind === "response" && (
        <>
          <circle cx="6" cy="8" r="2.5" />
          <circle cx="26" cy="8" r="2.5" />
          <circle cx="16" cy="16" r="2.5" />
          <circle cx="8" cy="25" r="2.5" />
          <circle cx="24" cy="25" r="2.5" />
          <path d="M8 9.5l6 5M24 9.5l-6 5M14.5 18l-5 5M17.5 18l5 5M8.5 8h15" />
        </>
      )}
      {kind === "planning" && (
        <>
          <rect x="5" y="6" width="22" height="21" rx="2" />
          <path d="M5 12h22M11 3.5v5M21 3.5v5" />
          <path d="M10 19l3 3 6-6" />
        </>
      )}
    </svg>
  );
}

/** The local fleet's satellite-derived PV over the observed morning: the link between the frames and the grid. */
function SolarSpark({ ev }: { ev: EventData }) {
  const v = ev.fleet_pv_mw as number[];
  const cap = ev.active_pv_capacity_mw;
  const W = 100;
  const H = 100;
  const x = (i: number) => 6 + (i / (v.length - 1)) * (W - 12);
  const y = (p: number) => 70 - (p / cap) * 40; // the middle band of the tile; title above, figures below
  const d = v.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(2)},${y(p).toFixed(2)}`).join("");
  const i11 = ev.frames.findIndex((f) => f.t.endsWith("11:00:00Z"));
  const i1130 = ev.frames.findIndex((f) => f.t.endsWith("11:30:00Z"));
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={`Satellite-derived solar output of the local fleet, every 15 minutes from 08:45 to 12:15 UTC, rising from ${v[i11].toFixed(2)} MW at 11:00 to ${v[i1130].toFixed(2)} MW at 11:30`}>
      <line x1={0} x2={W} y1={y(cap)} y2={y(cap)} className="spark-cap" vectorEffect="non-scaling-stroke" />
      <rect x={x(i11)} width={x(i1130) - x(i11)} y={26} height={48} className="spark-band" />
      <path d={d} className="spark-line" vectorEffect="non-scaling-stroke" pathLength={1} />
    </svg>
  );
}

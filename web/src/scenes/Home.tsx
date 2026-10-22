import { NetworkView } from "../components/NetworkView";
import { ThemeToggle } from "../components/theme";
import { Claim, DataError, Loading, asset, useData } from "../data/load";
import { hhmm } from "../data/format";
import type { EventData, Network } from "../data/types";
import { GUIDED_SECONDS } from "./beats";
import { ImportAxis } from "../components/journey";
import { useReveal } from "../components/reveal";
import { Wordmark } from "../components/Wordmark";

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

const MOMENTS: { ch: string; name: string; line: string; claim: string; prov: string }[] = [
  { ch: "clouds", name: "Clouds", line: "Real Meteosat images, fifteen minutes apart, watch the deck break.", claim: "n_frames", prov: "observations" },
  { ch: "energy", name: "Energy", line: "Estimated solar output across the local fleet, 11:00 to 11:30.", claim: "fleet_pv_delta", prov: "derived" },
  { ch: "grid", name: "Grid", line: "Freeze the network at 11:00 and give one plant a clear sky.", claim: "cf_AC_1100", prov: "simulated import change" },
  { ch: "genco", name: "GENCO", line: "From the wrong flow direction to the physical solar response, through four synthetic-data fine-tuning steps; then the same pattern on a second network.", claim: "slope_E5d", prov: "E5d, fitted over all reconstructed real states" },
  { ch: "value", name: "Value", line: "The clouds' extra import across the day, at historical prices.", claim: "day_cloud_gbp", prov: "illustrative" },
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
          <a href="#/experience?play=1">The experience</a>
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
            Estimated solar<span>local fleet, 08:45–12:15</span>
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
              <strong>GENCO, tested and adapted</strong> in four synthetic-data steps, and replicated on a second network
            </li>
          </ul>
          <div className="home-stand">
            <p className="lead question">What happens when a grid foundation model trained on synthetic networks encounters a real electricity grid affected by satellite-observed weather?</p>
            <p className="sublead">On 15 June 2024, clouds cleared above a real UK electricity network. Follow what happened, from sunlight to electricity to potential economic value.</p>
            <div className="home-actions">
              <a className="btn btn-primary btn-large" href="#/experience?play=1">
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
              About {GUIDED_SECONDS} seconds; pause, skip or step at your own pace. Or <a href="#/explore">explore the science</a>.
            </p>
          </div>
        </div>
      </section>

      <section className="research" aria-labelledby="research-h">
        <div className="research-text reveal">
          <h2 id="research-h" className="research-h">
            The research: teaching GENCO this grid
          </h2>
          <p>
            GENCO is a grid foundation model pretrained on synthetic networks. On the real Sundon network it first predicted power flowing the wrong way. Successive synthetic-data experiments taught it the network, then how the network responds to solar.
          </p>
          <p>
            <strong>Two models, two different strengths.</strong> Envelope tuning (E5b) brought the import bias from <Claim id="bias_zero_shot" /> to <Claim id="bias_E5b" />. Response-aware training (E5d) moved the solar response from <Claim id="slope_E5c" bare /> (E5c) to <Claim id="slope_E5d" /> (physics <Claim id="slope_AC" bare />), but its import bias is <Claim id="bias_E5d" />. No model yet does both: a research result, not an operational one. On a second network the pattern recurred, on synthetic states.
          </p>
          <a className="btn btn-primary" href="#/explore/journey?stage=E5b">
            Explore the five stages
          </a>
        </div>
        <div className="research-figure reveal">
          <ImportAxis rows={["zero_shot", "E5", "E5b", "E5c", "E5d"]} />
        </div>
      </section>

      <section className="moments" aria-labelledby="moments-h">
        <h2 id="moments-h" className="moments-h reveal">
          The chain in five moments
        </h2>
        <ul className="moments-list">
          {MOMENTS.map((m, i) => (
            <li key={m.ch} className="reveal" style={{ transitionDelay: `${i * 70}ms` }}>
              <a href={`#/experience/${m.ch}`} className="moment">
                <span className="moment-name">{m.name}</span>
                <span className="moment-line">{m.line}</span>
                <span className="moment-fig">
                  <Claim id={m.claim} />
                  <span className="moment-prov">{m.prov}</span>
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
            <a href="https://cloud2grid.streamlit.app/" target="_blank" rel="noopener">
              Scientific Explorer (Streamlit)
            </a>
          </li>
          <li>
            <a href="#/explore/data">Data and licences</a>
          </li>
        </ul>
        <p className="foot-credits">
          {att.data?.footer ?? ""} Contains BMRS data © Elexon Limited copyright and database right 2024.
        </p>
      </div>
    </footer>
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

import { useCallback, useEffect, useRef, useState } from "react";
import { Filmstrip } from "../components/SatelliteView";
import { Wordmark } from "../components/Wordmark";
import { ImportAxis, PbeStrip, Scoreboard, TwoQuestions } from "../components/journey";
import { Question, ScopeTag } from "../components/Scope";
import { ThemeToggle } from "../components/theme";
import { TimeRuler } from "../components/TimeRuler";
import { useReducedMotion } from "../components/hooks";
import { Claim, DataError, Loading } from "../data/load";
import { hhmm, num, skyWord } from "../data/format";
import { BEATS, CHAPTERS, GUIDED_SECONDS, firstBeat, type ChapterId } from "./beats";
import { COPY, PROLOGUE } from "./copy";
import { Finale } from "./Finale";
import {
  DayChart,
  GridHud,
  HalfHourLedger,
  PvCurve,
  ResponseBars,
  SatelliteView,
  SeasonView,
  SlopeScatter,
  Waterfall,
  useCloudImpact,
  useFrameIndex,
  useSceneData,
  type Camera,
  type Scenario,
} from "./visuals";

const H = (hm: string) => `2024-06-15T${hm}:00Z`;

export function Experience({ chapter, autoplay }: { chapter: string | null; autoplay: boolean }) {
  const rm = useReducedMotion();
  const { ev, net, error } = useSceneData();
  const ci = useCloudImpact();
  const fi = useFrameIndex(ev);
  const start = chapter && CHAPTERS.some((c) => c.id === chapter) ? firstBeat(chapter as ChapterId) : chapter === "finale" ? BEATS.length - 1 : 0;
  const [beat, setBeat] = useState(start);
  const [playing, setPlaying] = useState(autoplay && !rm);
  const [frame, setFrame] = useState(0);
  const [camera, setCamera] = useState<Camera>("wide");
  const [wipe, setWipe] = useState(50);
  const [slot, setSlot] = useState(H("11:00"));
  const [freeze, setFreeze] = useState<"off" | "frozen" | "cf">("off");
  const [scenario, setScenario] = useState<Scenario | "both">("observed");
  const [sel, setSel] = useState(12); // 11:00 half-hour of the 24 valued periods
  const [revealed, setRevealed] = useState(0);
  const b = BEATS[beat];
  const live = useRef<HTMLDivElement>(null);

  // ------------------------------------------------------------ per-beat programme (frozen values only)
  useEffect(() => {
    if (!ev) return;
    const at: [number, () => void][] = [];
    const f = (hm: string) => fi.get(hm) ?? 0;
    setRevealed(0);
    switch (b.id) {
      case "prologue":
        setCamera("wide");
        setFrame(0);
        break;
      case "c-sky":
        setFrame(0);
        setCamera("wide");
        at.push([450, () => setCamera("sundon")]);
        break;
      case "c-play":
        setCamera("sundon");
        if (rm) setFrame(f("11:00"));
        else {
          setFrame(0);
          for (let i = 1; i <= f("11:00"); i++) at.push([i * 620, () => setFrame(i)]);
        }
        break;
      case "c-clear":
        setCamera("sundon");
        setFrame(f("11:00"));
        at.push([1300, () => setFrame(f("11:15"))], [2600, () => setFrame(f("11:30"))]);
        break;
      case "e-wipe":
        setCamera("sundon");
        setFrame(f("11:00"));
        setWipe(rm ? 50 : 94);
        at.push([350, () => setWipe(50)]);
        break;
      case "e-curve":
        setFrame(f("11:30"));
        break;
      case "g-states":
        setFreeze("off");
        setSlot(H("11:00"));
        at.push([3200, () => setSlot(H("11:30"))]);
        break;
      case "g-why":
        setFreeze("off");
        setSlot(H("11:30"));
        break;
      case "g-freeze":
        setSlot(H("11:00"));
        setFreeze("frozen");
        at.push([2600, () => setFreeze("cf")]);
        break;
      case "v-value":
        setScenario("both");
        setSel(12);
        break;
      case "v-half":
        setScenario("observed");
        setSel(12);
        at.push([2200, () => setScenario("clear")], [4200, () => setScenario("both")]);
        break;
    }
    at.push([0, () => setRevealed(1)], [1400, () => setRevealed(2)], [2800, () => setRevealed(3)], [4600, () => setRevealed(4)]);
    const timers = at.map(([t, fn]) => setTimeout(fn, rm ? 0 : t));
    return () => timers.forEach(clearTimeout);
  }, [b.id, ev, fi, rm]);

  // ------------------------------------------------------------ guided replay
  useEffect(() => {
    if (!playing || b.dwell === 0) return;
    const t = setTimeout(() => setBeat((x) => Math.min(BEATS.length - 1, x + 1)), b.dwell);
    return () => clearTimeout(t);
  }, [playing, beat, b.dwell]);
  useEffect(() => {
    if (beat === BEATS.length - 1) setPlaying(false);
  }, [beat]);

  // ------------------------------------------------------------ URL follows the chapter (no history spam)
  useEffect(() => {
    history.replaceState(null, "", `#/experience/${b.ch}`);
  }, [b.ch]);

  const go = useCallback((i: number, keepPlaying = false) => {
    setBeat(Math.max(0, Math.min(BEATS.length - 1, i)));
    if (!keepPlaying) setPlaying(false);
  }, []);
  const take = <T,>(fn: (v: T) => void) => (v: T) => {
    setPlaying(false);
    fn(v);
  };

  // ------------------------------------------------------------ keyboard
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.key === "ArrowRight" || e.key === "PageDown") go(beat + 1);
      else if (e.key === "ArrowLeft" || e.key === "PageUp") go(beat - 1);
      else if (e.key === " " || e.key === "k") {
        e.preventDefault();
        setPlaying((p) => !p);
      } else if (e.key === "Home") go(0);
      else if (e.key === "End") go(BEATS.length - 1);
      else if (e.key === "Escape") location.hash = "/";
    };
    addEventListener("keydown", on);
    return () => removeEventListener("keydown", on);
  }, [beat, go]);

  if (error) return <DataError what="the 15 June event" detail={error} />;
  if (!ev || !net) return <Loading />;

  const chIdx = CHAPTERS.findIndex((c) => c.id === b.ch);
  const chapterBeats = BEATS.filter((x) => x.ch === b.ch);
  const local = chapterBeats.indexOf(b);
  const plant = ev.assets.find((a) => a.id === ev.plant_id)!;
  const frameT = ev.frames[frame].t;
  const rulerT = b.time.t ?? (b.ch === "clouds" ? frameT : b.id === "g-states" ? slot : null);
  const copy = COPY[b.id];
  const isFinale = b.ch === "finale";

  return (
    <div className={`exp ch-${b.ch} beat-${b.id}`} data-beat={b.id}>
      <header className="exp-head">
        <Wordmark />
        <nav className="chapters" aria-label="Chapters">
          {CHAPTERS.map((c, i) => {
            const done = i < chIdx || isFinale;
            const on = i === chIdx;
            const frac = on ? (local + 1) / chapterBeats.length : done ? 1 : 0;
            return (
              <button key={c.id} className={`chapter ${on ? "on" : ""} ${done ? "done" : ""}`} onClick={() => go(firstBeat(c.id))} aria-current={on ? "step" : undefined}>
                <span className="chapter-name">{c.name}</span>
                <span className="chapter-bar">
                  <span style={{ width: `${frac * 100}%` }} />
                </span>
              </button>
            );
          })}
        </nav>
        <div className="exp-actions">
          <button className="btn-text" onClick={() => setPlaying((p) => !p)} aria-pressed={playing} disabled={isFinale}>
            {playing ? "Pause" : "Play"}
          </button>
          <ThemeToggle />
          <a className="btn-text" href="#/explore">
            Explore the science
          </a>
        </div>
      </header>

      {isFinale ? (
        <Finale onReplay={() => go(0)} />
      ) : (
        <main className="stage">
          <section className="stage-text" aria-live="polite" ref={live}>
            <div key={b.id} className="beat-text">
              {b.id === "prologue" ? (
                <div className="prologue">
                  {PROLOGUE.map((s, i) => (
                    <p key={i} className={`statement ${i === 3 ? "is-question" : ""}`} style={{ animationDelay: `${rm ? 0 : i * 1500}ms` }}>
                      {s}
                    </p>
                  ))}
                </div>
              ) : (
                <>
                  {b.scope && <ScopeTag {...b.scope} />}
                  {copy.h && <h1 className="beat-h">{copy.h}</h1>}
                  {copy.lead && <p className="beat-lead">{copy.lead}</p>}
                  <p className="beat-body">{copy.body}</p>
                </>
              )}
              <BeatExtra id={b.id} frame={frame} plant={plant} frameT={frameT} slot={slot} freeze={freeze} revealed={revealed} scenario={scenario} setScenario={take(setScenario)} ci={ci.data} sel={sel} />
            </div>
            <div className="stage-controls">
              <button className="btn btn-secondary" onClick={() => go(beat - 1)} disabled={beat === 0}>
                Back
              </button>
              <button className="btn btn-primary" onClick={() => go(beat + 1)}>
                {beat === BEATS.length - 2 ? "Finish" : "Next"}
              </button>
              {playing && <span className="dwell" key={beat} style={{ animationDuration: `${b.dwell}ms` }} aria-hidden="true" />}
              <a className="btn-text detail-link" href={`#${CHAPTERS[chIdx].explore}`}>
                {CHAPTERS[chIdx].exploreLabel}
              </a>
            </div>
          </section>

          <section className="stage-visual" aria-label="Visual">
            {(b.ch === "clouds" || b.id === "e-wipe") && (
              <>
                <SatelliteView
                  event={ev}
                  frame={b.id === "e-wipe" ? (fi.get("11:00") ?? 9) : frame}
                  compare={b.id === "e-wipe" ? (fi.get("11:30") ?? 11) : undefined}
                  wipe={wipe}
                  onWipe={take(setWipe)}
                  camera={camera}
                  focusX={b.id === "prologue" && typeof window !== "undefined" && window.innerWidth > 900 ? 0.71 : 0.5}
                  network={net}
                  showPlants={b.id !== "prologue"}
                  highlightPlant={b.id === "c-clear"}
                  showBox
                  className={b.id === "e-wipe" ? "is-wipe" : ""}
                />
                {(b.id === "c-play" || b.id === "c-clear") && <Filmstrip event={ev} index={frame} onPick={take(setFrame)} />}
              </>
            )}
            {b.id === "e-curve" && (
              <div className="energy-curve">
                <PvCurve ev={ev} upto={fi.get("11:30") ?? 11} mark={[fi.get("11:00") ?? 9, fi.get("11:30") ?? 11]} />
              </div>
            )}
            {b.ch === "grid" && <GridHud ev={ev} net={net} slot={slot} freeze={freeze} highlight={b.id === "g-why" ? ["loads", "battery", "pv"] : freeze !== "off" ? ["plant"] : []} />}
            {b.id === "i-cf" && (
              <ResponseBars stage={revealed < 3 ? "e5c" : "e5d"}>
                <Question n={2} />
              </ResponseBars>
            )}
            {b.id === "i-slope" && (
              <SlopeScatter>
                <Question n={2} />
              </SlopeScatter>
            )}
            {b.id === "j-shift" && (
              <div className="journey-stage">
                <TwoQuestions />
              </div>
            )}
            {b.id === "j-zero" && (
              <div className="journey-stage">
                <Question n={1} />
                <ImportAxis rows={["zero_shot"]} withAC hidden={revealed < 2 ? ["zero_shot"] : []} focus="zero_shot" />
              </div>
            )}
            {b.id === "j-network" && (
              <div className="journey-stage">
                <Question n={1} />
                <ImportAxis rows={["zero_shot", "E5", "E5b"]} hidden={revealed < 2 ? ["E5", "E5b"] : revealed < 3 ? ["E5b"] : []} focus={revealed < 3 ? "E5" : "E5b"} />
                <PbeStrip rows={["zero_shot", "E5", "E5b"]} hidden={revealed < 2 ? ["E5", "E5b"] : revealed < 3 ? ["E5b"] : []} />
              </div>
            )}
            {b.id === "j-two" && (
              <div className="journey-stage">
                <Scoreboard focus={["E5b", "E5d"]} />
              </div>
            )}
            {b.ch === "value" &&
              (!ci.data ? (
                ci.error ? <DataError what="the economic study" detail={ci.error} /> : <Loading />
              ) : b.id === "v-season" ? (
                <SeasonView ci={ci.data}>
                  <p className="season-note">
                    Illustrative, retrospective valuations from AC reconstructions: not actual costs, savings, revenue or forecasts. GENCO does not predict prices; a national wholesale price is not a local nodal price. The other <Claim id="other_pv_capacity" /> of local solar sits inside the reconstructed loads and was never varied. One half-hour (13 April, 07:00 UTC) has no APX price at source; its value, at most £4.14, is omitted. Contains BMRS data © Elexon Limited copyright and database right 2024.
                  </p>
                </SeasonView>
              ) : (
                <DayChart ci={ci.data} scenario={scenario} sel={sel} onSel={take(setSel)}>
                  {b.id === "v-half" ? (
                    <HalfHourLedger ci={ci.data} i={sel} />
                  ) : (
                    <p className="season-note">
                      Illustrative, retrospective valuations: historical Elexon APX prices applied to AC-reconstructed energy. Not actual costs, savings, bills or forecasts; GENCO does not predict prices. Only the 6 MW plant is varied. Contains BMRS data © Elexon Limited copyright and database right 2024.
                    </p>
                  )}
                </DayChart>
              ))}
          </section>
        </main>
      )}

      <footer className="exp-foot">
        <TimeRuler mode={b.time.mode} t={rulerT} frames={ev.frames.map((f) => f.t)} gridSlots={ev.grid_slots} />
        <p className="exp-hint">
          <kbd>←</kbd> <kbd>→</kbd> move · <kbd>Space</kbd> {playing ? "pause" : "play"} · <kbd>Esc</kbd> leave · guided replay ≈ {GUIDED_SECONDS} s · every number comes from frozen, verified data
        </p>
      </footer>
    </div>
  );
}

// ------------------------------------------------------------ text-pane extras per beat
function BeatExtra(p: {
  id: string;
  frame: number;
  plant: { clearsky_index: (number | null)[] | null; p_mw: (number | null)[] };
  frameT: string;
  slot: string;
  freeze: "off" | "frozen" | "cf";
  revealed: number;
  scenario: Scenario | "both";
  setScenario: (s: Scenario | "both") => void;
  ci: import("../data/types").CloudImpact | null;
  sel: number;
}) {
  const kc = p.plant.clearsky_index?.[p.frame] ?? null;
  switch (p.id) {
    case "c-sky":
    case "c-play":
    case "c-clear":
      return (
        <dl className="readouts">
          <div>
            <dt>Observation</dt>
            <dd className="big">{hhmm(p.frameT)} UTC</dd>
            <dd className="prov">Observed · Meteosat E-View</dd>
          </div>
          <div>
            <dt>Sky over the 6 MW plant</dt>
            <dd className="big">{skyWord(kc)}</dd>
            <dd className="prov">Derived · clear-sky index {num(kc, 2)}</dd>
          </div>
        </dl>
      );
    case "e-wipe":
    case "e-curve":
      return (
        <dl className="readouts readouts-arrow">
          <div>
            <dt>11:00 UTC</dt>
            <dd className="big">
              <Claim id="fleet_pv_1100" />
            </dd>
          </div>
          <div className="arrow" aria-hidden="true">
            →
          </div>
          <div>
            <dt>11:30 UTC</dt>
            <dd className="big">
              <Claim id="fleet_pv_1130" />
            </dd>
          </div>
          <dd className="prov full">Derived · estimated output of the <Claim id="n_pv_plants" bare /> active plants (EUMETSAT LSA SAF + pvlib)</dd>
        </dl>
      );
    case "g-states":
      return (
        <dl className="readouts readouts-arrow">
          <div>
            <dt>Import, 11:00</dt>
            <dd className="big">
              <Claim id="import_ac_1100" />
            </dd>
          </div>
          <div className="arrow" aria-hidden="true">
            →
          </div>
          <div className={p.slot.endsWith("11:30:00Z") ? "" : "pending"}>
            <dt>Import, 11:30</dt>
            <dd className="big">
              <Claim id="import_ac_1130" />
            </dd>
          </div>
          <dd className="prov full">
            Simulated · AC reconstruction · change <Claim id="import_ac_hist_delta" />
          </dd>
        </dl>
      );
    case "g-why":
      return <Waterfall />;
    case "g-freeze":
      return (
        <div className="versus">
          <div className="vs-cell">
            <span className="vs-k">Historical change, 11:00 → 11:30</span>
            <span className="vs-v">
              <Claim id="import_ac_hist_delta" />
            </span>
            <span className="vs-s">everything moved at once</span>
          </div>
          <div className={`vs-cell is-solar ${p.freeze === "cf" ? "" : "pending"}`}>
            <span className="vs-k">Solar only, frozen at 11:00</span>
            <span className="vs-v">
              <Claim id="cf_AC_1100" />
            </span>
            <span className="vs-s">
              import <Claim id="cf_import_ac_obs_1100" /> → <Claim id="cf_import_ac_clear_1100" />, hypothetical
            </span>
          </div>
        </div>
      );
    case "j-zero":
      return (
        <dl className="readouts">
          <div>
            <dt>Original GENCO vs physics</dt>
            <dd className="big">
              <Claim id="bias_zero_shot" />
            </dd>
            <dd className="prov">import offset · average over all real states, not the 11:00 event</dd>
          </div>
          <div>
            <dt>Direction wrong in</dt>
            <dd className="big">
              <Claim id="zero_shot_wrong_sign" />
            </dd>
            <dd className="prov">of real half-hours, on this network</dd>
          </div>
        </dl>
      );
    case "j-network":
      return (
        <dl className="readouts readouts-pair">
          <div className={p.revealed >= 3 ? "" : "pending"}>
            <dt>Average import, E5b</dt>
            <dd className="big">
              <Claim id="import_mean_E5b" />
            </dd>
            <dd className="prov">
              physics <Claim id="import_mean_AC" />, original <Claim id="import_mean_zero_shot" />
            </dd>
          </div>
          <div className={p.revealed >= 3 ? "" : "pending"}>
            <dt>Import bias</dt>
            <dd className="big">
              <Claim id="bias_zero_shot" bare /> → <Claim id="bias_E5b" />
            </dd>
            <dd className="prov">average gap to the physics, original → E5b</dd>
          </div>
          <div className={`span-2 ${p.revealed >= 3 ? "" : "pending"}`}>
            <dt>Power-balance error</dt>
            <dd className="big">
              <Claim id="pbe_zero_shot" bare /> → <Claim id="pbe_E5b" />
            </dd>
            <dd className="prov">how physically consistent the whole predicted grid state is, original → E5b</dd>
          </div>
        </dl>
      );
    case "j-shift":
      return (
        <div className="next-q">
          <span className="next-q-k">This leads to the second question</span>
          <Question n={2} />
        </div>
      );
    case "i-cf":
      return (
        <dl className="readouts readouts-pair">
          <div>
            <dt>Solar input, 11:00</dt>
            <dd className="big">
              <Claim id="plant_pv_obs_1100" bare /> → <Claim id="plant_pv_clear_1100" />
            </dd>
            <dd className="prov">
              observed sky → hypothetical clear sky, <Claim id="plant_pv_cf_delta" />
            </dd>
          </div>
          <div className={p.revealed >= 3 ? "" : "pending"}>
            <dt>Change in grid import, E5d</dt>
            <dd className="big">
              <Claim id="cf_E5d_1100" />
            </dd>
            <dd className="prov">
              physics <Claim id="cf_AC_1100" />, E5c <Claim id="cf_E5c_1100" />
            </dd>
          </div>
        </dl>
      );
    case "i-slope":
      return (
        <dl className="readouts readouts-trio">
          {(
            [
              ["slope_AC", "AC physics"],
              ["slope_E5c", "E5c, ordinary"],
              ["slope_E5d", "E5d, response-aware"],
            ] as const
          ).map(([id, l]) => (
            <div key={id}>
              <dt>{l}</dt>
              <dd className="big">
                <Claim id={id} bare />
              </dd>
            </div>
          ))}
          <dd className="prov full">MW of import per MW of solar: a fitted sensitivity over all real half-hours, not the 11:00 change in MW.</dd>
        </dl>
      );
    case "j-two":
      return (
        <>
          <p className="takeaway">First we taught GENCO the network. Then we taught it the physical response. These are different problems.</p>
          <p className="beat-links">
            <a href="#/explore/journey">How we taught GENCO this network, step by step</a>
            <br />
            <a href="#/explore/models">Metrics, verdicts and frozen-model verification</a>
          </p>
        </>
      );
    case "v-value":
      return (
        <div className="result-card">
          <p className="result-t">
            15 June 2024 · one <Claim id="plant_capacity" bare /> MW plant
          </p>
          <dl className="readouts value-big">
            <div>
              <dt>Extra reconstructed import vs clear sky</dt>
              <dd className="big">
                <Claim id="day_cloud_mwh" />
              </dd>
            </div>
            <div>
              <dt>Illustrative value, APX prices</dt>
              <dd className="big">
                <Claim id="day_cloud_gbp" />
              </dd>
            </div>
            <dd className="prov full">
              <Claim id="day_periods" bare /> evaluated half-hours, <Claim id="day_first" bare />–<Claim id="day_last" bare /> UTC · retrospective, not an actual cost or saving
            </dd>
          </dl>
        </div>
      );
    case "v-half":
      return (
        <>
          <table className="sum" aria-label="The 11:00 half-hour, worked through">
            <tbody>
              <tr>
                <td />
                <td className="sum-v">
                  <Claim id="one_cloud_mw" />
                </td>
                <th scope="row">extra import, observed − clear sky</th>
              </tr>
              <tr>
                <td className="sum-op">×</td>
                <td className="sum-v">0.5 h</td>
                <th scope="row">one settlement period</th>
              </tr>
              <tr className="sum-sub">
                <td className="sum-op">=</td>
                <td className="sum-v">
                  <Claim id="one_cloud_mwh" />
                </td>
                <th scope="row">additional energy</th>
              </tr>
              <tr>
                <td className="sum-op">×</td>
                <td className="sum-v">
                  <Claim id="one_apx" />
                </td>
                <th scope="row">historical APX price, that half-hour</th>
              </tr>
              <tr className="sum-total">
                <td className="sum-op">≈</td>
                <td className="sum-v">
                  <Claim id="one_cloud_gbp" />
                </td>
                <th scope="row">illustrative value of one half-hour</th>
              </tr>
            </tbody>
          </table>
          <p className="part-of">
            One of the <Claim id="day_periods" bare /> half-hours that add up to the day's <Claim id="day_cloud_gbp" />.
          </p>
          <div className="seg" role="radiogroup" aria-label="Scenario">
            {(
              [
                ["observed", "Observed sky"],
                ["clear", "Clear sky (hypothetical)"],
                ["both", "The gap"],
              ] as const
            ).map(([k, l]) => (
              <button key={k} role="radio" aria-checked={p.scenario === k} className={p.scenario === k ? "on" : ""} onClick={() => p.setScenario(k)}>
                {l}
              </button>
            ))}
          </div>
        </>
      );
    case "v-season":
      return (
        <>
          <div className="result-card is-season">
            <p className="result-t">
              April–September 2024 · the same <Claim id="plant_capacity" bare /> MW plant
            </p>
            <dl className="readouts value-big">
              <div>
                <dt>Extra import relative to clear sky</dt>
                <dd className="big">
                  <Claim id="season_cloud_attributed_mwh" />
                </dd>
              </div>
              <div>
                <dt>Illustrative value</dt>
                <dd className="big">
                  <Claim id="season_cloud_attributed_gbp" />
                </dd>
              </div>
              <dd className="prov full">
                <Claim id="season_periods" bare /> evaluated half-hours across <Claim id="season_days" bare /> days
              </dd>
            </dl>
          </div>
          <p className="part-of">Do not scale these numbers to other plants: only this plant is varied.</p>
        </>
      );
    default:
      return null;
  }
}

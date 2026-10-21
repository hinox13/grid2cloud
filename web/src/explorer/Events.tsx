import { useEffect, useState } from "react";
import { Chart, TimeAxis, YAxis, linePath, linear } from "../components/charts";
import { useReducedMotion } from "../components/hooks";
import { NetworkLegend, NetworkView } from "../components/NetworkView";
import { Filmstrip, SatelliteView } from "../components/SatelliteView";
import { DataError, Loading, useData } from "../data/load";
import { MODEL_NAME, MODEL_ORDER, hhmm, ms, num, skyWord } from "../data/format";
import type { EventData, EventIndexRow, ModelId, ModelsData, Network } from "../data/types";
import { RailExtra } from "./Rail";
import { ModelName, PageHead, Prov, Section, Seg, setParams } from "./ui";

export function Events({ params }: { params: URLSearchParams }) {
  const idx = useData<EventIndexRow[]>("events/index.json");
  const net = useData<Network>("network.json");
  const mods = useData<ModelsData>("models.json");
  const [eid, setEid] = useState(params.get("e") ?? "jun15_cloud_clearing");
  const ev = useData<EventData>(`events/${eid}/event.json`);
  const [model, setModel] = useState<ModelId>((params.get("m") as ModelId) ?? "E5d");
  const [mode, setMode] = useState<"flow" | "error">("flow");
  const [zoom, setZoom] = useState(true);
  const [ti, setTi] = useState(0);
  const [playing, setPlaying] = useState(false);
  const rm = useReducedMotion();
  const wantT = params.get("t");

  useEffect(() => {
    if (!ev.data) return;
    const i = wantT ? ev.data.frames.findIndex((f) => hhmm(f.t) === wantT) : 0;
    setTi(Math.max(0, i));
    setPlaying(false);
  }, [ev.data, wantT]);
  useEffect(() => {
    if (!playing || !ev.data) return;
    if (ti >= ev.data.frames.length - 1) {
      setPlaying(false);
      return;
    }
    const t = setTimeout(() => setTi((x) => x + 1), rm ? 400 : 1000);
    return () => clearTimeout(t);
  }, [playing, ti, ev.data, rm]);
  useEffect(() => {
    if (ev.data) setParams("/explore/events", { e: eid, t: hhmm(ev.data.frames[ti].t), m: model });
  }, [eid, ti, model, ev.data]);

  if (idx.error || ev.error || net.error) return <DataError what="the event bundle" detail={(idx.error ?? ev.error ?? net.error)!} />;
  if (!idx.data || !ev.data || !net.data || !mods.data) return <Loading />;
  const E = ev.data;
  const f = E.frames[ti];
  const t = f.t;
  const past = E.grid_slots.filter((s) => ms(s) <= ms(t));
  const g = past.length ? past[past.length - 1] : E.grid_slots[0];
  const gi = E.grid_slots.indexOf(g);
  const held = g === t ? `grid state ${hhmm(g)}` : ms(g) < ms(t) ? `grid state held since ${hhmm(g)}` : `next grid state ${hhmm(g)}`;
  const plant = E.assets.find((a) => a.id === E.plant_id) ?? E.assets[0];
  const kc = plant.clearsky_index?.[ti] ?? null;
  const ghi = plant.ghi_wm2?.[ti] ?? null;
  const acImp = E.summary.AC.import_mw[gi] ?? 0;
  const mImp = E.summary[model].import_mw[gi] ?? 0;
  const info = mods.data.models.find((m) => m.id === model);

  return (
    <>
      <PageHead title="Weather events" lead="Three frozen events, chosen by a pre-registered meteorological ranking (never by model behaviour). Scrub the real 15-minute frames; compare the AC reference with any frozen GENCO version on the same half-hourly grid states." />
      <RailExtra>
        <div className="rail-block">
          <p className="rail-h">Event</p>
          <ul className="rail-events">
            {idx.data.map((x) => (
              <li key={x.event_id}>
                <button
                  className={x.event_id === eid ? "on" : ""}
                  aria-pressed={x.event_id === eid}
                  onClick={() => {
                    setEid(x.event_id);
                    setTi(0);
                  }}
                >
                  <strong>{x.title.split(" — ")[0]}</strong>
                  <span>{x.title.split(" — ")[1]}</span>
                  <span className="re-meta">
                    {x.n_frames} frames · {x.n_grid_slots} grid states
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </RailExtra>
      <div className="ev-controls">
        <label className="field ev-select">
          <span>Event</span>
          <select
            value={eid}
            onChange={(e) => {
              setEid(e.target.value);
              setTi(0);
            }}
          >
            {idx.data.map((x) => (
              <option key={x.event_id} value={x.event_id}>
                {x.title}
              </option>
            ))}
          </select>
        </label>
        <div className="field">
          <span>Grid shown</span>
          <Seg label="Model" value={model} onChange={setModel} options={MODEL_ORDER.map((m) => [m, m === "AC" ? "AC" : MODEL_NAME[m]])} />
        </div>
        <div className="field">
          <span>Branch colour</span>
          <Seg
            label="Branch colour"
            value={mode}
            onChange={setMode}
            options={[
              ["flow", "Loading"],
              ["error", "Error vs AC"],
            ]}
          />
        </div>
      </div>
      <p className="ev-context">
        <strong>{E.title}.</strong> {E.story} <br />
        <ModelName m={model} />: {model === "AC" ? mods.data.ac.about : info?.about}. <em>Result:</em> {model === "AC" ? mods.data.ac.verdict : info?.verdict}.
      </p>

      <Section title="The grid at the selected time">
      <div className="ev-chain" role="group" aria-label="State at the selected time">
        <div>
          <span className="k">
            Real clouds <Prov kind="observed" />
          </span>
          <span className="v">{skyWord(kc)}</span>
          <span className="s">clear-sky index {num(kc, 2)} at the 6 MW plant</span>
        </div>
        <div>
          <span className="k">
            Solar power <Prov kind="derived" />
          </span>
          <span className="v">{num(E.fleet_pv_mw[ti], 2)} MW</span>
          <span className="s">fleet estimate · GHI {num(ghi, 0)} W/m²</span>
        </div>
        <div>
          <span className="k">
            Power grid <Prov kind="simulated" />
          </span>
          <span className="v">{num(acImp, 1)} MW</span>
          <span className="s">AC import · {held}</span>
        </div>
        <div>
          <span className="k">
            GENCO <Prov kind="predicted" />
          </span>
          <span className="v">{model === "AC" ? "—" : `${num(mImp, 1)} MW`}</span>
          <span className="s">{model === "AC" ? "select a model" : `${MODEL_NAME[model]} · error ${num(mImp - acImp, 1, true)} MW`}</span>
        </div>
      </div>

      <div className="ev-stage">
        <figure className="ev-sat">
          <figcaption>
            Meteosat E-View · {hhmm(t)} UTC <Prov kind="observed" />
            <button className="btn-text" onClick={() => setZoom((z) => !z)} aria-pressed={zoom}>
              {zoom ? "Show the whole frame" : "Zoom to Sundon"}
            </button>
          </figcaption>
          <div className="ev-sat-box">
            <SatelliteView event={E} frame={ti} camera={zoom ? "sundon" : "uk"} network={net.data} highlightPlant={zoom} />
          </div>
        </figure>
        <figure className="ev-net">
          <figcaption>
            Sundon network · {model === "AC" ? "AC" : MODEL_NAME[model]} · {held} <Prov kind={model === "AC" ? "simulated" : "predicted"} />
          </figcaption>
          <div className="ev-net-box">
            <NetworkView net={net.data} state={E.flows[model][g]} ac={E.flows.AC[g]} model={model} mode={model === "AC" ? "flow" : mode} title={`Sundon network, ${MODEL_NAME[model]} at ${hhmm(g)} UTC`} interactive />
          </div>
          <NetworkLegend mode={model === "AC" ? "flow" : mode} />
          <p className="note">
            At {hhmm(g)}: max loading {num(E.summary.AC.max_loading_pct[gi], 0)} % (AC)
            {model !== "AC" && (
              <>
                {" "}
                vs {num(E.summary[model].max_loading_pct[gi], 0)} % ({MODEL_NAME[model]}) · power-balance error {num(E.summary[model].PBE_mean[gi], 2)} MVA
              </>
            )}
            . Tap or select a branch for its flow; zoom with + and −.
          </p>
        </figure>
      </div>

      <div className="ev-player">
        <button className="btn btn-secondary" onClick={() => (ti >= E.frames.length - 1 ? (setTi(0), setPlaying(true)) : setPlaying((p) => !p))} aria-pressed={playing}>
          {playing ? "Pause" : "Play"}
        </button>
        <label className="ev-slider">
          <span>
            Time (UTC): <strong>{hhmm(t)}</strong> · 15-minute satellite steps; the grid state is half-hourly and held between
          </span>
          <input type="range" min={0} max={E.frames.length - 1} value={ti} onChange={(e) => (setPlaying(false), setTi(Number(e.target.value)))} aria-valuetext={`${hhmm(t)} UTC`} />
        </label>
      </div>
      <div className="ev-film">
        <Filmstrip event={E} index={ti} onPick={(i) => (setPlaying(false), setTi(i))} camera={zoom ? "sundon" : "uk"} />
      </div>

      </Section>
      <Section title="Timeline of the event">
        <EventTimeline ev={E} model={model} t={t} g={g} />
        <p className="note ev-foot">
          Satellite and solar every 15 minutes; grid states every 30 minutes, the last one held in between, never interpolated. Selection: {E.selection_criteria}.
        </p>
      </Section>
    </>
  );
}

/** PV, import and model error on one time axis; hovering (or touching) any panel reads out that moment. */
export function EventTimeline({ ev, model, t, g }: { ev: EventData; model: ModelId; t: string; g: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const ts = ev.frames.map((f) => ms(f.t));
  const gs = ev.grid_slots.map(ms);
  const x0 = ts[0] - 450_000;
  const x1 = ts[ts.length - 1] + 450_000;
  const ac = ev.summary.AC.import_mw as number[];
  const md = ev.summary[model].import_mw as number[];
  const err = md.map((v, i) => v - ac[i]);
  const all = model === "AC" ? ac : [...ac, ...md];
  const lo = Math.min(0, ...all);
  const hi = Math.max(...all) * 1.1;
  const emax = Math.max(1, ...err.map(Math.abs));
  const pvMax = Math.max(ev.active_pv_capacity_mw, ...(ev.fleet_pv_mw as number[])) * 1.05;
  const desc = `Fleet PV, AC import${model !== "AC" ? ` and ${MODEL_NAME[model]} import with its error` : ""} for ${ev.title}.`;
  // pointer x (chart px) -> nearest real 15-minute frame; the grid state is the last one at or before it
  const pick = (px: number, b: { iw: number }) => {
    const x = linear(x0, x1, 0, b.iw);
    let best = 0;
    ts.forEach((v, i) => {
      if (Math.abs(x(v) - px) < Math.abs(x(ts[best]) - px)) best = i;
    });
    setHover(best);
  };
  const hi_ = hover ?? ts.findIndex((v) => v === ms(t));
  const hT = ev.frames[Math.max(0, hi_)].t;
  const hPast = ev.grid_slots.filter((s) => ms(s) <= ms(hT));
  const hG = hPast.length ? hPast[hPast.length - 1] : ev.grid_slots[0];
  const hGi = ev.grid_slots.indexOf(hG);
  const cursorX = (b: { iw: number }) => linear(x0, x1, 0, b.iw)(ms(hT));
  return (
    <div className="ev-timeline" onPointerLeave={() => setHover(null)}>
      <p className="tl-readout" aria-live="polite">
        <strong>{hhmm(hT)} UTC</strong> · fleet PV {num(ev.fleet_pv_mw[Math.max(0, hi_)], 2)} MW (derived) · AC import {num(ac[hGi], 1)} MW (grid state {hhmm(hG)})
        {model !== "AC" && (
          <>
            {" "}
            · {MODEL_NAME[model]} {num(md[hGi], 1)} MW, error {num(err[hGi], 1, true)} MW
          </>
        )}
        <span className="note"> {hover === null ? "· hover or touch the charts" : ""}</span>
      </p>
      <Chart height={150} title="Satellite-derived PV (MW)" desc={desc} margin={{ l: 52, t: 22, b: 22 }} onPointer={pick}>
        {(b) => {
          const x = linear(x0, x1, 0, b.iw);
          const y = linear(0, pvMax, b.ih, 0);
          const xs = ts.map(x);
          return (
            <>
              <YAxis y={y} b={b} n={3} />
              <text className="panel-title" x={0} y={-8}>
                <tspan className="t-pv">Satellite-derived PV, fleet (MW)</tspan> · ◆ HV PV in the grid state
              </text>
              <path d={linePath(xs, (ev.fleet_pv_mw as number[]).map(y)) + `L${xs[xs.length - 1]},${y(0)}L${xs[0]},${y(0)}Z`} className="pv-area" />
              <path d={linePath(xs, (ev.fleet_pv_mw as number[]).map(y))} className="pv-line" />
              {gs.map((s, i) => (
                <rect key={s} x={x(s) - 4} y={y(ev.grid_inputs.hv_pv_mw[i]) - 4} width={8} height={8} transform={`rotate(45 ${x(s)} ${y(ev.grid_inputs.hv_pv_mw[i])})`} className="pv-dot" />
              ))}
              <line x1={x(ms(t))} x2={x(ms(t))} y1={0} y2={b.ih} className="cursor" />
              {hover !== null && <line x1={cursorX(b)} x2={cursorX(b)} y1={0} y2={b.ih} className="hover-line" />}
            </>
          );
        }}
      </Chart>
      <Chart height={190} title="Grid import at Sundon (MW)" desc={desc} margin={{ l: 52, t: 22, b: 22 }} onPointer={pick}>
        {(b) => {
          const x = linear(x0, x1, 0, b.iw);
          const y = linear(lo, hi, b.ih, 0);
          const xs = gs.map(x);
          return (
            <>
              <YAxis y={y} b={b} n={4} />
              <text className="panel-title" x={0} y={-8}>
                Grid import at Sundon (MW) · <tspan className="t-ac">AC reference</tspan>
                {model !== "AC" && <tspan style={{ fill: `var(--m-${model})`, fontWeight: 700 }}> · {MODEL_NAME[model]}</tspan>}
              </text>
              <rect x={x(ms(g)) - 3} width={6} y={0} height={b.ih} className="sel-band" />
              <path d={linePath(xs, ac.map(y))} className="s-ac" />
              {xs.map((v, i) => (
                <circle key={i} cx={v} cy={y(ac[i])} r={4} className="dot-ac" />
              ))}
              {model !== "AC" && (
                <>
                  <path d={linePath(xs, md.map(y))} className="s-model" style={{ stroke: `var(--m-${model})` }} />
                  {xs.map((v, i) => (
                    <circle key={i} cx={v} cy={y(md[i])} r={4} style={{ fill: `var(--m-${model})` }} />
                  ))}
                </>
              )}
              <line x1={x(ms(t))} x2={x(ms(t))} y1={0} y2={b.ih} className="cursor" />
              {hover !== null && <line x1={cursorX(b)} x2={cursorX(b)} y1={0} y2={b.ih} className="hover-line" />}
              {model === "AC" && <TimeAxis x={x} b={b} from={ev.frames[0].t} to={ev.frames[ev.frames.length - 1].t} step={30} />}
            </>
          );
        }}
      </Chart>
      {model !== "AC" && (
        <Chart height={130} title={`${MODEL_NAME[model]} import error vs AC (MW)`} desc={desc} margin={{ l: 52, t: 22, b: 26 }} onPointer={pick}>
          {(b) => {
            const x = linear(x0, x1, 0, b.iw);
            const y = linear(-emax * 1.1, emax * 1.1, b.ih, 0);
            return (
              <>
                <YAxis y={y} b={b} n={4} />
                <text className="panel-title" x={0} y={-8}>
                  {MODEL_NAME[model]} import error vs AC (MW)
                </text>
                {gs.map((s, i) => (
                  <rect key={s} x={x(s) - 10} width={20} y={Math.min(y(0), y(err[i]))} height={Math.abs(y(err[i]) - y(0))} style={{ fill: `var(--m-${model})` }} />
                ))}
                <TimeAxis x={x} b={b} from={ev.frames[0].t} to={ev.frames[ev.frames.length - 1].t} step={30} />
              </>
            );
          }}
        </Chart>
      )}
    </div>
  );
}

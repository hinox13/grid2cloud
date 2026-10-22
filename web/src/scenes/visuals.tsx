import { useMemo } from "react";
import { Bars, Chart, Dots, TimeAxis, YAxis, bandPath, linePath, linear } from "../components/charts";

import { NetworkLegend, NetworkView, type Highlight } from "../components/NetworkView";
import { SatelliteView, type Camera } from "../components/SatelliteView";
import { Claim, Loading, useClaims, useData } from "../data/load";
import { MODEL_EXP, MODEL_NAME, gbp, hhmm, ms, num } from "../data/format";
import type { CloudImpact, EventData, ModelId, Network, PvResponse } from "../data/types";

// ------------------------------------------------------------------ energy: the fleet PV curve
export function PvCurve({ ev, upto, mark }: { ev: EventData; upto: number; mark?: [number, number] }) {
  const ts = ev.frames.map((f) => ms(f.t));
  const cap = ev.active_pv_capacity_mw;
  return (
    <Chart
      height="100%"
      margin={{ l: 46, r: 20, t: 34, b: 30 }}
      title="Estimated solar output of the local PV fleet, 15 June 2024, 08:45 to 12:15 UTC"
      desc={`Satellite-derived estimate every 15 minutes. ${ev.frames.map((f, i) => `${hhmm(f.t)} ${num(ev.fleet_pv_mw[i], 2)} MW`).join("; ")}. Installed capacity ${num(cap, 3)} MW.`}
    >
      {(b) => {
        const x = linear(ts[0] - 300_000, ts[ts.length - 1] + 300_000, 0, b.iw);
        const y = linear(0, 9.6, b.ih, 0);
        const xs = ts.map(x);
        const ys = ev.fleet_pv_mw.map((v, i) => (i <= upto && v !== null ? y(v) : null));
        const area = ev.fleet_pv_mw.slice(0, upto + 1).map((v, i) => `${i ? "L" : "M"}${xs[i]},${y(v ?? 0)}`).join("") + `L${xs[upto]},${y(0)}L${xs[0]},${y(0)}Z`;
        return (
          <>
            <YAxis y={y} b={b} n={5} label="MW, estimated" />
            <TimeAxis x={x} b={b} from={ev.frames[0].t} to={ev.frames[ev.frames.length - 1].t} step={15} every={2} />
            {mark && <rect x={xs[mark[0]]} y={0} width={xs[mark[1]] - xs[mark[0]]} height={b.ih} className="mark-band" />}
            <line x1={0} x2={b.iw} y1={y(cap)} y2={y(cap)} className="ref-line" />
            <text x={6} y={y(cap) - 7} className="ref-label">
              installed {num(cap, 3)} MW
            </text>
            <path d={area} className="pv-area" />
            <path d={linePath(xs, ys)} className="pv-line" />
            {ys.map((v, i) => (v === null ? null : <circle key={i} cx={xs[i]} cy={v} r={i === upto ? 6 : 3.2} className={`pv-dot ${i === upto ? "on" : ""}`} />))}
            {mark &&
              mark.map((i) => (
                <text key={i} x={xs[i] - 12} y={y(ev.fleet_pv_mw[i] ?? 0) + (i === mark[0] ? 26 : -4)} textAnchor="end" className="pt-label">
                  {num(ev.fleet_pv_mw[i], 2)} MW
                </text>
              ))}
          </>
        );
      }}
    </Chart>
  );
}

// ------------------------------------------------------------------ grid: network with an import readout
export function GridHud({
  ev,
  net,
  slot,
  freeze,
  highlight,
}: {
  ev: EventData;
  net: Network;
  slot: string;
  freeze: "off" | "frozen" | "cf";
  highlight: Highlight;
}) {
  const c = useClaims();
  const i = ev.grid_slots.indexOf(slot);
  const imp = ev.summary.AC.import_mw[i] ?? 0;
  // the readout swaps between real values; it never counts through numbers that were not computed
  const shown = freeze === "cf" ? (c.cf_import_ac_clear_1100.value ?? 0) : imp;
  return (
    <div className="grid-hud">
      <div className={`hud-import ${freeze === "cf" ? "is-hypo" : ""}`}>
        <span className="hud-k">{freeze === "cf" ? "Import if the plant had clear sky" : `Import from the national grid, ${hhmm(slot)} UTC`}</span>
        <span className="hud-v swap" key={`${slot}-${freeze === "cf"}`} data-hud-import={num(shown, 1)}>
          {num(shown, 1)}
          <span className="unit"> MW</span>
        </span>
        <span className="hud-p">{freeze === "cf" ? "Hypothetical · AC re-solved, only the 6 MW plant changed" : "Simulated · AC power flow on the reconstructed network"}</span>
      </div>
      <NetworkView net={net} state={ev.flows.AC[slot]} highlight={highlight} dim={freeze !== "off" || highlight.length > 1} title={`Sundon network, AC reconstruction at ${hhmm(slot)} UTC`} />
      <div className="hud-foot">
        <NetworkLegend />
        {freeze !== "off" && <p className="note">Branch flows: the historical 11:00 AC state. The clear-sky re-solve is summarised by its import; its branch flows are not part of the frozen bundle.</p>}
      </div>
    </div>
  );
}

/** Historical change split into the published-regression terms (Grid, "but how much is solar?"). */
export function Waterfall() {
  const c = useClaims();
  const rows = [
    { k: "import_ac_1100", label: "Import at 11:00", kind: "level" },
    { k: "hist_load_term", label: "Demand fell", kind: "term" },
    { k: "hist_battery_term", label: "Battery: charging → supplying", kind: "term" },
    { k: "hist_pv_term", label: "Solar rose", kind: "solar" },
    { k: "hist_remainder", label: "Other (non-linear, losses)", kind: "term" },
    { k: "import_ac_1130", label: "Import at 11:30", kind: "level" },
  ] as const;
  let run = c.import_ac_1100.value ?? 0;
  const max = 60;
  const pct = (v: number) => (v / max) * 100;
  return (
    <figure className="waterfall" aria-label="How the 11:00 to 11:30 import change splits by driver">
      {rows.map((r) => {
        const v = c[r.k].value ?? 0;
        let left: number;
        let width: number;
        if (r.kind === "level") {
          left = 0;
          width = pct(v);
          run = v;
        } else {
          const to = run + v;
          left = pct(Math.min(run, to));
          width = Math.abs(pct(v));
          run = to;
        }
        return (
          <div key={r.k} className={`wf-row wf-${r.kind}`}>
            <span className="wf-label">{r.label}</span>
            <span className="wf-track">
              <span className="wf-bar" style={{ left: `${left}%`, width: `${Math.max(width, 0.4)}%` }} />
            </span>
            <span className="wf-val">
              <Claim id={r.k} />
            </span>
          </div>
        );
      })}
      <figcaption className="note">
        AC import (simulated). Terms: published regression coefficients across <Claim id="n_states" bare /> states × this half-hour's input changes.
      </figcaption>
    </figure>
  );
}

// ------------------------------------------------------------------ intelligence
/**
 * The 11:00 counterfactual as cause and effect: the one input that changes (the plant's output,
 * observed sky → clear sky) and the resulting change in grid import per model. Changes, not levels.
 */
export function ResponseBars({ stage, children }: { stage: "e5c" | "e5d"; children?: React.ReactNode }) {
  const c = useClaims();
  const v = (id: string) => c[id].value ?? 0;
  const px = (mw: number) => `${(mw / 6.5) * 100}%`;
  return (
    <div className="genco-bars" tabIndex={0} role="region" aria-label="The 11:00 counterfactual by model">
      {children}
      <figure className="cf-input" aria-label={`Input: the 6 MW plant goes from ${c.plant_pv_obs_1100.display} MW (observed sky) to ${c.plant_pv_clear_1100.display} MW (hypothetical clear sky)`}>
        <figcaption>
          <strong>The one input that changes</strong> · the 6 MW plant at 11:00; demand, battery and every other input held fixed
        </figcaption>
        <div className="cf-track" aria-hidden="true">
          <span className="cf-span" style={{ left: px(v("plant_pv_obs_1100")), width: px(v("plant_pv_cf_delta")) }}>
            <span className="cf-delta">
              <Claim id="plant_pv_cf_delta" /> of solar
            </span>
          </span>
          <span className="cf-pt is-obs" style={{ left: px(v("plant_pv_obs_1100")) }}>
            <Claim id="plant_pv_obs_1100" />
            <small>observed sky</small>
          </span>
          <span className="cf-pt is-clear" style={{ left: px(v("plant_pv_clear_1100")) }}>
            <Claim id="plant_pv_clear_1100" />
            <small>clear sky (hypothetical)</small>
          </span>
        </div>
      </figure>
      <p className="viz-title cf-out">
        <strong>The result: change in grid import</strong> · how much less power Sundon draws from the national grid. A change, not the import level.
      </p>
      <Bars
        title="Counterfactual import change at 11:00 by model"
        desc={`AC reference ${c.cf_AC_1100.display} MW, E5c ${c.cf_E5c_1100.display} MW, E5d ${stage === "e5d" ? c.cf_E5d_1100.display + " MW" : "not yet shown"}.`}
        domain={[-5.4, 0.6]}
        unit="Change in import, MW · negative = less power drawn from the national grid"
        target={{ value: v("cf_AC_1100"), label: "AC reference" }}
        rows={[
          { key: "AC", label: <ModelLabel name="AC reference" sub="Simulated · reconstructed network" />, value: v("cf_AC_1100"), display: <Claim id="cf_AC_1100" />, colour: "var(--m-AC)" },
          { key: "E5c", label: <ModelLabel name="Ordinary adapted GENCO" sub="E5c · Predicted" />, value: v("cf_E5c_1100"), display: <Claim id="cf_E5c_1100" />, colour: "var(--m-E5c)" },
          { key: "E5d", label: <ModelLabel name="Response-aware GENCO" sub="E5d · Predicted" />, value: v("cf_E5d_1100"), display: <Claim id="cf_E5d_1100" />, colour: "var(--m-E5d)", hidden: stage === "e5c" },
        ]}
      />
    </div>
  );
}

function ModelLabel({ name, sub }: { name: string; sub: string }) {
  return (
    <>
      <span className="ml-name">{name}</span>
      <span className="ml-sub">{sub}</span>
    </>
  );
}

export function SlopeScatter({ models = ["E5c", "E5d"], children }: { models?: string[]; children?: React.ReactNode }) {
  const { data, error } = useData<PvResponse>("pv_response.json");
  const c = useClaims();
  if (error) return <p className="note">The 2,829-state scatter could not be loaded ({error}).</p>;
  if (!data) return <Loading label="Loading 2,829 real states" />;
  return (
    <div className="scatter-wrap" tabIndex={0} role="region" aria-label="Scatter plot, scrolls on small screens">
      {children}
      <p className="viz-title">
        All <Claim id="n_states" bare /> reconstructed real half-hours, <Claim id="states_span" bare />: grid import with the demand and battery effects removed, against the plant's solar output
      </p>
      <div className="scatter-panels">
        {models.map((m) => (
          <Scatter key={m} data={data} model={m} slope={c[`slope_${m}`].value ?? 0} slopeId={`slope_${m}`} ac={c.slope_AC.value ?? 0} />
        ))}
      </div>
      <p className="note">
        Solid line: the model's fitted sensitivity. Dashed: the AC reference for the reconstructed network, <Claim id="slope_AC" />. Sensitivities are MW of import per MW of solar, fitted over all states; they are not the 11:00 response.
      </p>
    </div>
  );
}

function Scatter({ data, model, slope, slopeId, ac }: { data: PvResponse; model: string; slope: number; slopeId: string; ac: number }) {
  const xsRaw = data.pv_injection_mw as number[];
  const ysRaw = data[`partial_${model}`] as number[];
  const name = model === "E5c" ? "Ordinary adapted (E5c)" : model === "E5d" ? "Response-aware (E5d)" : `${MODEL_NAME[model as ModelId]} (${MODEL_EXP[model as ModelId]})`;
  return (
    <div className="scatter">
      <p className="scatter-title" style={{ color: `var(--m-${model})` }}>
        {name}: <Claim id={slopeId} />
      </p>
      <Chart
        height={260}
        margin={{ l: 40, r: 10, t: 8, b: 30 }}
        title={`${name}: import with load and battery removed against solar output`}
        desc={`${xsRaw.length} real half-hourly states. Fitted slope ${num(slope, 2, true)} MW per MW; AC reference ${num(ac, 2, true)}.`}
      >
        {(b) => {
          const x = linear(-0.2, 6.3, 0, b.iw);
          const y = linear(-12, 8, b.ih, 0);
          const clip = (v: number) => Math.max(-12, Math.min(8, v));
          const xs = xsRaw.map(x);
          const ys = ysRaw.map((v) => y(clip(v)));
          return (
            <>
              <YAxis y={y} b={b} n={4} />
              <g className="axis" transform={`translate(0,${b.ih})`}>
                {[0, 2, 4, 6].map((v) => (
                  <text key={v} x={x(v)} y={18} textAnchor="middle">
                    {v}
                  </text>
                ))}
                <text x={b.iw} y={-6} textAnchor="end" className="axis-label">
                  solar, MW
                </text>
              </g>
              <Dots xs={xs} ys={ys} r={1.6} className={`dots m-${model}`} />
              <line x1={x(0)} y1={y(0)} x2={x(6)} y2={y(ac * 6)} className="slope-ac" />
              <line x1={x(0)} y1={y(0)} x2={x(6)} y2={y(slope * 6)} className="slope-fit" style={{ stroke: `var(--m-${model})` }} />
            </>
          );
        }}
      </Chart>
    </div>
  );
}

// ------------------------------------------------------------------ value: the season, a different time scale
const MONTHS = [
  ["Apr", 30],
  ["May", 31],
  ["Jun", 30],
  ["Jul", 31],
  ["Aug", 31],
  ["Sep", 30],
] as const;

/**
 * The extended case study: which days were evaluated (one cell per day, April–September 2024), the day
 * total against the season total on one £ axis, and where 15 June sits among the season's days.
 * Only the published season summary is used; nothing here is scaled or extrapolated.
 */
export function SeasonView({ ci, children }: { ci: CloudImpact; children?: React.ReactNode }) {
  const c = useClaims();
  const v = (id: string) => c[id].value ?? 0;
  const on = new Set(ci.season_dates);
  const season = v("season_cloud_attributed_gbp");
  const dayMax = 3000;
  const dp = (x: number) => `${(x / dayMax) * 100}%`;
  return (
    <div className="season-view" tabIndex={0} role="region" aria-label="The season: evaluated days and values">
      <figure className="cal" aria-label={`Evaluated days, April to September 2024: ${c.season_days.display} days with valued half-hours; 15 June highlighted`}>
        <figcaption>
          <strong>
            <Claim id="season_days" bare /> evaluated days
          </strong>{" "}
          · <Claim id="season_periods" bare /> AC-reconstructed half-hours with an intact state, not every daylight interval
        </figcaption>
        <div className="cal-grid" aria-hidden="true">
          {MONTHS.map(([m, n], mi) => (
            <div key={m} className="cal-row">
              <span className="cal-m">{m}</span>
              {Array.from({ length: 31 }, (_, d) => {
                const iso = `2024-${String(mi + 4).padStart(2, "0")}-${String(d + 1).padStart(2, "0")}`;
                return <i key={d} className={d >= n ? "cal-none" : iso === "2024-06-15" ? "cal-day is-event" : on.has(iso) ? "cal-day is-on" : "cal-day"} />;
              })}
            </div>
          ))}
        </div>
        <p className="cal-key" aria-hidden="true">
          <i className="cal-day is-on" /> evaluated <i className="cal-day" /> not evaluated <i className="cal-day is-event" /> 15 June
        </p>
      </figure>

      <figure className="scale" aria-label={`Illustrative value of the clouds' extra import: 15 June ${c.day_cloud_gbp.display}; April–September ${c.season_cloud_attributed_gbp.display}`}>
        <figcaption>
          <strong>Two time scales, one plant</strong> · illustrative value of the extra import caused by clouds
        </figcaption>
        <div className="scale-row is-day">
          <span className="scale-k">15 June 2024 · <Claim id="day_periods" bare /> half-hours</span>
          <span className="scale-track">
            <span style={{ width: `${(v("day_cloud_gbp") / season) * 100}%` }} />
          </span>
          <span className="scale-v">
            <Claim id="day_cloud_gbp" />
          </span>
        </div>
        <div className="scale-row is-season">
          <span className="scale-k">
            April–September 2024 · <Claim id="season_periods" bare /> half-hours
          </span>
          <span className="scale-track">
            <span style={{ width: "100%" }} />
          </span>
          <span className="scale-v">
            <Claim id="season_cloud_attributed_gbp" />
          </span>
        </div>
      </figure>

      <figure className="spread" aria-label={`Daily value across the ${c.season_days.display} days: median ${c.season_day_median_gbp.display}, 90th percentile ${c.season_day_p90_gbp.display}, largest ${c.season_day_max_gbp.display}; 15 June ${c.day_cloud_gbp.display}`}>
        <figcaption>
          <strong>15 June was not a typical day</strong> · the clouds' illustrative value per day, across the <Claim id="season_days" bare /> evaluated days
        </figcaption>
        <div className="spread-axis" aria-hidden="true">
          {[
            ["median", "season_day_median_gbp", "median day"],
            ["p90", "season_day_p90_gbp", "90th percentile"],
            ["max", "season_day_max_gbp", `largest, ${c.season_day_max_date.display}`],
          ].map(([k, id, label]) => (
            <span key={k} className={`spread-mark m-${k}`} style={{ left: dp(v(id)) }}>
              <b>{c[id].display}</b>
              <small>{label}</small>
            </span>
          ))}
          <span className="spread-mark is-event" style={{ left: dp(v("day_cloud_gbp")) }}>
            <b>{c.day_cloud_gbp.display}</b>
            <small>15 June</small>
          </span>
        </div>
      </figure>
      {children}
    </div>
  );
}

// ------------------------------------------------------------------ value: the day, observed vs clear
export type Scenario = "observed" | "clear";

export function DayChart({ ci, scenario, sel, onSel, children }: { ci: CloudImpact; scenario: Scenario | "both"; sel: number; onSel: (i: number) => void; children?: React.ReactNode }) {
  const P = ci.periods;
  const D = ci.derived;
  const n = P.slot.length;
  const ts = P.slot.map(ms);
  const half = 900_000;
  const obsOn = scenario !== "clear";
  const clrOn = scenario !== "observed";
  const desc = `24 half-hours, 05:00 to 16:30 UTC. Cloud-attributed extra import totals ${D.cloud_AC_mwh.reduce((a, b) => a + b, 0).toFixed(1)} MWh.`;
  const panel = (title: string, h: number, draw: (x: ReturnType<typeof linear>, b: { iw: number; ih: number }) => React.ReactNode, yDom: [number, number], yLabel: string, fmt?: (v: number) => string) => (
    <Chart
      height={h}
      margin={{ l: 48, r: 14, t: 22, b: 22 }}
      title={title}
      desc={desc}
      onPointer={(px, b) => {
        const x = linear(ts[0] - half, ts[n - 1] + half, 0, b.iw);
        let best = 0;
        ts.forEach((t, i) => {
          if (Math.abs(x(t) - px) < Math.abs(x(ts[best]) - px)) best = i;
        });
        onSel(best);
      }}
    >
      {(b) => {
        const x = linear(ts[0] - half, ts[n - 1] + half, 0, b.iw);
        const y = linear(yDom[0], yDom[1], b.ih, 0);
        return (
          <>
            <YAxis y={y} b={b} n={3} label={yLabel} fmt={fmt} />
            <rect x={x(ts[sel]) - (x(ts[1]) - x(ts[0])) / 2} width={x(ts[1]) - x(ts[0])} y={0} height={b.ih} className="sel-band" />
            {draw(x, b)}
          </>
        );
      }}
    </Chart>
  );
  return (
    <div className="day-chart" data-scenario={scenario}>
      {panel(
        "The 6 MW plant: observed sky and hypothetical clear sky (MW)",
        150,
        (x, b) => {
          const y = linear(0, 7, b.ih, 0);
          const xs = ts.map(x);
          return (
            <>
              <path d={linePath(xs, P.plant_pv_clear_mw.map(y))} className={`s-clear ${clrOn ? "" : "faded"}`} />
              <path d={linePath(xs, P.plant_pv_mw.map(y))} className={`s-pv ${obsOn ? "" : "faded"}`} />
              <text x={4} y={-8} className="panel-title">
                6 MW plant output · <tspan className="t-pv">observed sky (derived)</tspan> · <tspan className="t-clear">clear sky (hypothetical)</tspan>
              </text>
            </>
          );
        },
        [0, 7],
        "",
      )}
      {panel(
        "Grid import, AC reconstruction: observed sky and with the plant at clear sky (MW)",
        190,
        (x, b) => {
          const y = linear(0, 90, b.ih, 0);
          const xs = ts.map(x);
          return (
            <>
              <path d={bandPath(xs, P.import_AC_clear_sky_mw.map(y), P.import_AC_observed_mw.map(y))} className="s-gap" />
              <path d={linePath(xs, P.import_AC_clear_sky_mw.map(y))} className={`s-clear ${clrOn ? "" : "faded"}`} />
              <path d={linePath(xs, P.import_AC_observed_mw.map(y))} className={`s-ac ${obsOn ? "" : "faded"}`} />
              <text x={4} y={-8} className="panel-title">
                Grid import · <tspan className="t-ac">observed sky (simulated)</tspan> · <tspan className="t-clear">plant at clear sky (hypothetical)</tspan> · <tspan className="t-gap">gap = extra import caused by clouds</tspan>
              </text>
            </>
          );
        },
        [0, 90],
        "",
      )}
      {panel(
        "Historical APX market price (GBP per MWh) and the illustrative value of the cloud-attributed import per half-hour (GBP)",
        160,
        (x, b) => {
          const y = linear(-60, 240, b.ih, 0);
          const xs = ts.map(x);
          const bw = (x(ts[1]) - x(ts[0])) * 0.62;
          return (
            <>
              {D.cloud_AC_gbp.map((v, i) => (
                <rect key={i} x={xs[i] - bw / 2} width={bw} y={Math.min(y(0), y(v))} height={Math.abs(y(v) - y(0))} className={`s-gbp ${v < 0 ? "neg" : ""} ${i === sel ? "on" : ""}`} />
              ))}
              <path d={linePath(xs.map((v) => v - (x(ts[1]) - x(ts[0])) / 2), P.apx_gbp_per_mwh.map(y), true)} className="s-price" />
              <g className="axis">
                {ts.map((t, i) =>
                  i % 4 === 0 ? (
                    <text key={t} x={xs[i]} y={b.ih + 17} textAnchor="middle">
                      {hhmm(P.slot[i])}
                    </text>
                  ) : null,
                )}
              </g>
              <text x={4} y={-8} className="panel-title">
                <tspan className="t-price">APX price, £/MWh (observed, Elexon)</tspan> · <tspan className="t-gbp">value of the extra import, £ (illustrative)</tspan>
              </text>
            </>
          );
        },
        [-60, 240],
        "",
      )}
      <label className="day-scrub">
        <span className="sr-only">Half-hour</span>
        <input type="range" min={0} max={n - 1} value={sel} onChange={(e) => onSel(Number(e.target.value))} aria-valuetext={`${hhmm(P.slot[sel])} UTC`} />
      </label>
      {children}
    </div>
  );
}

export function HalfHourLedger({ ci, i }: { ci: CloudImpact; i: number }) {
  const P = ci.periods;
  const D = ci.derived;
  return (
    <div className="ledger-hh" aria-live="polite">
      <p className="lh-t">
        {hhmm(P.slot[i])}–{hhmm(new Date(ms(P.slot[i]) + 1_800_000).toISOString())} UTC · settlement period {P.settlement_period[i]}
      </p>
      <dl>
        <div>
          <dt>Plant, observed → clear sky</dt>
          <dd>
            {num(P.plant_pv_mw[i], 2)} → {num(P.plant_pv_clear_mw[i], 2)} MW
          </dd>
        </div>
        <div>
          <dt>Extra import caused by clouds</dt>
          <dd>{num(D.cloud_AC_mwh[i], 3, true)} MWh</dd>
        </div>
        <div>
          <dt>APX price (observed)</dt>
          <dd>£{num(P.apx_gbp_per_mwh[i], 2)}/MWh</dd>
        </div>
        <div>
          <dt>Illustrative value</dt>
          <dd>{gbp(D.cloud_AC_gbp[i])}</dd>
        </div>
      </dl>
    </div>
  );
}

export function useCloudImpact() {
  return useData<CloudImpact>("cloud_impact.json");
}

export function useSceneData() {
  const ev = useData<EventData>("events/jun15_cloud_clearing/event.json");
  const net = useData<Network>("network.json");
  return { ev: ev.data, net: net.data, error: ev.error ?? net.error };
}

export function useFrameIndex(ev: EventData | null) {
  return useMemo(() => {
    const m = new Map<string, number>();
    ev?.frames.forEach((f, i) => m.set(hhmm(f.t), i));
    return m;
  }, [ev]);
}

export type { Camera };
export { SatelliteView };

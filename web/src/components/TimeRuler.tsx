import { useClaims } from "../data/load";
import { hhmm, ms } from "../data/format";
import { useReducedMotion, useSize } from "./hooks";

export type TimeMode = "history" | "frozen" | "day" | "season" | "valued";

const DAY_SLOTS = Array.from({ length: 24 }, (_, i) => new Date(Date.UTC(2024, 5, 15, 5, 0) + i * 1_800_000).toISOString().replace(".000", ""));
const HOURS = Array.from({ length: 13 }, (_, i) => Date.UTC(2024, 5, 15, 5 + i, 0));

/**
 * The story's clock, drawn at the evidence's own resolution: one tick per real satellite frame
 * (15 min), one taller tick per grid state (30 min), a lock when the grid is frozen for the
 * counterfactual, and the 24 valued half-hours for the economics. Nothing between ticks exists.
 */
export function TimeRuler({ mode, t, frames, gridSlots }: { mode: TimeMode; t: string | null; frames: string[]; gridSlots: string[] }) {
  const [ref, { w }] = useSize<HTMLDivElement>();
  const rm = useReducedMotion();
  const c = useClaims();
  const [d0, d1] = mode === "day" ? [Date.UTC(2024, 5, 15, 4, 45), Date.UTC(2024, 5, 15, 17, 0)] : [Date.UTC(2024, 5, 15, 8, 37), Date.UTC(2024, 5, 15, 12, 23)];
  const pad = 16;
  const x = (v: number) => pad + ((v - d0) / (d1 - d0)) * (w - 2 * pad);
  const slots = mode === "day" ? DAY_SLOTS : gridSlots;
  const tr = rm ? "none" : "transform .9s cubic-bezier(.65,0,.25,1), opacity .6s";
  const lock = ms("2024-06-15T11:00:00Z");
  if (mode === "season" || mode === "valued") {
    const months = ["Apr", "May", "Jun", "Jul", "Aug", "Sep"];
    const status =
      mode === "season"
        ? `Aggregate GENCO evaluation · all ${c.n_states.display} real half-hours, ${c.states_span.display} · not one moment`
        : `Economic case study · one ${c.plant_capacity.display} MW plant · ${c.season_periods.display} valued half-hours over ${c.season_days.display} days, ${c.states_span.display}`;
    return (
      <div className="ruler mode-season" aria-label={`Time: ${status}`} role="group">
        <div className="ruler-key">
          <span className="ruler-status">{status}</span>
        </div>
        <div ref={ref} className="ruler-track">
          {w > 0 && (
            <svg width={w} height={44} aria-hidden="true">
              <rect x={16} y={6} width={w - 32} height={22} className="season-band" />
              {months.map((m, i) => (
                <text key={m} x={16 + ((i + 0.5) / 6) * (w - 32)} y={42} textAnchor="middle" className="ruler-hour">
                  {w < 600 ? m : `${m} 2024`}
                </text>
              ))}
              <rect x={16 + (2.47 / 6) * (w - 32)} y={2} width={3} height={30} className="ruler-grid" />
            </svg>
          )}
        </div>
      </div>
    );
  }
  const status =
    mode === "history"
      ? "Watching the recorded morning"
      : mode === "frozen"
        ? "Grid frozen at 11:00 UTC · counterfactual: only the 6 MW plant changes"
        : "Whole day · 24 AC-reconstructed half-hours, 05:00–16:30 UTC";
  return (
    <div className={`ruler mode-${mode}`} aria-label={`Time: ${status}${t ? `, ${hhmm(t)} UTC` : ""}`} role="group">
      <div className="ruler-key">
        <span>
          <i className="rk-frame" /> satellite image, every 15 min
        </span>
        <span>
          <i className="rk-grid" /> grid state, every 30 min
        </span>
        <span className="ruler-status">{status}</span>
      </div>
      <div ref={ref} className="ruler-track">
        {w > 0 && (
          <svg width={w} height={44} aria-hidden="true">
            {mode === "day" && (
              <rect x={x(ms(frames[0]))} y={2} width={x(ms(frames[frames.length - 1])) - x(ms(frames[0]))} height={12} className="ruler-window" />
            )}
            {HOURS.map((h, i) => {
              const every = mode === "day" ? (w < 520 ? 3 : w < 900 ? 2 : 1) : 1;
              const vis = h >= d0 && h <= d1 && i % every === 0;
              return (
                <text key={h} style={{ transform: `translateX(${x(h)}px)`, transition: tr, opacity: vis ? 1 : 0 }} y={42} textAnchor="middle" className="ruler-hour">
                  {hhmm(new Date(h).toISOString())}
                </text>
              );
            })}
            {mode !== "day" &&
              w > 520 &&
              [9, 10, 11, 12].flatMap((hr) => [30].map((mi) => Date.UTC(2024, 5, 15, hr, mi))).map((h) =>
                h < d1 ? (
                  <text key={h} style={{ transform: `translateX(${x(h)}px)` }} y={42} textAnchor="middle" className="ruler-hour minor">
                    {hhmm(new Date(h).toISOString())}
                  </text>
                ) : null,
              )}
            {frames.map((f) => (
              <rect key={f} width={3} height={10} y={4} x={-1.5} className={`ruler-frame ${t === f && mode === "history" ? "on" : ""}`} style={{ transform: `translateX(${x(ms(f))}px)`, transition: tr }} />
            ))}
            {slots.map((s) => (
              <rect key={s} width={3} height={18} y={14} x={-1.5} className={`ruler-grid ${t === s ? "on" : ""}`} style={{ transform: `translateX(${x(ms(s))}px)`, transition: tr }} />
            ))}
            {mode === "frozen" && (
              <g style={{ transform: `translateX(${x(lock)}px)` }}>
                <rect x={-7} y={0} width={14} height={32} className="ruler-lock" />
              </g>
            )}
            {t && mode !== "frozen" && (
              <rect x={-2} y={0} width={4} height={32} className="ruler-now" style={{ transform: `translateX(${x(ms(t))}px)`, transition: tr }} />
            )}
          </svg>
        )}
      </div>
    </div>
  );
}

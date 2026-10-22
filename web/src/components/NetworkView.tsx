import { num } from "../data/format";
import type { FlowState, ModelId, Network } from "../data/types";
import { useRef, useState } from "react";
import { useSize } from "./hooks";
import { useTheme } from "./theme";

// Electrical schematic, NOT a map: positions come from the Explorer's published layout
// (configs/app/network_layout.yaml). Every width and colour is a frozen AC or GENCO branch result.

type Mode = "flow" | "error";
export type Highlight = ("pv" | "battery" | "loads" | "plant")[];

interface Props {
  net: Network;
  state: FlowState | null; // the model shown
  ac?: FlowState | null; // AC state at the same time (error mode)
  model?: ModelId;
  mode?: Mode;
  highlight?: Highlight;
  dim?: boolean;
  compact?: boolean;
  title?: string;
  /** zoom, pan and click / keyboard details for each branch (Explorer) */
  interactive?: boolean;
}

const LOAD_DARK = ["#33414d", "#c2611c", "#ffb072"];
const LOAD_LIGHT = ["#c9d1d8", "#e0761f", "#8f3a00"];
const DIV_DARK = ["#4d9be6", "#55606b", "#ff6b5e"];
const DIV_LIGHT = ["#1f66b8", "#c3cad1", "#c8302a"];

function mix(a: string, b: string, t: number): string {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  return `rgb(${pa.map((v, i) => Math.round(v + (pb[i] - v) * t)).join(",")})`;
}
function ramp(stops: string[], t: number): string {
  const x = Math.max(0, Math.min(1, t));
  return x < 0.5 ? mix(stops[0], stops[1], x * 2) : mix(stops[1], stops[2], (x - 0.5) * 2);
}

export function NetworkView({ net, state, ac, model = "AC", mode = "flow", highlight = [], dim = false, compact = false, title, interactive = false }: Props) {
  const [ref, size] = useSize<HTMLDivElement>();
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState<[number, number]>([0, 0]);
  const [selected, setSelected] = useState<string | null>(null);
  const drag = useRef<{ x: number; y: number; p: [number, number] } | null>(null);
  const theme = useTheme();
  const X0 = -7.6;
  const X1 = 6.1;
  const Y0 = -1.75; // schematic y (up) range
  const Y1 = 4.75;
  const ppu = (size.w ? Math.min(size.w / (X1 - X0), size.h / (Y1 - Y0)) : 60) * zoom;
  // visible window in schematic units (zoom about the centre, then pan)
  const vw = (X1 - X0) / zoom;
  const vh = (Y1 - Y0) / zoom;
  const vx = X0 + ((X1 - X0) - vw) / 2 + pan[0];
  const vy = -Y1 + ((Y1 - Y0) - vh) / 2 + pan[1];
  const px = (v: number) => v / ppu; // screen px -> schematic units
  const nodes = new Map(net.nodes.map((n) => [n.bus, n]));
  const bars = new Map<number, number>();
  for (const n of net.nodes) if (net.layout.busbars[n.key]) bars.set(n.bus, net.layout.busbars[n.key].y);
  const barX = new Map<number, number[]>([...bars.keys()].map((b) => [b, [nodes.get(b)!.x]]));
  const load = theme === "dark" ? LOAD_DARK : LOAD_LIGHT;
  const div = theme === "dark" ? DIV_DARK : DIV_LIGHT;
  const fs = Math.max(9, Math.min(14, ppu * 0.2));

  const edges = net.edges.map((e, i) => {
    const a = nodes.get(e.a)!;
    const b = nodes.get(e.b)!;
    let [x0, y0, x1, y1] = [a.x, a.y, b.x, b.y];
    if (bars.has(e.a)) {
      [x0, y0] = [b.x, bars.get(e.a)!];
      barX.get(e.a)!.push(b.x);
    }
    if (bars.has(e.b)) {
      [x1, y1] = [a.x, bars.get(e.b)!];
      barX.get(e.b)!.push(a.x);
    }
    const p = state?.p_ab_mw[i] ?? null;
    const lp = state?.loading_pct[i] ?? null;
    const pac = ac?.p_ab_mw[i] ?? null;
    const err = p !== null && pac !== null ? p - pac : null;
    const out = p === null;
    const w = out ? 1 : 1.6 + 7 * Math.sqrt(Math.min(Math.abs(p), 120) / 120);
    const colour = out ? "var(--muted)" : mode === "error" && err !== null ? ramp(div, 0.5 + 0.5 * Math.max(-1, Math.min(1, err / 10))) : ramp(load, (lp ?? 0) / 100);
    return { e, x0, y0, x1, y1, p, lp, err, out, w, colour, pac };
  });

  return (
    <div ref={ref} className={`net ${dim ? "is-dim" : ""} ${compact ? "is-compact" : ""} ${interactive ? "is-interactive" : ""}`}>
      {size.w > 0 && (
        <svg
          viewBox={`${vx} ${vy} ${vw} ${vh}`}
          role={interactive ? "group" : "img"}
          aria-label={title ?? "Sundon network schematic"}
          onPointerDown={
            interactive
              ? (e) => {
                  drag.current = { x: e.clientX, y: e.clientY, p: pan };
                }
              : undefined
          }
          onPointerMove={
            interactive
              ? (e) => {
                  const d = drag.current;
                  if (!d || zoom === 1) return;
                  setPan([d.p[0] - (e.clientX - d.x) / ppu, d.p[1] - (e.clientY - d.y) / ppu]);
                }
              : undefined
          }
          onPointerUp={interactive ? () => (drag.current = null) : undefined}
          onPointerLeave={interactive ? () => (drag.current = null) : undefined}
        >
          <title>{title ?? "Sundon network schematic"}</title>
          {net.layout.bands.map((b, i) => (
            <g key={b.label}>
              <rect x={X0} y={-b.y1} width={X1 - X0} height={b.y1 - b.y0} className={`band band-${i % 2}`} />
              <text x={X0 + px(10)} y={-b.y1 + px(fs + 6)} fontSize={px(fs)} className="net-band-label">
                {b.label}
              </text>
            </g>
          ))}
          {edges.map(({ e, x0, y0, x1, y1, p, lp, err, out, w, colour, pac }) => {
            const send = p !== null && p < 0;
            const [sx, sy, ex, ey] = send ? [x1, y1, x0, y0] : [x0, y0, x1, y1];
            const ang = Math.atan2(-(ey - sy), ex - sx);
            const mx = sx + 0.56 * (ex - sx);
            const my = -(sy + 0.56 * (ey - sy));
            const L = px(7);
            const showArrow = p !== null && Math.abs(p) > 0.5;
            return (
              <g key={e.id} className={`edge ${out ? "is-out" : ""}`}>
                <line x1={x0} y1={-y0} x2={x1} y2={-y1} stroke={colour} strokeWidth={px(w)} strokeDasharray={out ? `${px(3)} ${px(3)}` : undefined} className="edge-line" />
                {showArrow && (
                  <path
                    d={`M ${mx + L * Math.cos(ang)} ${my + L * Math.sin(ang)} L ${mx - L * Math.cos(ang) + L * 0.7 * Math.sin(ang)} ${my - L * Math.sin(ang) - L * 0.7 * Math.cos(ang)} L ${mx - L * Math.cos(ang) - L * 0.7 * Math.sin(ang)} ${my - L * Math.sin(ang) + L * 0.7 * Math.cos(ang)} Z`}
                    className="edge-arrow"
                  />
                )}
                <line
                  x1={x0}
                  y1={-y0}
                  x2={x1}
                  y2={-y1}
                  strokeWidth={px(16)}
                  className={`edge-hit ${selected === e.id ? "is-selected" : ""}`}
                  tabIndex={interactive ? 0 : undefined}
                  role={interactive ? "button" : undefined}
                  aria-label={interactive ? `Branch ${e.from.split(":")[1]} to ${e.to.split(":")[1]}` : undefined}
                  onClick={interactive ? () => setSelected(e.id === selected ? null : e.id) : undefined}
                  onKeyDown={interactive ? (k) => (k.key === "Enter" || k.key === " ") && (k.preventDefault(), setSelected(e.id)) : undefined}
                >
                  <title>
                    {`${e.from.split(":")[1]} – ${e.to.split(":")[1]} (${e.kind}, ${e.elements.join(", ")})\n` +
                      (out
                        ? "out of service in this state"
                        : `${model === "AC" ? "AC" : model}: P ${num(p, 1, true)} MW, loading ${num(lp, 0)} %` +
                          (model !== "AC" && pac !== null ? `\nAC: P ${num(pac, 1, true)} MW · error ${num(err, 1, true)} MW` : ""))}
                  </title>
                </line>
              </g>
            );
          })}
          {[...bars.entries()].map(([b, y]) => {
            const xs = barX.get(b)!;
            const n = nodes.get(b)!;
            return (
              <rect key={b} x={Math.min(...xs) - 0.14} y={-y - px(3.5)} width={Math.max(...xs) - Math.min(...xs) + 0.28} height={px(7)} className="busbar">
                <title>{`${n.label} busbar (${n.kv} kV)${state?.vm_pu[b] ? ` · ${num(state.vm_pu[b], 3)} pu` : ""}`}</title>
              </rect>
            );
          })}
          {net.nodes
            .filter((n) => !bars.has(n.bus))
            .map((n) => {
              const r = px(n.role === "pv_33kv" ? 6.5 : n.role === "battery_33kv" ? 6.5 : n.role === "load_11kv" ? 5 : 3);
              const hi =
                ((highlight.includes("pv") || highlight.includes("plant")) && n.role === "pv_33kv") ||
                (highlight.includes("battery") && n.role === "battery_33kv") ||
                (highlight.includes("loads") && n.role === "load_11kv");
              return (
                <g key={n.bus} className={`node role-${n.role} ${hi ? "is-hi" : ""}`}>
                  {hi && <circle cx={n.x} cy={-n.y} r={r * 2.6} className="node-halo" />}
                  {n.role === "battery_33kv" ? (
                    <rect x={n.x - r} y={-n.y - r} width={2 * r} height={2 * r} className="node-mark" strokeWidth={px(1.5)} />
                  ) : (
                    <circle cx={n.x} cy={-n.y} r={r} className="node-mark" strokeWidth={px(1.5)} />
                  )}
                  <title>{`${n.label} · ${n.kv} kV · ${n.substation}${state?.vm_pu[n.bus] ? ` · ${num(state.vm_pu[n.bus], 3)} pu` : ""}`}</title>
                </g>
              );
            })}
          {!compact &&
            net.layout.groups.map((g) => (
              <text key={g.label} x={g.x} y={-g.y} fontSize={px(fs)} textAnchor={g.anchor === "left" ? "start" : "middle"} className="net-group">
                {g.label.split("<br>").map((line, i) => (
                  <tspan key={i} x={g.x} dy={i ? px(fs * 1.15) : 0}>
                    {line}
                  </tspan>
                ))}
              </text>
            ))}
        </svg>
      )}
      {interactive && (
        <div className="net-tools" role="group" aria-label="Zoom the schematic">
          <button onClick={() => setZoom((z) => Math.min(4, z * 1.5))} aria-label="Zoom in">
            +
          </button>
          <button onClick={() => setZoom((z) => Math.max(1, z / 1.5))} aria-label="Zoom out" disabled={zoom === 1}>
            −
          </button>
          <button
            onClick={() => {
              setZoom(1);
              setPan([0, 0]);
            }}
            disabled={zoom === 1}
          >
            Reset
          </button>
        </div>
      )}
      {interactive &&
        selected &&
        (() => {
          const x = edges.find((d) => d.e.id === selected);
          if (!x) return null;
          return (
            <div className="net-detail" role="status">
              <strong>
                {x.e.from.split(":")[1]} – {x.e.to.split(":")[1]}
              </strong>{" "}
              <span className="note">
                {x.e.kind}, {x.e.elements.join(", ")}, rating {num(x.e.rating_mva, 1)} MVA
              </span>
              <br />
              {x.out ? (
                "Out of service in this state."
              ) : (
                <>
                  {model === "AC" ? "AC" : model}: P {num(x.p, 1, true)} MW, loading {num(x.lp, 0)} %{model !== "AC" && x.pac !== null && <> · AC: P {num(x.pac, 1, true)} MW · error {num(x.err, 1, true)} MW</>}
                </>
              )}
              <button className="btn-text" onClick={() => setSelected(null)}>
                Close
              </button>
            </div>
          );
        })()}
    </div>
  );
}

export function NetworkLegend({ mode = "flow" }: { mode?: Mode }) {
  return (
    <div className="net-legend" aria-hidden="true">
      <span>
        <i className="lg-line thin" />
        <i className="lg-line thick" /> active power (width)
      </span>
      {mode === "flow" ? (
        <span>
          <i className="lg-grad" /> loading 0 → 100 %
        </span>
      ) : (
        <span>
          <i className="lg-grad err" /> model − AC flow (−10 → +10 MW)
        </span>
      )}
      <span>
        <i className="lg-dot pv" /> PV connection
      </span>
      <span>
        <i className="lg-dot bat" /> battery
      </span>
      <span>
        <i className="lg-dot load" /> 11 kV load
      </span>
      <span>schematic, not a map</span>
    </div>
  );
}

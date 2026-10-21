import { useMemo, type ReactNode } from "react";
import { hhmm, ms, num } from "../data/format";
import { useReducedMotion, useSize } from "./hooks";

// Small SVG chart toolkit. Charts draw frozen values; the only transformation is a linear scale.

export type Scale = ((v: number) => number) & { d: [number, number]; r: [number, number]; ticks: (n?: number) => number[] };

export function linear(d0: number, d1: number, r0: number, r1: number): Scale {
  const f = ((v: number) => r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0)) as Scale;
  f.d = [d0, d1];
  f.r = [r0, r1];
  f.ticks = (n = 5) => {
    const span = Math.abs(d1 - d0) || 1;
    const raw = span / n;
    const mag = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) ?? mag * 10;
    const lo = Math.ceil(Math.min(d0, d1) / step) * step;
    const out: number[] = [];
    for (let v = lo; v <= Math.max(d0, d1) + 1e-9; v += step) out.push(Number(v.toFixed(10)));
    return out;
  };
  return f;
}

export interface Box {
  w: number;
  h: number;
  m: { t: number; r: number; b: number; l: number };
  iw: number;
  ih: number;
}

/** Responsive SVG frame. `desc` is the chart's text alternative. */
export function Chart({
  height,
  margin,
  title,
  desc,
  className,
  children,
  onPointer,
}: {
  height: number | string;
  margin?: Partial<Box["m"]>;
  title: string;
  desc: string;
  className?: string;
  children: (b: Box) => ReactNode;
  onPointer?: (x: number, b: Box) => void;
}) {
  const [ref, size] = useSize<HTMLDivElement>();
  const m = { t: 12, r: 12, b: 26, l: 44, ...margin };
  const b: Box = { w: size.w, h: size.h, m, iw: Math.max(10, size.w - m.l - m.r), ih: Math.max(10, size.h - m.t - m.b) };
  return (
    <figure ref={ref} className={`chart ${className ?? ""}`} style={{ height }}>
      {size.w > 0 && (
        <svg
          width={size.w}
          height={size.h}
          role="img"
          aria-label={title}
          onPointerMove={onPointer ? (e) => onPointer(e.clientX - e.currentTarget.getBoundingClientRect().left - m.l, b) : undefined}
          onPointerDown={onPointer ? (e) => onPointer(e.clientX - e.currentTarget.getBoundingClientRect().left - m.l, b) : undefined}
        >
          <title>{title}</title>
          <desc>{desc}</desc>
          <g transform={`translate(${m.l},${m.t})`}>{children(b)}</g>
        </svg>
      )}
      <figcaption className="sr-only">{desc}</figcaption>
    </figure>
  );
}

export function YAxis({ y, b, fmt = (v) => num(v, 0), label, n = 4, grid = true }: { y: Scale; b: Box; fmt?: (v: number) => string; label?: string; n?: number; grid?: boolean }) {
  return (
    <g className="axis">
      {y.ticks(n).map((v) => (
        <g key={v} transform={`translate(0,${y(v)})`}>
          {grid && <line x2={b.iw} className="gridline" />}
          <text x={-8} dy="0.32em" textAnchor="end">
            {fmt(v)}
          </text>
        </g>
      ))}
      {label && (
        <text className="axis-label" x={-b.m.l + 2} y={-4} textAnchor="start">
          {label}
        </text>
      )}
    </g>
  );
}

export function TimeAxis({ x, b, step = 30, from, to, every = 1 }: { x: Scale; b: Box; step?: number; from: string; to: string; every?: number }) {
  const ticks: number[] = [];
  for (let t = ms(from); t <= ms(to) + 1; t += step * 60_000) ticks.push(t);
  return (
    <g className="axis" transform={`translate(0,${b.ih})`}>
      {ticks.map((t, i) =>
        i % every === 0 ? (
          <text key={t} x={x(t)} y={18} textAnchor="middle">
            {hhmm(new Date(t).toISOString())}
          </text>
        ) : null,
      )}
    </g>
  );
}

export function linePath(xs: number[], ys: (number | null)[], step = false): string {
  let d = "";
  let pen = false;
  xs.forEach((x, i) => {
    const y = ys[i];
    if (y === null || !Number.isFinite(y)) {
      pen = false;
      return;
    }
    if (!pen) d += `M${x},${y}`;
    else if (step) d += `H${x}V${y}`;
    else d += `L${x},${y}`;
    pen = true;
  });
  return d;
}

/** Area between two series (same x). */
export function bandPath(xs: number[], y0: number[], y1: number[]): string {
  const top = xs.map((x, i) => `${i ? "L" : "M"}${x},${y1[i]}`).join("");
  const bot = xs
    .map((x, i) => [x, y0[i]] as const)
    .reverse()
    .map(([x, y]) => `L${x},${y}`)
    .join("");
  return top + bot + "Z";
}

// ------------------------------------------------------------------ horizontal comparison bars
export interface BarRow {
  key: string;
  label: ReactNode;
  value: number;
  display: ReactNode;
  colour: string;
  kind?: "solid" | "outline" | "hatched";
  note?: ReactNode;
  hidden?: boolean;
}

/** Bars from a zero line. Width transitions reveal frozen values; hidden rows keep their slot. */
export function Bars({ rows, domain, unit, title, desc, target }: { rows: BarRow[]; domain: [number, number]; unit: string; title: string; desc: string; target?: { value: number; label: string } }) {
  const rm = useReducedMotion();
  const span = domain[1] - domain[0];
  const pct = (v: number) => ((v - domain[0]) / span) * 100;
  const z = pct(0);
  return (
    <figure className="bars" aria-label={title}>
      <figcaption className="sr-only">{desc}</figcaption>
      {rows.map((r) => {
        const v = r.hidden ? 0 : r.value;
        const left = Math.min(z, pct(v));
        const width = Math.abs(pct(v) - z);
        return (
          <div key={r.key} className={`bar-row ${r.hidden ? "is-hidden" : ""}`} data-row={r.key}>
            <div className="bar-label">{r.label}</div>
            <div className="bar-track">
              <div className="bar-zero" style={{ left: `${z}%` }} />
              {target && <div className="bar-target" style={{ left: `${pct(target.value)}%` }} title={target.label} />}
              <div
                className={`bar-fill kind-${r.kind ?? "solid"}`}
                style={{ left: `${left}%`, width: `${width}%`, background: r.kind === "outline" ? "transparent" : r.colour, borderColor: r.colour, transition: rm ? "none" : undefined }}
              />
            </div>
            <div className="bar-value" aria-live="polite">
              {r.hidden ? "" : r.display}
              {r.note && !r.hidden && <span className="bar-note">{r.note}</span>}
            </div>
          </div>
        );
      })}
      <div className="bar-unit">{unit}</div>
    </figure>
  );
}

/** Many points as one path (fast for thousands of points). */
export function Dots({ xs, ys, r, className }: { xs: number[]; ys: number[]; r: number; className?: string }) {
  const d = useMemo(() => xs.map((x, i) => `M${x.toFixed(1)},${ys[i].toFixed(1)}h0`).join(""), [xs, ys]);
  return <path d={d} className={className} strokeWidth={r * 2} strokeLinecap="round" fill="none" />;
}

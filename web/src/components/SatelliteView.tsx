import { useEffect, useRef, useState } from "react";
import { asset } from "../data/load";
import { hhmm, num } from "../data/format";
import type { EventData, Network } from "../data/types";
import { useReducedMotion, useSize } from "./hooks";

// The observed frames are plate carrée (EPSG:4326 as served by EUMETView): 1100 × 600 px over
// 5.5° × 3°, so one degree is the same number of pixels in both directions and circles stay round.
export const STUDY_BOX = { lon0: -1.05, lat0: 51.65, lon1: -0.15, lat1: 52.25 };

export type Camera = "uk" | "wide" | "region" | "sundon" | "plant";
const CAMERAS: Record<Camera, [number, number, number, number]> = {
  uk: [-3.5, 50.5, 2.0, 53.5],
  wide: [-2.9, 50.6, 1.5, 53.2],
  region: [-2.6, 51.05, 1.3, 52.85],
  sundon: [-2.05, 51.2, 0.85, 52.7],
  plant: [-1.0, 51.68, -0.2, 52.18],
};

const TOWNS: [string, number, number][] = [
  ["London", 51.507, -0.128],
  ["Oxford", 51.752, -1.258],
  ["Cambridge", 52.205, 0.122],
  ["Birmingham", 52.486, -1.89],
  ["Milton Keynes", 52.04, -0.76],
];

// label placement in screen px: dx, dy, anchor (keeps the four names apart at Sundon zoom)
const SUBSTATIONS: [string, string, number, number, "start" | "end"][] = [
  ["SUNDON", "Sundon", 9, -9, "start"],
  ["CHAUL END", "Chaul End", 9, 18, "start"],
  ["LEIGHTON BUZZARD", "Leighton Buzzard", -10, -10, "end"],
  ["LEWSEY", "Lewsey", -10, 18, "end"],
];

interface Props {
  event: EventData;
  frame: number;
  camera: Camera;
  /** second real frame shown to the right of a draggable wipe (no blending of images) */
  compare?: number;
  wipe?: number;
  onWipe?: (v: number) => void;
  network?: Network | null;
  showPlants?: boolean;
  highlightPlant?: boolean;
  showBox?: boolean;
  frozen?: boolean;
  label?: string;
  /** where the camera's centre lands across the pane (0.5 = middle), e.g. right of an overlaid panel */
  focusX?: number;
  className?: string;
}

export function SatelliteView(p: Props) {
  const [ref, size] = useSize<HTMLDivElement>();
  const f = p.event.frames[p.frame];
  return (
    <div ref={ref} className={`sat ${p.frozen ? "is-frozen" : ""} ${p.className ?? ""}`}>
      {size.w > 0 && (
        <>
          <Layer {...p} w={size.w} h={size.h} frameIdx={p.frame} />
          {p.compare !== undefined && (
            <div className="sat-right" style={{ clipPath: `inset(0 0 0 ${p.wipe ?? 50}%)` }}>
              <Layer {...p} w={size.w} h={size.h} frameIdx={p.compare} />
            </div>
          )}
        </>
      )}
      {p.compare !== undefined ? (
        <>
          <div className="sat-handle" style={{ left: `${p.wipe ?? 50}%` }} aria-hidden="true" />
          <span className="sat-stamp left">{hhmm(f.t)} UTC</span>
          <span className="sat-stamp right">{hhmm(p.event.frames[p.compare].t)} UTC</span>
          <input
            className="sat-wipe"
            type="range"
            min={0}
            max={100}
            step={0.5}
            value={p.wipe ?? 50}
            onChange={(e) => p.onWipe?.(Number(e.target.value))}
            aria-label={`Compare the ${hhmm(f.t)} and ${hhmm(p.event.frames[p.compare].t)} UTC observations`}
          />
        </>
      ) : (
        <span className="sat-stamp left">
          {p.label ?? `${hhmm(f.t)} UTC · 15 June 2024`}
          {p.frozen && " · grid frozen here"}
        </span>
      )}
      <span className="sat-credit">
        <span className="sat-credit-long">Meteosat E-View · observed · </span>© EUMETSAT 2024, CC BY 4.0, modified
      </span>
    </div>
  );
}

function Layer(p: Props & { w: number; h: number; frameIdx: number }) {
  const rm = useReducedMotion();
  const f = p.event.frames[p.frameIdx];
  const [lon0, lat0, lon1, lat1] = f.bbox;
  const W = 1100;
  const Hh = 600;
  const ppd = W / (lon1 - lon0); // image px per degree
  const [c0, c1, c2, c3] = CAMERAS[p.camera];
  const rw = (c2 - c0) * ppd;
  const rh = (c3 - c1) * ppd;
  const s = Math.max(p.w / rw, p.h / rh, p.w / W, p.h / Hh);
  const cx = ((c0 + c2) / 2 - lon0) * ppd;
  const cy = (lat1 - (c1 + c3) / 2) * ppd;
  const tx = Math.min(0, Math.max(p.w - W * s, p.w * (p.focusX ?? 0.5) - cx * s));
  const ty = Math.min(0, Math.max(p.h - Hh * s, p.h / 2 - cy * s));
  const k = 1 / (ppd * s); // degrees per screen pixel: overlay marks keep their on-screen size

  // cross-fade between two consecutive REAL frames (display transition; nothing is synthesised)
  const [under, setUnder] = useState(f.file);
  const last = useRef(f.file);
  useEffect(() => {
    if (last.current !== f.file) {
      setUnder(last.current);
      last.current = f.file;
    }
  }, [f.file]);

  const ti = p.frameIdx;
  const assets = p.event.assets;
  const nodes = p.network?.nodes.filter((n) => n.lat !== null && n.lon !== null) ?? [];
  const pos = new Map(nodes.map((n) => [n.bus, n]));
  const subs = SUBSTATIONS.map(([key, name, dx, dy, anchor]) => {
    const n = nodes.find((x) => x.substation.startsWith(key));
    return n ? { name, lat: n.lat!, lon: n.lon!, dx, dy, anchor } : null;
  }).filter(Boolean) as { name: string; lat: number; lon: number; dx: number; dy: number; anchor: "start" | "end" }[];
  const seen = new Set<string>();
  const links = (p.network?.edges ?? []).flatMap((e) => {
    const a = pos.get(e.a);
    const b = pos.get(e.b);
    if (!a || !b) return [];
    const d = Math.hypot(a.lat! - b.lat!, a.lon! - b.lon!);
    const key = [a.substation.split(" ")[0], b.substation.split(" ")[0]].sort().join("-");
    if (d < 0.01 || seen.has(key)) return [];
    seen.add(key);
    return [[a, b] as const];
  });
  const zoomed = p.camera === "sundon" || p.camera === "plant";
  const fs = 13 * k;

  return (
    <div
      className="sat-inner"
      style={{
        width: W,
        height: Hh,
        transform: `translate(${tx}px, ${ty}px) scale(${s})`,
        transition: rm ? "none" : "transform 1.8s cubic-bezier(.65,0,.25,1)",
      }}
    >
      <img className="sat-img" src={asset(under)} alt="" width={W} height={Hh} />
      <img
        key={f.file}
        className={`sat-img ${rm ? "" : "fade-in"}`}
        src={asset(f.file)}
        alt={`Meteosat E-View observation, 15 June 2024 ${hhmm(f.t)} UTC`}
        width={W}
        height={Hh}
      />
      <svg className="sat-overlay" viewBox={`${lon0} ${-lat1} ${lon1 - lon0} ${lat1 - lat0}`} preserveAspectRatio="none" aria-hidden="true">
        {!zoomed &&
          TOWNS.map(([n, la, lo]) => (
            <g key={n}>
              <circle cx={lo} cy={-la} r={2.5 * k} className="ov-town" />
              <text x={lo} y={-la - 7 * k} fontSize={fs} strokeWidth={3 * k} className="ov-label" textAnchor="middle">
                {n}
              </text>
            </g>
          ))}
        {p.showBox !== false && (
          <rect
            x={STUDY_BOX.lon0}
            y={-STUDY_BOX.lat1}
            width={STUDY_BOX.lon1 - STUDY_BOX.lon0}
            height={STUDY_BOX.lat1 - STUDY_BOX.lat0}
            className="ov-box"
            strokeWidth={1.6 * k}
            strokeDasharray={`${6 * k} ${4 * k}`}
          />
        )}
        {!zoomed && p.showBox !== false && (
          <text x={STUDY_BOX.lon0} y={-STUDY_BOX.lat1 - 6 * k} fontSize={fs} strokeWidth={3 * k} className="ov-label">
            Sundon study area
          </text>
        )}
        {zoomed &&
          links.map(([a, b], i) => (
            <line key={i} x1={a.lon!} y1={-a.lat!} x2={b.lon!} y2={-b.lat!} className="ov-link" strokeWidth={1.6 * k} />
          ))}
        {p.showPlants !== false &&
          assets.map((a) => {
            const cf = a.capacity_factor[ti] ?? 0;
            const r = Math.min(14, 4 + 4 * Math.sqrt(a.capacity_mw)) * k;
            return (
              <circle key={a.id} cx={a.lon} cy={-a.lat} r={r} className="ov-plant" style={{ fillOpacity: 0.25 + 0.75 * Math.min(1, cf) }} strokeWidth={1.2 * k}>
                <title>{`${a.id} · ${num(a.capacity_mw, 2)} MW installed · estimated ${num(a.p_mw[ti], 2)} MW at ${hhmm(f.t)} UTC`}</title>
              </circle>
            );
          })}
        {zoomed &&
          subs.map((s) => (
            <g key={s.name}>
              <rect x={s.lon - 3.5 * k} y={-s.lat - 3.5 * k} width={7 * k} height={7 * k} className="ov-sub" strokeWidth={1.2 * k} />
              <text x={s.lon + s.dx * k} y={-s.lat + s.dy * k} fontSize={fs} strokeWidth={3 * k} textAnchor={s.anchor} className="ov-label">
                {s.name}
              </text>
            </g>
          ))}
        {p.highlightPlant &&
          (() => {
            const pl = assets.find((a) => a.id === p.event.plant_id);
            if (!pl) return null;
            return (
              <g className="ov-plant-hi">
                <circle cx={pl.lon} cy={-pl.lat} r={20 * k} strokeWidth={2.2 * k} />
                <text x={pl.lon} y={-pl.lat + 36 * k} fontSize={fs} strokeWidth={3 * k} textAnchor="middle" className="ov-label">
                  6 MW plant
                </text>
              </g>
            );
          })()}
      </svg>
    </div>
  );
}

/** The fifteen real frames as a strip: the evidence's own time resolution, clickable. */
export function Filmstrip({ event, index, onPick, camera = "sundon" }: { event: EventData; index: number; onPick: (i: number) => void; camera?: Camera }) {
  const [c0, c1, c2, c3] = CAMERAS[camera];
  return (
    <div className="filmstrip" role="group" aria-label="Meteosat frames, 15-minute steps">
      {event.frames.map((f, i) => {
        const [lon0, , lon1, lat1] = f.bbox;
        const ppd = 1100 / (lon1 - lon0);
        const s = 100 / ((c2 - c0) * ppd); // strip cell is 100 units wide
        const x = -(c0 - lon0) * ppd * s;
        const y = -(lat1 - c3) * ppd * s;
        const cellH = (c3 - c1) * ppd * s;
        return (
          <button
            key={f.t}
            className={`film-cell ${i === index ? "on" : ""} ${i < index ? "past" : ""}`}
            onClick={() => onPick(i)}
            aria-label={`Show the ${hhmm(f.t)} UTC frame`}
            aria-pressed={i === index}
          >
            <span className="film-img" style={{ aspectRatio: `100 / ${cellH}` }}>
              <img src={asset(f.file)} alt="" loading="lazy" style={{ width: `${1100 * s}%`, left: `${x}%`, top: `${(y / cellH) * 100}%` }} />
            </span>
            <span className="film-t">{hhmm(f.t)}</span>
          </button>
        );
      })}
    </div>
  );
}

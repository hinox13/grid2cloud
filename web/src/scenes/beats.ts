import type { TimeMode } from "../components/TimeRuler";

export type ChapterId = "clouds" | "energy" | "grid" | "genco" | "value" | "finale";

export const CHAPTERS: { id: Exclude<ChapterId, "finale">; name: string; explore: string; exploreLabel: string }[] = [
  { id: "clouds", name: "Clouds", explore: "/explore/events?e=jun15_cloud_clearing&t=08:45", exploreLabel: "All frames, three events" },
  { id: "energy", name: "Energy", explore: "/explore/events?e=jun15_cloud_clearing&t=11:30", exploreLabel: "Per-plant solar estimates" },
  { id: "grid", name: "Grid", explore: "/explore/events?e=jun15_cloud_clearing&t=11:00&m=AC", exploreLabel: "Every branch, every half-hour" },
  { id: "genco", name: "GENCO", explore: "/explore/journey", exploreLabel: "The full model journey" },
  { id: "value", name: "Value", explore: "/explore/value", exploreLabel: "The full economic study" },
];

/**
 * Which measurement a beat shows. The story moves between three that must never look interchangeable:
 * one historical moment (and its controlled counterfactual), the aggregate GENCO evaluation over all
 * real half-hours, and the economic case study of one 6 MW plant (one half-hour, one day or the season).
 */
export type Scope = { kind: "event"; cf?: boolean } | { kind: "aggregate" } | { kind: "economic"; span: "half-hour" | "day" | "season" };

export interface Beat {
  id: string;
  ch: ChapterId;
  /** milliseconds on this beat during the guided replay */
  dwell: number;
  time: { mode: TimeMode; t: string | null };
  scope: Scope | null;
  /** the GENCO chapter asks two questions: 1 how much is imported, 2 how import changes with solar */
  question?: 1 | 2;
}

const T = (hm: string) => `2024-06-15T${hm}:00Z`;
const EVENT: Scope = { kind: "event" };
const CF: Scope = { kind: "event", cf: true };
const AGG: Scope = { kind: "aggregate" };

// guided replay ≈ 95 s; every beat can be stepped through, paused or skipped
export const BEATS: Beat[] = [
  { id: "prologue", ch: "clouds", dwell: 6500, time: { mode: "history", t: T("08:45") }, scope: null },
  { id: "c-sky", ch: "clouds", dwell: 4000, time: { mode: "history", t: T("08:45") }, scope: EVENT },
  { id: "c-play", ch: "clouds", dwell: 5000, time: { mode: "history", t: null }, scope: EVENT },
  { id: "c-clear", ch: "clouds", dwell: 4000, time: { mode: "history", t: null }, scope: EVENT },
  { id: "e-wipe", ch: "energy", dwell: 4000, time: { mode: "history", t: T("11:30") }, scope: EVENT },
  { id: "e-curve", ch: "energy", dwell: 4000, time: { mode: "history", t: T("11:30") }, scope: EVENT },
  { id: "g-states", ch: "grid", dwell: 4500, time: { mode: "history", t: null }, scope: EVENT },
  { id: "g-why", ch: "grid", dwell: 4500, time: { mode: "history", t: T("11:30") }, scope: EVENT },
  { id: "g-freeze", ch: "grid", dwell: 5500, time: { mode: "frozen", t: T("11:00") }, scope: CF },
  { id: "j-zero", ch: "genco", dwell: 6000, time: { mode: "season", t: null }, scope: AGG, question: 1 },
  { id: "j-network", ch: "genco", dwell: 6000, time: { mode: "season", t: null }, scope: AGG, question: 1 },
  { id: "j-shift", ch: "genco", dwell: 5000, time: { mode: "season", t: null }, scope: AGG },
  { id: "i-cf", ch: "genco", dwell: 6500, time: { mode: "frozen", t: T("11:00") }, scope: CF, question: 2 },
  { id: "i-slope", ch: "genco", dwell: 5000, time: { mode: "season", t: null }, scope: AGG, question: 2 },
  { id: "j-two", ch: "genco", dwell: 5500, time: { mode: "season", t: null }, scope: AGG },
  { id: "v-value", ch: "value", dwell: 6500, time: { mode: "day", t: null }, scope: { kind: "economic", span: "day" } },
  { id: "v-half", ch: "value", dwell: 5500, time: { mode: "day", t: T("11:00") }, scope: { kind: "economic", span: "half-hour" } },
  { id: "v-season", ch: "value", dwell: 5500, time: { mode: "valued", t: null }, scope: { kind: "economic", span: "season" } },
  { id: "finale", ch: "finale", dwell: 0, time: { mode: "day", t: null }, scope: null },
];

export const firstBeat = (ch: ChapterId) => BEATS.findIndex((b) => b.ch === ch);
export const GUIDED_SECONDS = Math.round(BEATS.reduce((s, b) => s + b.dwell, 0) / 1000);

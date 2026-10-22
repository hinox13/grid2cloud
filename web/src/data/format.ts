// Presentation only: fixed-precision formatting with a true minus sign, and UTC clock labels.
import type { ModelId } from "./types";

export function num(x: number | null | undefined, digits = 1, signed = false): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "n/a";
  const s = Math.abs(x).toFixed(digits);
  const zero = Number(s) === 0;
  const sign = x < 0 && !zero ? "−" : signed && !zero ? "+" : "";
  const [int, dec] = s.split(".");
  return sign + int.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (dec ? "." + dec : "");
}

export const gbp = (x: number, digits = 0) => (x < 0 ? "−£" : "£") + num(Math.abs(x), digits);

export const hhmm = (iso: string) => iso.slice(11, 16);

export const ms = (iso: string) => Date.parse(iso);

export const MODEL_ORDER: ModelId[] = ["AC", "zero_shot", "E5", "E5b", "E5c", "E5d"];

export const MODEL_NAME: Record<ModelId, string> = {
  AC: "AC reference",
  zero_shot: "Off-the-shelf",
  E5: "Grid-tuned",
  E5b: "Envelope-tuned",
  E5c: "Generator-aware",
  E5d: "Response-aware",
};

export const MODEL_EXP: Record<ModelId, string> = { AC: "", zero_shot: "E4", E5: "E5", E5b: "E5b", E5c: "E5c", E5d: "E5d" };

/** CSS custom property holding the model's series colour (theme-aware). */
export const modelVar = (m: ModelId) => `var(--m-${m})`;

export function skyWord(kc: number | null | undefined): string {
  if (kc === null || kc === undefined) return "n/a";
  return kc >= 0.8 ? "clear" : kc >= 0.5 ? "broken cloud" : "overcast";
}

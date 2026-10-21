import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { Claim, Provenance } from "./types";

// Every request goes to this site's own static files: no external API at runtime.
export const BASE = import.meta.env.BASE_URL;
export const asset = (rel: string) => `${BASE}data/${rel}`;

const cache = new Map<string, Promise<unknown>>();

export function fetchJson<T>(rel: string): Promise<T> {
  if (!cache.has(rel)) {
    const p = fetch(asset(rel)).then((r) => {
      if (!r.ok) throw new Error(`${rel}: HTTP ${r.status}`);
      return r.json();
    });
    p.catch(() => cache.delete(rel)); // allow a retry after a failed load
    cache.set(rel, p);
  }
  return cache.get(rel) as Promise<T>;
}

export function useData<T>(rel: string | null): { data: T | null; error: string | null } {
  const [state, setState] = useState<{ rel: string | null; data: T | null; error: string | null }>({ rel, data: null, error: null });
  useEffect(() => {
    if (!rel) return;
    let live = true;
    fetchJson<T>(rel).then(
      (data) => live && setState({ rel, data, error: null }),
      (e: Error) => live && setState({ rel, data: null, error: e.message }),
    );
    return () => {
      live = false;
    };
  }, [rel]);
  return state.rel === rel ? { data: state.data, error: state.error } : { data: null, error: null };
}

// ------------------------------------------------------------------ claims
type ClaimMap = Record<string, Claim>;
const ClaimsCtx = createContext<ClaimMap | null>(null);

export function ClaimsProvider({ children }: { children: ReactNode }) {
  const { data, error } = useData<Claim[]>("claims.json");
  if (error) return <DataError what="the frozen figures (claims.json)" detail={error} />;
  if (!data) return <Loading />;
  const map = Object.fromEntries(data.map((c) => [c.id, c]));
  return <ClaimsCtx.Provider value={map}>{children}</ClaimsCtx.Provider>;
}

export function useClaims(): ClaimMap {
  const c = useContext(ClaimsCtx);
  if (!c) throw new Error("useClaims outside ClaimsProvider");
  return c;
}

const UNIT: Record<string, string> = { MW: " MW", MWh: " MWh", MVA: " MVA", "MW/MW": " MW per MW", "%": " %", "GBP/MWh": "/MWh" };

/** A frozen figure exactly as the Python export formatted it. `bare` omits the unit. */
export function Claim({ id, bare = false }: { id: string; bare?: boolean }) {
  const c = useClaims()[id];
  if (!c) return <span data-claim-missing={id}>n/a</span>;
  const unit = bare ? "" : (UNIT[c.unit] ?? "");
  return (
    <span className="claim" data-claim={id} data-prov={c.provenance} title={`${PROV_LABEL[c.provenance]} · ${c.source}${c.note ? ` · ${c.note}` : ""}`}>
      {c.display}
      {unit && <span className="unit">{unit}</span>}
    </span>
  );
}

export const PROV_LABEL: Record<Provenance, string> = {
  observed: "Observed",
  derived: "Derived",
  simulated: "Simulated",
  predicted: "Predicted",
  hypothetical: "Hypothetical",
};

export const PROV_ABOUT: Record<Provenance, string> = {
  observed: "recorded by an instrument or market: Meteosat imagery, Elexon prices",
  derived: "estimated from observations: satellite PV, UKPN loads",
  simulated: "AC power flow on the reconstructed network",
  predicted: "a frozen GENCO checkpoint's output",
  hypothetical: "a counterfactual: what would have happened under a clear sky",
};

export function Loading({ label = "Loading the frozen data" }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span>{label}…</span>
    </div>
  );
}

export function DataError({ what, detail }: { what: string; detail: string }) {
  return (
    <div className="data-error" role="alert">
      <p>
        <strong>Could not load {what}.</strong> The page needs its static data files; nothing is computed in the browser.
      </p>
      <p className="note">{detail}</p>
    </div>
  );
}

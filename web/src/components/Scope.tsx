import type { ReactNode } from "react";
import { Claim } from "../data/load";

// The evaluation scopes of the study, labelled the same way in the story and the Explorer so an
// average over thousands of half-hours, one historical moment, an economic total and a synthetic
// replication on a second network never read as the same kind of number. Each has its own glyph:
// one dot, a field of dots, a pound sign, two linked networks.

export type ScopeKind = "event" | "aggregate" | "economic" | "synthetic";
export type EconomicSpan = "half-hour" | "day" | "season";

function Glyph({ kind }: { kind: ScopeKind }) {
  return (
    <svg className="scope-glyph" viewBox="0 0 18 18" width="18" height="18" aria-hidden="true">
      {kind === "event" && (
        <>
          <circle cx="9" cy="9" r="7.2" fill="none" stroke="currentColor" strokeWidth="1.6" />
          <circle cx="9" cy="9" r="3.2" fill="currentColor" />
        </>
      )}
      {kind === "aggregate" && [0, 1, 2].flatMap((i) => [0, 1, 2].map((j) => <circle key={`${i}${j}`} cx={3 + i * 6} cy={3 + j * 6} r="1.9" fill="currentColor" />))}
      {kind === "synthetic" && (
        <>
          <circle cx="4.5" cy="9" r="3" fill="none" stroke="currentColor" strokeWidth="1.6" />
          <circle cx="13.5" cy="9" r="3" fill="none" stroke="currentColor" strokeWidth="1.6" />
          <line x1="7.5" y1="9" x2="10.5" y2="9" stroke="currentColor" strokeWidth="1.6" strokeDasharray="1.4 1.2" />
        </>
      )}
      {kind === "economic" && (
        <text x="9" y="14" textAnchor="middle" fontSize="15" fontWeight="700" fill="currentColor">
          £
        </text>
      )}
    </svg>
  );
}

export function ScopeTag({ kind, cf, span, className = "" }: { kind: ScopeKind; cf?: boolean; span?: EconomicSpan; className?: string }) {
  let k: ReactNode;
  let d: ReactNode;
  if (kind === "event") {
    k = cf ? "One moment · controlled counterfactual" : "One moment · historical event";
    d = cf ? <>15 June 2024, 11:00 UTC · only the 6 MW plant changes, all other inputs held fixed</> : <>15 June 2024, 08:45–12:15 UTC</>;
  } else if (kind === "aggregate") {
    k = "Average · GENCO evaluation";
    d = (
      <>
        all <Claim id="n_states" bare /> reconstructed real half-hours, <Claim id="states_span" bare />
      </>
    );
  } else if (kind === "synthetic") {
    k = "Second network · synthetic replication";
    d = (
      <>
        Aylesbury East · <Claim id="g2_test_states" bare /> held-out synthetic states, <Claim id="g2_pairs" bare /> paired solar changes
      </>
    );
  } else {
    k = (
      <>
        Economic case study · one <Claim id="plant_capacity" bare /> MW plant
      </>
    );
    d =
      span === "half-hour" ? (
        <>one half-hour, 15 June 2024 11:00–11:30 UTC</>
      ) : span === "season" ? (
        <>
          <Claim id="season_periods" bare /> half-hours over <Claim id="season_days" bare /> days, <Claim id="states_span" bare />
        </>
      ) : (
        <>
          one day, 15 June 2024 · <Claim id="day_periods" bare /> half-hours
        </>
      );
  }
  return (
    <p className={`scope scope-${kind} ${className}`} data-scope={kind}>
      <Glyph kind={kind} />
      <span className="scope-k">{k}</span>
      <span className="scope-d">{d}</span>
    </p>
  );
}

/** The scope as a short inline mark (glyph + a few words), for compact lists such as the closing chain. */
export function ScopeMark({ kind, children }: { kind: ScopeKind; children: ReactNode }) {
  return (
    <span className={`scope-mark mark-${kind}`} data-scope={kind}>
      <Glyph kind={kind} />
      <span className="scope-mark-t">{children}</span>
    </span>
  );
}

/** The two questions of the GENCO chapter, set as the title of the visual. */
export function Question({ n }: { n: 1 | 2 }) {
  return (
    <p className={`question q-${n}`} data-question={n}>
      <span className="question-n">Question {n}</span>
      <span className="question-t">{n === 1 ? "How much electricity does the grid import on average?" : "When solar generation increases, does GENCO predict the correct change in grid import?"}</span>
    </p>
  );
}

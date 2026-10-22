import { Claim, Loading, useData } from "../data/load";

// The second network (Aylesbury East): every seed of every arm on the held-out synthetic test data.
// A synthetic replication only; the real-data reconstruction of this network failed validation.

export interface G2Run {
  run: string;
  arm: "B" | "C" | "D";
  seed: number;
  import_mae_mw: number;
  import_bias_mw: number;
  import_r: number;
  pbe_mean_mva: number;
  vm_mae_pu: number;
  export_recall: number;
  pred_vs_ac_slope: number;
  pv_slope_ratio: number;
  pv_rel_err: number;
  load_slope_ratio: number;
}

export interface Research {
  second_network: {
    replication: { runs: G2Run[]; hypotheses: Record<string, boolean>; hypothesis_text: Record<string, string>; arms: Record<string, string> };
  };
  sundon_runs: { runs: { run: string; experiment: string; lambda: number | null; seed: number | null; selected: boolean; note: string; PBE_mean: number; import_bias_mw: number; import_mae_mw: number; import_corr: number; pv_slope_ratio: number; load_slope_ratio: number; chap31_slope_ratio: number }[] };
}

export const ARM_LABEL: Record<G2Run["arm"], [string, string]> = {
  B: ["Ordinary, envelope", "E5b-like"],
  C: ["Ordinary, generators", "E5c-like"],
  D: ["Response-aware", "E5d recipe"],
};
const ARM_VAR: Record<G2Run["arm"], string> = { B: "var(--m-E5b)", C: "var(--m-E5c)", D: "var(--m-E5d)" };

/** PV slope ratio and import error for every seed of the three Aylesbury arms. */
export function ReplicationStrip({ compact = false }: { compact?: boolean }) {
  const { data } = useData<Research>("research.json");
  if (!data) return <Loading label="" />;
  const runs = data.second_network.replication.runs;
  const R1 = 1.25;
  const rp = (x: number) => (Math.max(0, Math.min(R1, x)) / R1) * 100;
  const M1 = 30;
  const mp = (x: number) => (Math.min(M1, x) / M1) * 100;
  return (
    <figure className={`score repl ${compact ? "is-compact" : ""}`} aria-label="Aylesbury East, synthetic test data: PV response ratio and import error for every seed">
      <div className="score-head">
        <span />
        <span>
          <strong>Solar response</strong>
          <em>
            GENCO ÷ AC import change per MW of PV, <Claim id="g2_pairs" bare /> held-out synthetic pairs; band 0.8–1.2
          </em>
        </span>
        {!compact && (
          <span>
            <strong>Absolute state</strong>
            <em>
              import error, MW, on <Claim id="g2_test_states" bare /> held-out synthetic states (shorter is better)
            </em>
          </span>
        )}
      </div>
      {(["B", "C", "D"] as const).map((arm) => {
        const rs = runs.filter((r) => r.arm === arm).sort((a, b) => a.seed - b.seed);
        return (
          <div key={arm} className="score-row" data-arm={arm}>
            <span className="score-name">
              <i style={{ background: ARM_VAR[arm] }} />
              <span>
                {ARM_LABEL[arm][0]} <span className="iax-exp">{ARM_LABEL[arm][1]}</span>
              </span>
            </span>
            <span className="score-cell">
              <span className="score-track resp">
                <span className="repl-band" style={{ left: `${rp(0.8)}%`, width: `${rp(1.2) - rp(0.8)}%` }} />
                <span className="score-target" style={{ left: `${rp(1)}%` }} />
                {rs.map((r) => {
                  const ok = r.pv_slope_ratio >= 0.8 && r.pv_slope_ratio <= 1.2;
                  return (
                    <span
                      key={r.seed}
                      className={`score-dot repl-dot ${arm === "D" && !ok ? "is-failed" : ""}`}
                      style={{ left: `${rp(r.pv_slope_ratio)}%`, background: arm === "D" && !ok ? "transparent" : ARM_VAR[arm], borderColor: ARM_VAR[arm] }}
                      title={`seed ${r.seed}: ratio ${r.pv_slope_ratio.toFixed(2)}`}
                    />
                  );
                })}
              </span>
              <span className="score-val">{rs.map((r) => r.pv_slope_ratio.toFixed(2)).join(" · ")}</span>
            </span>
            {!compact && (
              <span className="score-cell">
                <span className="score-track">
                  {rs.map((r) => (
                    <span key={r.seed} className="repl-tick" style={{ left: `${mp(r.import_mae_mw)}%`, background: ARM_VAR[arm] }} title={`seed ${r.seed}: ${r.import_mae_mw.toFixed(1)} MW`} />
                  ))}
                </span>
                <span className="score-val">{rs.map((r) => r.import_mae_mw.toFixed(1)).join(" · ")}</span>
              </span>
            )}
          </div>
        );
      })}
      <p className="score-note">
        Seeds 0 · 1 · 2. The hollow dot is the response-aware seed that failed (ratio <Claim id="g2_D_bad_ratio" bare />). Synthetic AC states only: the real-data reconstruction of this network failed its validation.
      </p>
    </figure>
  );
}

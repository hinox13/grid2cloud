import type { ReactNode } from "react";
import { Claim, useClaims } from "../data/load";
import type { ModelId } from "../data/types";

// The model journey: five published adaptation stages, each evaluated on the same 2,829 real
// half-hourly states (aggregate evaluation, not the 15 June event). Two separate dimensions:
// state accuracy (how far the import level sits from the AC reference) and response accuracy
// (how the import moves per MW of solar). Every figure is a frozen claim.

export type Stage = Exclude<ModelId, "AC">;
export const STAGES: Stage[] = ["zero_shot", "E5", "E5b", "E5c", "E5d"];

export interface StageText {
  name: string;
  tag: string;
  change: ReactNode;
  fixed: ReactNode;
  left: ReactNode;
  next: ReactNode;
  caveat?: ReactNode;
}

export const STAGE_TEXT: Record<Stage, StageText> = {
  zero_shot: {
    name: "Original GENCO",
    tag: "E4 · zero-shot",
    change: "Pretrained on synthetic grids and used as published. It had never seen the Sundon network.",
    fixed: "Nothing yet: this is the starting point.",
    left: (
      <>
        It predicts <Claim id="import_mean_zero_shot" /> where the AC reference imports <Claim id="import_mean_AC" />: export instead of import in <Claim id="zero_shot_wrong_sign" /> of real states.
      </>
    ),
    next: "It had never seen this topology, so the first step was to teach it the network.",
  },
  E5: {
    name: "Grid-tuned",
    tag: "E5 · grid adaptation",
    change: "Fine-tuned on synthetic operating states of the reconstructed Sundon network.",
    fixed: (
      <>
        The direction of the import is right in <Claim id="sign_acc_E5" /> of real states, and synthetic states are fitted well.
      </>
    ),
    left: (
      <>
        Real operation is still poor: offset <Claim id="bias_E5" />, power-balance error <Claim id="pbe_E5" />, and the import barely follows the physics (r <Claim id="corr_E5" />).
      </>
    ),
    next: "Real loads, battery and solar lay outside the range of the synthetic training states.",
  },
  E5b: {
    name: "Envelope-tuned",
    tag: "E5b · operating envelope",
    change: "Synthetic states sampled across the real operating range of loads, battery and generation, from public metadata only.",
    fixed: (
      <>
        Power-balance error <Claim id="pbe_zero_shot" bare /> → <Claim id="pbe_E5b" /> (original → E5b); the import offset falls to <Claim id="bias_E5b" />.
      </>
    ),
    left: (
      <>
        Solar response <Claim id="slope_E5b" />: still blind to solar. Import and voltage criteria still fail.
      </>
    ),
    next: "Solar plants were not yet represented as generators.",
  },
  E5c: {
    name: "Generator-aware",
    tag: "E5c · explicit generators",
    change: "Solar and wind plants represented as explicit generators in the training states.",
    fixed: (
      <>
        Import tracking r <Claim id="corr_E5c" />; battery response <Claim id="slope_battery_E5c" /> (physics <Claim id="slope_battery_AC" />).
      </>
    ),
    left: (
      <>
        Solar response <Claim id="slope_E5c" />. In the ordinary loss a solar signal of at most 6 MW barely counts beside load swings of tens of MW.
      </>
    ),
    caveat: (
      <>
        <strong>Generator encoding.</strong> From E5c on, our representation places the Leighton Buzzard generators on PQ buses, so their generation is left out of the model's internal physics feedback. Evaluation uses the correct generation values, so the metrics stand, but conclusions about ordinary GENCO fine-tuning beyond our implementation are limited.
      </>
    ),
    next: "Teach the response directly, not only the states.",
  },
  E5d: {
    name: "Response-aware",
    tag: "E5d · response supervision",
    change: "A new loss on pairs of synthetic AC states that differ in one input: solar, the battery or one load.",
    fixed: (
      <>
        Solar response <Claim id="slope_E5d" /> (physics <Claim id="slope_AC" />; E5c <Claim id="slope_E5c" bare />); load <Claim id="slope_load_E5d" /> (physics <Claim id="slope_load_AC" />). On held-out synthetic pairs, a matched run without the new loss stayed blind to solar (ratio <Claim id="l0_syn_ratio" bare />).
      </>
    ),
    left: (
      <>
        Offset <Claim id="bias_E5d" /> and power-balance error <Claim id="pbe_E5d" />, both worse than E5b; the battery response overshoots (<Claim id="slope_battery_E5d" />). Only this training seed learned the response this well: with seeds 1 and 2 the response reached <Claim id="e5d_s1_ratio" bare /> and <Claim id="e5d_s2_ratio" bare /> of the physics, with offsets <Claim id="e5d_s1_bias" /> and <Claim id="e5d_s2_bias" />. Pre-registered verdict: partial.
      </>
    ),
    next: "Open: calibrate the level without losing the response, and make it stable across seeds (future work, not attempted here).",
  },
};

const NAME: Record<ModelId, string> = { AC: "AC reference", zero_shot: "Original GENCO", E5: "Grid-tuned", E5b: "Envelope-tuned", E5c: "Generator-aware", E5d: "Response-aware" };
const EXP: Record<ModelId, string> = { AC: "physics", zero_shot: "E4", E5: "E5", E5b: "E5b", E5c: "E5c", E5d: "E5d" };

/**
 * Average import over all real states as a horizontal power-flow comparison: export to the left,
 * import to the right, the AC reference as a dashed target. Hidden rows keep their place.
 */
export function ImportAxis({ rows, hidden = [], focus, withAC = false }: { rows: Stage[]; hidden?: Stage[]; focus?: Stage; withAC?: boolean }) {
  const c = useClaims();
  const D0 = -235;
  const D1 = 190;
  const pct = (v: number) => ((v - D0) / (D1 - D0)) * 100;
  const z = pct(0);
  const ac = c.import_mean_AC.value ?? 0;
  return (
    <figure className={`iax ${focus ? "has-focus" : ""}`} aria-label="Average grid import by model against the AC reference">
      <figcaption className="sr-only">
        Average import over all real states: AC {c.import_mean_AC.display} MW;{" "}
        {rows.filter((r) => !hidden.includes(r)).map((r) => `${NAME[r]} ${c[`import_mean_${r}`].display} MW`).join("; ")}.
      </figcaption>
      <div className="iax-regions" aria-hidden="true">
        <span style={{ width: `${z}%` }}>← Export: power flows out of Sundon</span>
        <span style={{ width: `${100 - z}%` }}>Import: power flows in →</span>
      </div>
      <div className="iax-plot">
        <div className="iax-lines" aria-hidden="true">
          <div className="iax-zero" style={{ left: `${z}%` }} />
          <div className="iax-ac" style={{ left: `${pct(ac)}%` }}>
            {!withAC && (
              <span>
                AC reference <Claim id="import_mean_AC" />
              </span>
            )}
          </div>
        </div>
        {withAC && (
          <div className="iax-row is-ac is-focus" data-stage="AC" style={{ ["--c" as string]: "var(--m-AC)" }}>
            <span className="iax-name">
              AC reference <span className="iax-exp">physics</span>
            </span>
            <span className="iax-track">
              <span className="iax-bar" style={{ left: `${z}%`, width: `${pct(ac) - z}%` }} />
              <span className="iax-val" style={{ left: `${pct(ac)}%` }}>
                <Claim id="import_mean_AC" />
                <span className="iax-off">power flows in</span>
              </span>
            </span>
          </div>
        )}
        {rows.map((m) => {
          const v = c[`import_mean_${m}`].value ?? 0;
          const off = hidden.includes(m);
          const left = Math.min(z, pct(v));
          const width = Math.abs(pct(v) - z);
          return (
            <div key={m} className={`iax-row ${off ? "is-off" : ""} ${focus === m ? "is-focus" : ""} ${v < 0 ? "is-export" : ""}`} data-stage={m} style={{ ["--c" as string]: `var(--m-${m})` }}>
              <span className="iax-name">
                {NAME[m]} <span className="iax-exp">{EXP[m]}</span>
              </span>
              <span className="iax-track">
                <span className="iax-bar" style={{ left: `${left}%`, width: off ? 0 : `${width}%` }} />
                {!off && (
                  <span className={`iax-val ${v < 0 ? "inside" : ""}`} style={v < 0 ? { left: `${left}%` } : { left: `${left + width}%` }}>
                    <Claim id={`import_mean_${m}`} />
                    <span className="iax-off">
                      offset <Claim id={`bias_${m}`} />
                    </span>
                  </span>
                )}
              </span>
            </div>
          );
        })}
      </div>
      <p className="iax-note">Average power drawn from the national grid over the same {c.n_states.display} reconstructed real half-hours of 2024. The reference is an AC reconstruction informed by observations, not a measured grid state.</p>
    </figure>
  );
}

/** State accuracy and response accuracy, side by side and labelled separately. */
export function Scoreboard({ focus, show = STAGES }: { focus?: Stage[]; show?: Stage[] }) {
  const c = useClaims();
  const v = (id: string) => c[id].value ?? 0;
  // state: |offset| on a log scale, 1 to 300 MW (shorter bar = closer to the physics)
  const lg = (x: number) => ((Math.log10(Math.max(1, Math.abs(x))) - 0) / (Math.log10(300) - 0)) * 100;
  // response: −1.4 … +0.2 MW per MW
  const R0 = -1.4;
  const R1 = 0.2;
  const rp = (x: number) => ((x - R0) / (R1 - R0)) * 100;
  const acs = v("slope_AC");
  return (
    <figure className="score" aria-label="State accuracy and solar-response accuracy by model">
      <div className="score-head">
        <span />
        <span>
          <strong>Question 1 · the amount</strong>
          <em>import bias: how far the average import sits from the physics, MW (shorter is better, log scale)</em>
        </span>
        <span>
          <strong>Question 2 · the response</strong>
          <em>MW of import per MW of solar; the dashed line is the physics, <Claim id="slope_AC" bare /></em>
        </span>
      </div>
      {STAGES.filter((m) => show.includes(m)).map((m) => {
        const bias = v(`bias_${m}`);
        const s = v(`slope_${m}`);
        const unusable = m === "E5";
        return (
          <div key={m} className={`score-row ${focus?.includes(m) ? "is-focus" : ""}`} data-stage={m}>
            <span className="score-name">
              <i style={{ background: `var(--m-${m})` }} />
              {NAME[m]} <span className="iax-exp">{EXP[m]}</span>
            </span>
            <span className="score-cell">
              <span className="score-track">
                <span className="score-bar" style={{ width: `${lg(bias)}%`, background: `var(--m-${m})` }} />
              </span>
              <span className="score-val">
                <Claim id={`bias_${m}`} />
                <small>
                  PBE <Claim id={`pbe_${m}`} bare /> MVA
                </small>
              </span>
            </span>
            <span className="score-cell">
              <span className="score-track resp">
                <span className="score-target" style={{ left: `${rp(acs)}%` }} />
                <span className="score-zero" style={{ left: `${rp(0)}%` }} />
                <span className={`score-dot ${unusable ? "is-unusable" : ""}`} style={{ left: `${rp(s)}%`, background: unusable ? "transparent" : `var(--m-${m})`, borderColor: `var(--m-${m})` }} />
              </span>
              <span className="score-val">{unusable ? <span title={`fitted ${c.slope_E5.display}, but import r ${c.corr_E5.display}`}>not usable</span> : <Claim id={`slope_${m}`} bare />}</span>
            </span>
          </div>
        );
      })}
      <p className="score-note">
        Closest on most absolute-state metrics: envelope-tuned (E5b). Only response-aware (E5d) responds to solar like the physics. E5d is not better on every metric: its offset and power-balance error are larger than E5b's. Grid-tuned's fitted slope is not a usable response because its import barely follows the physics (r <Claim id="corr_E5" bare />).
      </p>
    </figure>
  );
}

/**
 * The turn of the GENCO chapter: E5b answers the first question (the amount) but not the second
 * (the change when solar rises). Same model, same 2,829 states, two different measures and units.
 */
export function TwoQuestions() {
  const c = useClaims();
  const v = (id: string) => c[id].value ?? 0;
  const lvl = (x: number) => `${(x / 60) * 100}%`;
  const rsp = (x: number) => `${(Math.abs(x) / 1.2) * 100}%`;
  return (
    <figure className="twoq" aria-label={`Envelope-tuned GENCO (E5b) on both questions. Amount: ${c.import_mean_E5b.display} MW average import against ${c.import_mean_AC.display} MW for the physics. Response: ${c.slope_E5b.display} MW per MW of solar against ${c.slope_AC.display} for the physics.`}>
      <div className="twoq-card is-yes">
        <p className="twoq-q">
          <span>Question 1 · the amount</span>How much electricity does the grid import on average?
        </p>
        <div className="twoq-bars" aria-hidden="true">
          <span className="twoq-row">
            <span className="twoq-name">AC reference</span>
            <span className="twoq-track">
              <span style={{ width: lvl(v("import_mean_AC")), background: "var(--m-AC)" }} />
            </span>
            <Claim id="import_mean_AC" />
          </span>
          <span className="twoq-row">
            <span className="twoq-name">E5b</span>
            <span className="twoq-track">
              <span style={{ width: lvl(v("import_mean_E5b")), background: "var(--m-E5b)" }} />
            </span>
            <Claim id="import_mean_E5b" />
          </span>
        </div>
        <p className="twoq-verdict">
          <b>Close.</b> Bias <Claim id="bias_E5b" />, a level in MW.
        </p>
      </div>
      <div className="twoq-card is-no">
        <p className="twoq-q">
          <span>Question 2 · the response</span>When solar generation rises by 1 MW, how much does import change?
        </p>
        <div className="twoq-bars is-change" aria-hidden="true">
          <span className="twoq-row">
            <span className="twoq-name">AC reference</span>
            <span className="twoq-track">
              <span style={{ width: rsp(v("slope_AC")), background: "var(--m-AC)" }} />
            </span>
            <Claim id="slope_AC" bare />
          </span>
          <span className="twoq-row">
            <span className="twoq-name">E5b</span>
            <span className="twoq-track">
              <span style={{ width: rsp(v("slope_E5b")), background: "var(--m-E5b)" }} />
            </span>
            <Claim id="slope_E5b" bare />
          </span>
        </div>
        <p className="twoq-unit">MW of import per MW of solar; bars grow left from zero (less import)</p>
        <p className="twoq-verdict">
          <b>Barely moves.</b> The physics drops about 1 MW of import per extra MW of solar; E5b hardly reacts.
        </p>
      </div>
    </figure>
  );
}

/** Physical consistency: mean power-balance error per stage, log scale (a different measure from the import offset). */
export function PbeStrip({ rows, hidden = [] }: { rows: Stage[]; hidden?: Stage[] }) {
  const c = useClaims();
  const lg = (x: number) => ((Math.log10(x) - Math.log10(0.1)) / (Math.log10(100) - Math.log10(0.1))) * 100;
  return (
    <figure className="pbe" aria-label="Power-balance error by stage">
      <figcaption>
        <strong>Physical consistency</strong> · power-balance error of the predicted grid state (MVA, log scale; 0 for the physics)
      </figcaption>
      {rows.map((m) => (
        <div key={m} className={`pbe-row ${hidden.includes(m) ? "is-off" : ""}`} data-stage={m}>
          <span className="pbe-name">{NAME[m]}</span>
          <span className="pbe-track">
            <span className="pbe-bar" style={{ width: hidden.includes(m) ? 0 : `${lg(c[`pbe_${m}`].value ?? 0.1)}%`, background: `var(--m-${m})` }} />
          </span>
          <span className="pbe-val">{hidden.includes(m) ? "" : <Claim id={`pbe_${m}`} />}</span>
        </div>
      ))}
    </figure>
  );
}

/** Fitted solar sensitivity across all real states (MW of import per MW of solar), against the physics. */
export function SlopeStrip({ rows, hidden = [] }: { rows: Stage[]; hidden?: Stage[] }) {
  const c = useClaims();
  const R0 = -1.3;
  const R1 = 0.15;
  const rp = (x: number) => ((x - R0) / (R1 - R0)) * 100;
  return (
    <figure className="slope-strip" aria-label="Fitted solar sensitivity by model">
      <figcaption>
        <strong>Across all <Claim id="n_states" bare /> real half-hours</strong> · fitted sensitivity, MW of import per MW of solar
      </figcaption>
      <div className="ss-axis" aria-hidden="true">
        <span style={{ left: `${rp(-1)}%` }}>−1</span>
        <span style={{ left: `${rp(-0.5)}%` }}>−0.5</span>
        <span style={{ left: `${rp(0)}%` }}>0</span>
      </div>
      {rows.map((m) => (
        <div key={m} className={`ss-row ${hidden.includes(m) ? "is-off" : ""}`} data-stage={m}>
          <span className="pbe-name">{NAME[m]}</span>
          <span className="ss-track">
            <span className="score-target" style={{ left: `${rp(c.slope_AC.value ?? -1)}%` }} />
            <span className="score-zero" style={{ left: `${rp(0)}%` }} />
            {!hidden.includes(m) && <span className="score-dot" style={{ left: `${rp(c[`slope_${m}`].value ?? 0)}%`, background: `var(--m-${m})`, borderColor: `var(--m-${m})` }} />}
          </span>
          <span className="pbe-val">{hidden.includes(m) ? "" : <Claim id={`slope_${m}`} />}</span>
        </div>
      ))}
      <p className="ss-note">
        Dashed: the AC reference, <Claim id="slope_AC" />. A slope, fitted over all states; not the 11:00 response above.
      </p>
    </figure>
  );
}

/**
 * Two models, two different strengths: E5b and E5d side by side on the same 2,829 states, with the
 * absolute state (the amount) and the solar response (the change) scored separately. The better
 * model on each row is marked; neither wins both rows.
 */
export function TradeOff({ compact = false }: { compact?: boolean }) {
  const c = useClaims();
  const v = (id: string) => c[id].value ?? 0;
  const lg = (x: number) => (Math.log10(Math.max(1, Math.abs(x))) / Math.log10(20)) * 100; // |bias| 1 … 20 MW
  const rp = (x: number) => (Math.min(1.25, Math.abs(x)) / 1.25) * 100; // |slope| 0 … 1.25 MW/MW
  const cell = (m: "E5b" | "E5d", row: "state" | "resp") => {
    const better = row === "state" ? m === "E5b" : m === "E5d";
    return (
      <div className={`to-cell ${better ? "is-better" : ""}`} data-model={m} data-row={row}>
        <span className={`to-mark ${better ? "" : "is-empty"}`} aria-hidden={!better}>
          {better ? "Stronger" : "\u00a0"}
        </span>
        {row === "state" ? (
          <>
            <span className="to-v">
              <Claim id={`bias_${m}`} />
            </span>
            <span className="to-track" aria-hidden="true">
              <span style={{ width: `${lg(v(`bias_${m}`))}%`, background: `var(--m-${m})` }} />
            </span>
            <span className="to-s">
              import bias; power-balance error <Claim id={`pbe_${m}`} />
            </span>
          </>
        ) : (
          <>
            <span className="to-v">
              <Claim id={`slope_${m}`} />
            </span>
            <span className="to-track is-resp" aria-hidden="true">
              <span style={{ width: `${rp(v(`slope_${m}`))}%`, background: `var(--m-${m})` }} />
              <i style={{ left: `${rp(v("slope_AC"))}%` }} />
            </span>
            <span className="to-s">
              <Claim id={`ratio_pv_${m}`} /> of the AC reference response (<Claim id="slope_AC" bare />)
            </span>
          </>
        )}
      </div>
    );
  };
  return (
    <figure className={`tradeoff ${compact ? "is-compact" : ""}`} aria-label="Envelope-tuned E5b against response-aware E5d: absolute state and solar response, scored separately">
      <div className="to-grid">
        <span className="to-corner" />
        {(["E5b", "E5d"] as const).map((m) => (
          <span key={m} className="to-model" style={{ ["--c" as string]: `var(--m-${m})` }}>
            <i />
            {NAME[m]} <span className="iax-exp">{m}</span>
          </span>
        ))}
        <span className="to-row-h">
          <strong>Absolute state</strong>
          <em>how much is imported: average gap to the AC reference (shorter is better)</em>
        </span>
        {cell("E5b", "state")}
        {cell("E5d", "state")}
        <span className="to-row-h">
          <strong>Solar response</strong>
          <em>MW of import per MW of solar, fitted; the tick is the AC reference for the reconstructed network</em>
        </span>
        {cell("E5b", "resp")}
        {cell("E5d", "resp")}
      </div>
      <figcaption className="to-note">
        Same <Claim id="n_states" bare /> reconstructed half-hours, same AC targets. <strong>Neither model does both:</strong> E5d did not keep E5b's absolute accuracy.
        {!compact && (
          <>
            {" "}
            Not every metric favours E5b: E5d follows the import's variation more closely (r <Claim id="corr_E5d" bare /> against <Claim id="corr_E5b" bare />) and has the lower voltage error (<Claim id="vm_mae_E5d" /> against <Claim id="vm_mae_E5b" />).
          </>
        )}
      </figcaption>
    </figure>
  );
}

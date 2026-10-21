import { Loading, useData } from "../data/load";
import { MODEL_NAME, num } from "../data/format";
import type { ModelId, ModelsData } from "../data/types";
import { Callout, ModelName, PageHead, Section } from "./ui";

const VERDICTS: Record<string, string> = {
  zero_shot: "Off-the-shelf (E4): fails. GENCO as published cannot transfer to the Sundon topology: it predicts about 211 MW of export where AC gives about 49 MW of import.",
  E5: "Grid-tuned (E5): verdict D. Fine-tuning on standard synthetic Sundon states fits held-out synthetic states but does not transfer to real operation.",
  E5b: "Envelope-tuned (E5b): E5B-C, partial. Fine-tuning on a broad physics-informed synthetic envelope cuts real-state error by about 99 % (vs grid-tuned); import (R3) and voltage (R4) criteria still fail.",
  E5c: "Generator-aware (E5c): E5C-B. Explicit generator nodes improve load and battery tracking, but the solar response stays near zero (R3, R4, R5 fail). Selection flagged: no run passed the synthetic gate.",
  E5d: "Response-aware (E5d): E5D-D, partial. An extra loss on paired synthetic AC states (one input changed: solar, battery or a load) teaches the response; no real or weather data was used for training or selection. The synthetic solar response is learned (slope ratio 0.997 on held-out pairs) and transfers to real operation (solar slope −0.04 → −1.07, AC −1.02; load 0.61 → 0.93). The full gate still fails: import bias +13 MW (R3), Vm MAE 0.0109 pu (R4), battery overshoot 1.17 (R6). Selection flagged: no run passed the static synthetic gate.",
};

type Row = Record<string, number | [number, number]>;

const METRICS: { col: string; title: string; log?: boolean; ref?: number; digits: number; signed?: boolean; better: string }[] = [
  { col: "PBE_mean", title: "Power-balance error (MVA)", log: true, digits: 2, better: "lower is better" },
  { col: "import_mae_mw", title: "Grid import error (MW)", log: true, digits: 1, better: "lower is better" },
  { col: "genco_slope_pv", title: "Solar slope (MW per MW)", ref: -1.02, digits: 2, signed: true, better: "closer to AC −1.02" },
  { col: "import_corr", title: "Import correlation with AC", ref: 1, digits: 2, better: "higher is better" },
  { col: "vm_tracking_median_r", title: "Voltage tracking r (median)", ref: 1, digits: 2, better: "higher is better" },
  { col: "genco_slope_chap31", title: "Battery slope (MW per MW)", ref: 1.0, digits: 2, signed: true, better: "closer to AC +1.00" },
];

export function Models() {
  const { data } = useData<ModelsData>("models.json");
  if (!data) return <Loading />;
  const evo = Object.fromEntries(data.evolution.map((r) => [r.model, r as unknown as Row])) as Record<string, Row>;
  const v = (m: string, c: string) => evo[m][c] as number;
  const ci = (m: string, c: string) => {
    const x = evo[m][`${c}_ci`];
    return Array.isArray(x) ? ` [${num(x[0], 3)}, ${num(x[1], 3)}]` : "";
  };
  const ids = data.models.map((m) => m.id);
  return (
    <>
      <PageHead title="Model evolution" lead={`Every number below is a frozen, published result on the same ${v("E5d", "n").toLocaleString("en-GB")} real half-hourly 2024 states. Checkpoints were selected on synthetic data only and frozen before any real state was evaluated.`}>
        <Callout>
          This is not a ranking by version number, and there is no "best model": each stage fixed a different failure mode. The envelope-tuned model has the lowest real-state error; the generator-aware model the best import variance and battery response; the response-aware model is the only one with the physical solar and load sensitivity, but with a larger import bias. None passes the full pre-registered real-transfer gate. <strong>Synthetic-to-real transfer needs topology and operating-envelope coverage, and explicit learning of physically meaningful sensitivities.</strong>
        </Callout>
      </PageHead>

      <Section title="The five GENCO models">
        <div className="model-rows">
          {data.models.map((m) => (
            <div key={m.id} className="model-row" style={{ borderLeftColor: `var(--m-${m.id})` }}>
              <ModelName m={m.id} />
              <p>{m.about}.</p>
              <p className="note">
                Result: {m.verdict}. Run <code>{m.selected_run}</code>
                {m.checkpoint_sha256 ? (
                  <>
                    , checkpoint <code title={m.checkpoint_sha256}>{m.checkpoint_sha256.slice(0, 16)}…</code>
                  </>
                ) : (
                  <>, {m.checkpoint_ref}</>
                )}
                {m.registry ? `, selection ${m.selection_flagged ? "flagged fallback" : "gated"}` : ", off-the-shelf"}.
              </p>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Real-state metrics" scope={{ kind: "aggregate" }} aside={<p className="note">95 % block-bootstrap confidence intervals, resampled by day, in brackets. PBE = mean nodal power-balance error; Vm tracking r = median per-bus correlation of predicted and AC voltage over time.</p>}>
        <div className="table-wrap">
          <table className="ex-table">
            <thead>
              <tr>
                <th scope="col">Model</th>
                <th scope="col" className="num">
                  PBE (MVA) ↓
                </th>
                <th scope="col" className="num">
                  Active residual (MW) ↓
                </th>
                <th scope="col" className="num">
                  Import r ↑
                </th>
                <th scope="col" className="num">
                  Import MAE (MW) ↓
                </th>
                <th scope="col" className="num">
                  Vm tracking r ↑
                </th>
                <th scope="col" className="num">
                  Vm MAE (pu) ↓
                </th>
                <th scope="col" className="num">
                  Solar slope (AC −1.02)
                </th>
              </tr>
            </thead>
            <tbody>
              {ids.map((m) => (
                <tr key={m}>
                  <td>
                    <ModelName m={m} />
                  </td>
                  <td className="num">
                    {num(v(m, "PBE_mean"), v(m, "PBE_mean") < 1 ? 3 : 1)}
                    <span className="ci">{ci(m, "PBE_mean")}</span>
                  </td>
                  <td className="num">
                    {num(v(m, "P_residual"), v(m, "P_residual") < 1 ? 3 : 1)}
                    <span className="ci">{ci(m, "P_residual")}</span>
                  </td>
                  <td className="num">{num(v(m, "import_corr"), 2)}</td>
                  <td className="num">{num(v(m, "import_mae_mw"), 1)}</td>
                  <td className="num">{num(v(m, "vm_tracking_median_r"), 2, true)}</td>
                  <td className="num">
                    {num(v(m, "V_error"), 4)}
                    <span className="ci">{ci(m, "V_error")}</span>
                  </td>
                  <td className="num">{num(v(m, "genco_slope_pv"), 2, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="metric-grid">
          {METRICS.map((mt) => (
            <MetricBars key={mt.col} {...mt} ids={ids} value={(m) => v(m, mt.col)} />
          ))}
        </div>
      </Section>

      <Section title="Verdicts (pre-registered)">
        <ul className="ex-list verdicts">
          {ids.map((m) => (
            <li key={m} style={{ borderLeftColor: `var(--m-${m})` }}>
              {VERDICTS[m]}
            </li>
          ))}
        </ul>
        <p className="note">
          Sources: reports/tables/e5d_real_transfer.csv and e5d_response_transfer.csv (every model on the same states), copied verbatim into the Explorer bundle; their sha256 are listed on the Data page. Frozen checkpoints and a CPU verification script are in the <a href="https://github.com/hinox13/grid2cloud/releases/tag/cloud2grid-models-v1">cloud2grid-models-v1</a> release.
        </p>
      </Section>
    </>
  );
}

function MetricBars({ title, log, ref, digits, signed, better, ids, value }: { title: string; log?: boolean; ref?: number; digits: number; signed?: boolean; better: string; ids: ModelId[]; value: (m: ModelId) => number }) {
  const vals = ids.map(value);
  const tf = (x: number) => (log ? Math.log10(Math.max(1e-3, Math.abs(x))) : x);
  const all = [...vals.map(tf), ...(ref !== undefined ? [tf(ref)] : []), 0];
  const lo = log ? Math.min(...vals.map(tf)) - 0.3 : Math.min(...all);
  const hi = log ? Math.max(...vals.map(tf)) + 0.2 : Math.max(...all);
  const pct = (x: number) => ((tf(x) - lo) / (hi - lo || 1)) * 100;
  const zero = log ? 0 : pct(0);
  return (
    <figure className="metric">
      <figcaption>
        <strong>{title}</strong> <span className="note">{better}{log ? " · log scale" : ""}</span>
      </figcaption>
      {ids.map((m, i) => {
        const p = pct(vals[i]);
        return (
          <div key={m} className="metric-row">
            <span className="metric-name">{MODEL_NAME[m]}</span>
            <span className="metric-track">
              {ref !== undefined && <i className="metric-ref" style={{ left: `${pct(ref)}%` }} />}
              <i className="metric-fill" style={{ left: `${Math.min(zero, p)}%`, width: `${Math.max(0.8, Math.abs(p - zero))}%`, background: `var(--m-${m})` }} />
            </span>
            <span className="metric-val">{num(vals[i], digits, signed)}</span>
          </div>
        );
      })}
    </figure>
  );
}

import { Loading, PROV_ABOUT, PROV_LABEL, useData } from "../data/load";
import type { Attribution, Claim as ClaimT, ModelsData, Provenance } from "../data/types";
import { ModelName, PageHead, Prov, Section } from "./ui";

interface Manifest {
  schema: string;
  generator: string;
  inputs: Record<string, string>;
  outputs: Record<string, string>;
}

export function Data() {
  const att = useData<Attribution>("attribution.json");
  const mods = useData<ModelsData>("models.json");
  const man = useData<Manifest>("manifest.json");
  const claims = useData<ClaimT[]>("claims.json");
  if (!att.data || !mods.data || !man.data || !claims.data) return <Loading />;
  const A = att.data;
  const outs = Object.entries(man.data.outputs);
  const frames = outs.filter(([k]) => k.endsWith(".webp"));
  return (
    <>
      <PageHead title="Data, licences and reproducibility" lead="This site redistributes only derived and processed data whose licences allow it. Every source passed the project's licence gate for redistribute_derived when the bundles were built. Nothing is fetched from another service while you use it." />

      <Section title="Provenance classes">
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Table, scrolls sideways on small screens">
          <table className="ex-table">
            <tbody>
              {(Object.keys(PROV_LABEL) as Provenance[]).map((k) => (
                <tr key={k}>
                  <th scope="row">
                    <Prov kind={k} />
                  </th>
                  <td>{PROV_ABOUT[k]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Sources and credits">
        <ul className="ex-list credits">
          {A.sources.map((s) => (
            <li key={s.source_id}>
              <code>{s.source_id}</code>: {s.attribution.replace("[year]", "2024")}{" "}
              {s.licence_url && (
                <a href={s.licence_url} target="_blank" rel="noopener">
                  {s.licence}
                </a>
              )}
            </li>
          ))}
          {A.economic_sources.map((s) => (
            <li key={s.name}>
              {s.name}: {s.attribution ?? s.licence}{" "}
              {s.licence_url && (
                <a href={s.licence_url} target="_blank" rel="noopener">
                  {s.licence}
                </a>
              )}
            </li>
          ))}
        </ul>
        <p className="ex-callout">{A.modified_notice}</p>
      </Section>

      <Section title="What this site contains" aside={<p className="note">Exported by {man.data.generator} (schema {man.data.schema}) from the committed Explorer bundles in data/demo; nothing else is read.</p>}>
        <ul className="ex-list">
          <li>
            <strong>{frames.length} Meteosat E-View frames</strong> for the three events, copied byte for byte from the published bundle (WebP, unchanged extent).
          </li>
          <li>Satellite irradiance and estimated PV at registered PV assets (asset id, capacity, location; no customer fields).</li>
          <li>The reconstructed Sundon network: node names, voltages, schematic positions and published coordinates where known.</li>
          <li>AC and frozen-GENCO states for the events, the published summary tables, the 2,829-state response table and the Cloud Impact bundle with Elexon prices.</li>
          <li>
            <strong>Not included:</strong> raw satellite files, raw UKPN files, model weights, credentials, unpublished experiments.
          </li>
        </ul>
      </Section>

      <Section title="Reproducibility">
        <h3 className="ex-h3">Checks anyone can run from the public repository</h3>
        <ul className="ex-list">
          <li>
            <code>python scripts/web/export_web_data.py --check</code>: rebuilds every file of this site from data/demo and compares byte for byte.
          </li>
          <li>
            <code>pytest tests/web</code>: re-derives every figure the Experience states from the parquet bundles, aligns timestamps and settlement periods, re-checks MW × 0.5 h and MWh × £/MWh, model labels and frame hashes.
          </li>
          <li>
            <code>python scripts/economic_impact/verify_economic.py</code>: the 15 June numbers from the frozen bundle and the season totals from the released per-half-hour table.
          </li>
          <li>
            <code>python reproduce/verify_models.py</code> (release cloud2grid-models-v1): verifies the frozen checkpoints on CPU in a few minutes.
          </li>
        </ul>
        <h3 className="ex-h3">What needs local research data that is not redistributed</h3>
        <ul className="ex-list">
          <li>Re-solving the AC power flows and counterfactuals, and re-running GENCO over all real states.</li>
          <li>Rebuilding data/demo itself (scripts/build_demo_events.py) from the raw satellite and UKPN inputs.</li>
        </ul>
        <p className="note">
          Explorer bundle schema {A.bundle.schema_version}, built from research commit <code>{A.bundle.git_commit.slice(0, 10)}</code>.
        </p>
      </Section>

      <Section title="Frozen checkpoints">
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Table, scrolls sideways on small screens">
          <table className="ex-table">
            <thead>
              <tr>
                <th scope="col">Model</th>
                <th scope="col">Run</th>
                <th scope="col">Checkpoint</th>
                <th scope="col">Registry</th>
              </tr>
            </thead>
            <tbody>
              {mods.data.models.map((m) => (
                <tr key={m.id}>
                  <td>
                    <ModelName m={m.id} />
                  </td>
                  <td>
                    <code>{m.selected_run}</code>
                  </td>
                  <td>
                    <code className="hash">{m.checkpoint_sha256 ?? m.checkpoint_ref}</code>
                  </td>
                  <td>{m.registry ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Table, scrolls sideways on small screens">
          <table className="ex-table">
            <caption>Published tables used (sha256)</caption>
            <tbody>
              {Object.entries(mods.data.published_tables).map(([k, v]) => (
                <tr key={k}>
                  <td>
                    <code>{k}</code>
                  </td>
                  <td>
                    <code className="hash">{v}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Every figure the Experience states" aside={<p className="note">Written once by the export pipeline; the page only displays these strings. Hover any figure on the site to see its class and source.</p>}>
        <details className="ex-details">
          <summary>{claims.data.length} frozen figures</summary>
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Table, scrolls sideways on small screens">
            <table className="ex-table dense">
              <thead>
                <tr>
                  <th scope="col">Id</th>
                  <th scope="col" className="num">
                    Shown
                  </th>
                  <th scope="col">Unit</th>
                  <th scope="col">Class</th>
                  <th scope="col">Source</th>
                </tr>
              </thead>
              <tbody>
                {claims.data.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <code>{c.id}</code>
                    </td>
                    <td className="num">{c.display}</td>
                    <td>{c.unit}</td>
                    <td>{PROV_LABEL[c.provenance]}</td>
                    <td>
                      {c.source}
                      {c.note && <span className="note"> · {c.note}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </Section>

      <Section title="Licence-gate decisions">
        <details className="ex-details">
          <summary>{A.gate_decisions.length + A.economic_gate_decisions.length} decisions</summary>
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Table, scrolls sideways on small screens">
            <table className="ex-table dense">
              <thead>
                <tr>
                  {Object.keys(A.gate_decisions[0]).map((k) => (
                    <th key={k} scope="col">
                      {k}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...A.gate_decisions, ...A.economic_gate_decisions].map((g, i) => (
                  <tr key={i}>
                    {Object.keys(A.gate_decisions[0]).map((k) => (
                      <td key={k}>{String(g[k] ?? "")}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </Section>

      <Section title="Files of this site">
        <details className="ex-details">
          <summary>{outs.length} files with sha256</summary>
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Table, scrolls sideways on small screens">
            <table className="ex-table dense">
              <tbody>
                {outs.map(([k, v]) => (
                  <tr key={k}>
                    <td>
                      <code>data/{k}</code>
                    </td>
                    <td>
                      <code className="hash">{v}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </Section>
    </>
  );
}

import { ARM_LABEL, ReplicationStrip, type Research } from "../components/replication";
import { Claim, Loading, useData } from "../data/load";
import { num } from "../data/format";
import { Callout, PageHead, Section, Tiles } from "./ui";

const REPO = "https://github.com/hinox13/grid2cloud";

/** The second network: a pre-registered synthetic replication on Aylesbury East, with its failed real-data validation. */
export function Replication() {
  const { data } = useData<Research>("research.json");
  if (!data) return <Loading />;
  const rep = data.second_network.replication;
  return (
    <>
      <PageHead
        title="A second network: Aylesbury East"
        lead="Does the Sundon pattern recur on another network? A pre-registered replication on a larger UK Power Networks 33 kV network with more solar, GENCO fine-tuned again from the same pretrained checkpoint, and every seed reported."
      >
        <Callout tone="warn">
          <strong>Synthetic states only.</strong> This network's real-data reconstruction failed its pre-registered validation, so the replication uses AC power-flow states sampled from public metadata, with AC as the reference. It says nothing about Aylesbury's real 2024 operation or about weather, and it is independent retraining on this network, not the Sundon model reused.
        </Callout>
      </PageHead>

      <Section title="The answer" scope={{ kind: "synthetic" }}>
        <Tiles
          items={[
            { k: "Ordinary fine-tuning (E5c-like)", v: <Claim id="g2_C_pv_slope_ratio" bare />, s: "of the physical solar response, three seeds: largely blind, as at Sundon" },
            { k: "Response-aware (E5d recipe)", v: <Claim id="g2_D_pv_slope_ratio_ok" bare />, s: <>of the physical response, in <Claim id="g2_D_ok_seeds" bare /> seeds</> },
            { k: "The third seed", v: <Claim id="g2_D_bad_ratio" bare />, s: <>failed: import error <Claim id="g2_D_bad_mae" />; synthetic validation flagged it</> },
            { k: "Pre-registered classification", v: <Claim id="g2_classification" bare />, s: "H1–H6 hold; H7, stability across all three seeds, fails" },
          ]}
        />
        <p className="ex-p">
          The central Sundon observation recurred: ordinary synthetic fine-tuning improves the absolute state but leaves GENCO largely insensitive to solar, and the response-aware loss recovers the physical response. Response learning was less stable here: one of three seeds failed completely.
        </p>
      </Section>

      <Section title="Every seed" scope={{ kind: "synthetic" }}>
        <ReplicationStrip />
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Table, scrolls sideways on small screens">
          <table className="ex-table">
            <caption>Every run on the held-out synthetic test data, against AC</caption>
            <thead>
              <tr>
                <th scope="col">Arm</th>
                <th scope="col" className="num">
                  Seed
                </th>
                <th scope="col" className="num">
                  Solar response (÷ AC)
                </th>
                <th scope="col" className="num">
                  Load response (÷ AC)
                </th>
                <th scope="col" className="num">
                  Import MAE (MW)
                </th>
                <th scope="col" className="num">
                  Import bias (MW)
                </th>
                <th scope="col" className="num">
                  Import r
                </th>
                <th scope="col" className="num">
                  PBE (MVA)
                </th>
                <th scope="col" className="num">
                  Exports found
                </th>
              </tr>
            </thead>
            <tbody>
              {rep.runs.map((r) => (
                <tr key={r.run}>
                  <td>
                    {ARM_LABEL[r.arm][0]} <span className="ci">{ARM_LABEL[r.arm][1]}</span>
                  </td>
                  <td className="num">{r.seed}</td>
                  <td className="num">{num(r.pv_slope_ratio, 2)}</td>
                  <td className="num">{num(r.load_slope_ratio, 2)}</td>
                  <td className="num">{num(r.import_mae_mw, 1)}</td>
                  <td className="num">{num(r.import_bias_mw, 1, true)}</td>
                  <td className="num">{num(r.import_r, 2)}</td>
                  <td className="num">{num(r.pbe_mean_mva, 2)}</td>
                  <td className="num">{num(r.export_recall * 100, 0)} %</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="note">
          Responses on <Claim id="g2_pairs" bare /> held-out pairs of AC states that differ only in solar (or one load); absolute metrics on <Claim id="g2_test_states" bare /> held-out states, including contingencies, of which <Claim id="g2_export_states" bare /> export. "Exports found": share of exporting states where the model also predicts an export. AC import standard deviation <Claim id="g2_ac_std" />.
        </p>
      </Section>

      <Section title="Does the E5b/E5d trade-off recur?" scope={{ kind: "synthetic" }}>
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Table, scrolls sideways on small screens">
          <table className="ex-table">
            <caption>Range over seeds (response-aware: the two successful seeds)</caption>
            <thead>
              <tr>
                <th scope="col">Arm</th>
                <th scope="col" className="num">
                  Import MAE
                </th>
                <th scope="col" className="num">
                  Power-balance error
                </th>
                <th scope="col" className="num">
                  Solar response (÷ AC)
                </th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Ordinary, envelope (E5b-like)</td>
                <td className="num">
                  <Claim id="g2_B_import_mae_mw" />
                </td>
                <td className="num">
                  <Claim id="g2_B_pbe_mean_mva" />
                </td>
                <td className="num">
                  <Claim id="g2_B_pv_slope_ratio" bare />
                </td>
              </tr>
              <tr>
                <td>Ordinary, generators (E5c-like)</td>
                <td className="num">
                  <Claim id="g2_C_import_mae_mw" />
                </td>
                <td className="num">
                  <Claim id="g2_C_pbe_mean_mva" />
                </td>
                <td className="num">
                  <Claim id="g2_C_pv_slope_ratio" bare />
                </td>
              </tr>
              <tr>
                <td>Response-aware (E5d recipe)</td>
                <td className="num">
                  <Claim id="g2_D_import_mae_mw_ok" />
                </td>
                <td className="num">
                  <Claim id="g2_D_pbe_mean_mva_ok" />
                </td>
                <td className="num">
                  <Claim id="g2_D_pv_slope_ratio_ok" bare />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <ul className="ex-list">
          <li>
            <strong>Not in the same form.</strong> On this network's synthetic test, the successful response-aware seeds were also closer on the absolute state than ordinary fine-tuning. A sizeable error remained: the predicted import is compressed toward its mean, and exporting states are recognised only about two times in three.
          </li>
          <li>
            <strong>Not like for like with Sundon.</strong> Sundon's trade-off (import bias E5b <Claim id="bias_E5b" /> against E5d <Claim id="bias_E5d" />) was measured on the <Claim id="n_states" bare /> reconstructed real half-hours. Here only synthetic states exist. The arms also differ in detail: arm B uses the same sampling pool as C and D, and C and D use GraphKit's corrected generator decoder, where Sundon's E5c and E5d used the original one.
          </li>
          <li>
            <strong>What does recur:</strong> an accurate response with a substantial, sign-coherent absolute import error (H5, H6), and a response that not every seed learns.
          </li>
        </ul>
      </Section>

      <Section title="Two networks, one method">
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Table, scrolls sideways on small screens">
          <table className="ex-table">
            <thead>
              <tr>
                <th scope="col" />
                <th scope="col">Sundon</th>
                <th scope="col">Aylesbury East</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Network, as built from public LTDS data</td>
                <td>
                  <Claim id="n_buses" bare /> buses
                </td>
                <td>
                  <Claim id="g2_buses" bare /> buses, <Claim id="g2_lines" bare /> lines, <Claim id="g2_trafos" bare /> transformers
                </td>
              </tr>
              <tr>
                <td>Generation varied in the study</td>
                <td>
                  one <Claim id="plant_capacity" bare /> MW solar plant (<Claim id="other_pv_capacity" /> more inside the metered loads)
                </td>
                <td>
                  <Claim id="g2_solar_mw" /> solar and <Claim id="g2_wind_mw" /> wind at the 33 kV busbars
                </td>
              </tr>
              <tr>
                <td>Battery</td>
                <td>yes</td>
                <td>none</td>
              </tr>
              <tr>
                <td>Real-data validation of the reconstruction</td>
                <td>passed: usable with limitations</td>
                <td>failed (below)</td>
              </tr>
              <tr>
                <td>GENCO evaluated on</td>
                <td>
                  <Claim id="n_states" bare /> reconstructed real half-hours, and synthetic tests
                </td>
                <td>synthetic tests only</td>
              </tr>
              <tr>
                <td>Training</td>
                <td colSpan={2}>the same pretrained GENCO checkpoint, fine-tuned separately on each network's synthetic states; selected on synthetic validation and frozen before testing</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="note">The two networks differ in topology, size and solar share at once, so no difference between them is attributed to any one of these.</p>
      </Section>

      <Section title="Why the real-data validation failed">
        <Tiles
          items={[
            { k: "Grid import, NMAE", v: <Claim id="g2_val_nmae" bare />, s: "passes (≤ 0.25)" },
            { k: "Core circuits fitted", v: <Claim id="g2_val_core" />, s: "fails (≥ 60 % required)" },
            { k: "Worst circuit direction", v: <Claim id="g2_val_direction" bare />, s: "fails (≥ 0.90 required): one grid-transformer section flows the opposite way" },
            { k: "Import residual vs solar, |r|", v: <Claim id="g2_val_resid_r" bare />, s: "fails (≤ 0.50 required)" },
          ]}
        />
        <p className="ex-p">
          A post-hoc regression explains the solar failure: the measured import falls by about <Claim id="g2_obs_pv_slope" bare /> MW per MW of satellite-derived solar, where the model implies about −1. Only about half of the estimated solar appears in the measured import, for reasons public data cannot separate (export limits, curtailment, connection points, or the solar model itself). As pre-registered, the study stopped: GENCO was never trained or evaluated on Aylesbury's real states.
        </p>
      </Section>

      <Section title="Can it test spatial weather?">
        <p className="ex-p">
          No. <Claim id="g2_pixel_share" /> of the network's active solar (<Claim id="g2_pixel_mw" /> of <Claim id="g2_active_pv_mw" />) lies in one native satellite pixel: three farms within about 1.5 km. The pre-registered requirement of at least three pixels failed, so this network cannot show whether the spatial structure of clouds matters, and the synthetic replication reads no weather at all.
        </p>
      </Section>

      <Section title="Pre-registered hypotheses">
        <ul className="ex-list hyp-list">
          {Object.entries(rep.hypotheses).map(([k, ok]) => (
            <li key={k} data-holds={ok}>
              <strong>
                {k} {ok ? "holds" : "fails"}.
              </strong>{" "}
              {rep.hypothesis_text[k]}
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Method and reproduction">
        <ul className="ex-list">
          <li>
            <strong>Pre-registration.</strong> Hypotheses, arms and classification rule were committed before any data or training; two amendments (the response-loss scale by the E5d rule, and the zero-shot normaliser) were recorded before they took effect. Checkpoints were frozen with SHA256 hashes before any test prediction, which the code refuses until the freeze.
          </li>
          <li>
            <strong>Arms.</strong> Four arms, three seeds each, 10,000 training states, the official GraphKit recipe: zero-shot; ordinary fine-tuning with generation as negative demand (E5b-like); ordinary fine-tuning with explicit generators (E5c-like); the same with the response-aware loss (E5d recipe).
          </li>
          <li>
            <strong>Data.</strong> Synthetic states sampled from public metadata only (load ranges, registered generation), solved with AC power flow. No real series, satellite value or validation result was read; a read guard enforces this.
          </li>
          <li>
            <strong>Limits.</strong> Three seeds per arm, no significance tests; one second network; synthetic only.
          </li>
          <li>
            <strong>Report.</strong> Tables, configuration and verification steps in <a href={`${REPO}/blob/main/reports/g2/SECOND_NETWORK_REPORT.md`} target="_blank" rel="noopener">reports/g2/SECOND_NETWORK_REPORT.md</a>; every figure on this page is exported from <code>data/demo/research/second_network.json</code>, which rebuilds from the published tables.
          </li>
        </ul>
        <p className="note">
          The development history holds the full pre-registration. The public repository is <a href={REPO}>hinox13/grid2cloud</a>.
        </p>
      </Section>
    </>
  );
}

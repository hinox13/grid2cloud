import { ScopeMark, type ScopeKind } from "../components/Scope";
import { Claim } from "../data/load";

const REPO = "https://github.com/hinox13/grid2cloud";

export function Finale({ onReplay }: { onReplay: () => void }) {
  const links: { k: string; v: React.ReactNode; s: React.ReactNode; scope: ScopeKind; where: React.ReactNode }[] = [
    { k: "Clouds", v: <><Claim id="cloudy_frac_start" bare /> → <Claim id="cloudy_frac_end" /></>, s: "cloudy share of the satellite field", scope: "event", where: "one moment, 15 June" },
    { k: "Energy", v: <Claim id="fleet_pv_delta" />, s: "estimated solar, 11:00 → 11:30", scope: "event", where: "one moment, 15 June" },
    { k: "Grid", v: <Claim id="cf_AC_1100" />, s: "change in import, solar alone, at 11:00", scope: "event", where: "one moment, counterfactual" },
    { k: "GENCO learns the grid", v: <><Claim id="bias_zero_shot" bare /> → <Claim id="bias_E5b" /></>, s: "import bias, original → E5b", scope: "aggregate", where: <>average, <Claim id="n_states" bare /> half-hours</> },
    { k: "GENCO learns the response", v: <><Claim id="slope_E5c" bare /> → <Claim id="slope_E5d" bare /></>, s: <>MW per MW of solar, E5c → E5d; physics <Claim id="slope_AC" bare /></>, scope: "aggregate", where: <>fitted, <Claim id="n_states" bare /> half-hours</> },
    { k: "Value", v: <Claim id="day_cloud_gbp" />, s: "illustrative, one 6 MW plant", scope: "economic", where: <>one day, <Claim id="day_periods" bare /> half-hours</> },
  ];
  return (
    <main className="finale">
      <section className="finale-close">
        <h1 className="finale-h">
          From clouds to grid
          <br />
          to value.
        </h1>
        <p className="finale-takeaway">Two models, two different strengths, one unresolved challenge: E5b came closer on the amount, E5d on the response, and no model yet gets both.</p>
        <ol className="chain" aria-label="The chain of consequences">
          {links.map((l) => (
            <li key={l.k}>
              <span className="chain-k">{l.k}</span>
              <span className="chain-v">{l.v}</span>
              <span className="chain-s">{l.s}</span>
              <ScopeMark kind={l.scope}>{l.where}</ScopeMark>
            </li>
          ))}
        </ol>
        <div className="finale-actions">
          <a className="btn btn-primary btn-large" href="#/explore">
            Explore the science
          </a>
          <button className="btn btn-secondary" onClick={onReplay}>
            Replay the event
          </button>
          <a className="btn-text" href={REPO} target="_blank" rel="noopener">
            Source, models and verification on GitHub
          </a>
        </div>
        <div className="finale-body">
          <p>
            Real satellite observations, a real reconstructed network, and a foundation model that went from predicting the wrong flow direction to learning the network, and then how it responds to sunlight, from synthetic data alone. On a second network, Aylesbury East, the same pattern recurred on synthetic states: ordinary fine-tuning recovered <Claim id="g2_C_pv_slope_ratio" bare /> of the physical solar response, response-aware training <Claim id="g2_D_pv_slope_ratio_ok" bare /> in <Claim id="g2_D_ok_seeds" bare /> seeds.
          </p>
          <p>
            What remains: the response-aware model's import is <Claim id="bias_E5d" /> off on average and only one training seed learned the response this well, so it is not an operational estimator, and AC power flow stays the reference. Whether satellite-observed weather itself changes GENCO's accuracy remains unresolved: the first test found no measurable effect, but beneath an error floor that made it uninformative, and the pre-registered re-test runs only after full real transfer, which no model achieved. The next tests are a calibrated level that keeps the response, seed stability, and a second network that passes real-data validation.
          </p>
        </div>
      </section>
    </main>
  );
}

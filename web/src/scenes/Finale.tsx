import { ScopeMark, type ScopeKind } from "../components/Scope";
import { Claim } from "../data/load";

const REPO = "https://github.com/hinox13/grid2cloud";

export function Finale({ onReplay }: { onReplay: () => void }) {
  const links: { k: string; v: React.ReactNode; s: React.ReactNode; scope: ScopeKind; where: React.ReactNode }[] = [
    { k: "Clouds", v: <><Claim id="cloudy_frac_start" bare /> → <Claim id="cloudy_frac_end" /></>, s: "cloudy share of the satellite field", scope: "event", where: "one moment, 15 June" },
    { k: "Energy", v: <Claim id="fleet_pv_delta" />, s: "estimated solar, 11:00 → 11:30", scope: "event", where: "one moment, 15 June" },
    { k: "Grid", v: <Claim id="cf_AC_1100" />, s: "change in import, solar alone, at 11:00", scope: "event", where: "one moment, counterfactual" },
    { k: "GENCO learns the grid", v: <><Claim id="bias_zero_shot" bare /> → <Claim id="bias_E5b" /></>, s: "import bias, original → E5b", scope: "aggregate", where: <>average, <Claim id="n_states" bare /> half-hours</> },
    { k: "GENCO learns the response", v: <><Claim id="slope_E5c" bare /> → <Claim id="slope_E5d" /></>, s: <>per MW of solar; physics <Claim id="slope_AC" bare /></>, scope: "aggregate", where: <>fitted, <Claim id="n_states" bare /> half-hours</> },
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
        <p className="finale-takeaway">First we taught GENCO the network. Then we taught it the physical response. These are different problems.</p>
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
            Real satellite observations, a real reconstructed network, and a foundation model that went from predicting the wrong flow direction to learning the network, and then how it responds to sunlight, from synthetic data alone.
          </p>
          <p>
            What remains: its absolute import is <Claim id="bias_E5d" /> off on average, so it is not an operational estimator, and AC power flow stays the reference on this network. A calibration step and a second network are the next tests.
          </p>
        </div>
      </section>
    </main>
  );
}

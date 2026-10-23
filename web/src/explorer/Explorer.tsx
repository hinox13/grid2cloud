import { useEffect, useState, type ReactNode } from "react";
import { ThemeToggle } from "../components/theme";
import { Wordmark } from "../components/Wordmark";
import { SiteFooter } from "../scenes/Home";
import { Data } from "./Data";
import { Events } from "./Events";
import { Journey } from "./Journey";
import { Models } from "./Models";
import { Rail, RailProvider } from "./Rail";
import { Replication } from "./Replication";
import { Response } from "./Response";
import { Science } from "./Science";
import { Value } from "./Value";

// The research environment: same data, components and visual language as the Experience.
const VIEWS: { path: string; name: string; title: string; el: (p: URLSearchParams) => ReactNode }[] = [
  { path: "/explore/journey", name: "Model journey", title: "How we taught GENCO this network", el: (p) => <Journey params={p} /> },
  { path: "/explore/events", name: "Grid events", title: "Weather events", el: (p) => <Events params={p} /> },
  { path: "/explore/response", name: "PV response", title: "The PV response", el: (p) => <Response params={p} /> },
  { path: "/explore/replication", name: "Second network", title: "A second network", el: () => <Replication /> },
  { path: "/explore/models", name: "Model metrics", title: "Model evolution", el: () => <Models /> },
  { path: "/explore/value", name: "Value", title: "Cloud impact and value", el: () => <Value /> },
  { path: "/explore", name: "Methods", title: "The scientific story", el: () => <Science /> },
  { path: "/explore/data", name: "Data & credits", title: "Data, licences and reproducibility", el: () => <Data /> },
];

export default function Explorer({ path, params }: { path: string; params: URLSearchParams }) {
  const view = VIEWS.find((v) => v.path === path.replace(/\/$/, "")) ?? VIEWS.find((v) => v.path === "/explore")!;
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  useEffect(() => {
    document.title = `${view.title} · Cloud2Grid`;
    return () => {
      document.title = "Cloud2Grid";
    };
  }, [view]);
  return (
    <div className="explorer">
      <header className="ex-head">
        <Wordmark />
        <nav className="ex-nav" aria-label="Explorer">
          {VIEWS.map((v) => (
            <a key={v.path} href={`#${v.path}`} aria-current={v === view ? "page" : undefined}>
              {v.name}
            </a>
          ))}
        </nav>
        <div className="ex-actions">
          <a className="btn-text" href="#/experience">
            The experience
          </a>
          <ThemeToggle />
        </div>
      </header>
      <div className="ex-layout">
        <Rail viewKey={view.path} slotRef={setSlot} />
        <RailProvider slot={slot}>
          <main className="ex-main" key={view.path}>
            {view.el(params)}
          </main>
        </RailProvider>
      </div>
      <SiteFooter />
    </div>
  );
}

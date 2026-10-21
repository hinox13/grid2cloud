import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Claim, PROV_LABEL } from "../data/load";
import type { Provenance } from "../data/types";
import { Prov } from "./ui";

// The Explorer's left rail: where am I on this page, the figures a reviewer keeps checking, and the
// provenance key. A view can add its own controls to the rail through <RailExtra>.

const SlotCtx = createContext<HTMLElement | null>(null);

export function RailExtra({ children }: { children: ReactNode }) {
  const el = useContext(SlotCtx);
  return el ? createPortal(children, el) : null;
}

export function RailProvider({ slot, children }: { slot: HTMLElement | null; children: ReactNode }) {
  return <SlotCtx.Provider value={slot}>{children}</SlotCtx.Provider>;
}

const SHORT: Record<Provenance, string> = {
  observed: "instrument or market record",
  derived: "estimated from observations",
  simulated: "AC power flow",
  predicted: "a frozen GENCO model",
  hypothetical: "a counterfactual",
};

interface Item {
  id: string;
  title: string;
}

export function Rail({ viewKey, slotRef }: { viewKey: string; slotRef: (el: HTMLDivElement | null) => void }) {
  const [items, setItems] = useState<Item[]>([]);
  const [active, setActive] = useState("");

  // the section index follows whatever the view rendered (views load their data asynchronously)
  useEffect(() => {
    const main = document.querySelector(".ex-main");
    if (!main) return;
    const scan = () => {
      const next = [...main.querySelectorAll<HTMLElement>(".ex-section[id]")].map((s) => ({ id: s.id, title: s.dataset.title ?? "" }));
      setItems((prev) => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next));
    };
    scan();
    const mo = new MutationObserver(scan);
    mo.observe(main, { childList: true, subtree: true });
    return () => mo.disconnect();
  }, [viewKey]);

  // highlight the section being read
  useEffect(() => {
    if (!items.length) return;
    const seen = new Map<string, boolean>();
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => seen.set(e.target.id, e.isIntersecting));
        const first = items.find((it) => seen.get(it.id));
        if (first) setActive(first.id);
      },
      { rootMargin: "-80px 0px -55% 0px" },
    );
    items.forEach((it) => {
      const el = document.getElementById(it.id);
      if (el) io.observe(el);
    });
    return () => io.disconnect();
  }, [items]);

  // hash routing owns location.hash, so the index scrolls instead of linking to #anchors
  const go = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    setActive(id);
  };

  return (
    <aside className="ex-rail" aria-label="Page tools">
      <div ref={slotRef} className="rail-slot" />
      {items.length > 1 && (
        <nav className="rail-block" aria-label="On this page">
          <p className="rail-h">On this page</p>
          <ul className="rail-toc">
            {items.map((it) => (
              <li key={it.id}>
                <button className={it.id === active ? "on" : ""} aria-current={it.id === active ? "location" : undefined} onClick={() => go(it.id)}>
                  {it.title}
                </button>
              </li>
            ))}
          </ul>
        </nav>
      )}
      <div className="rail-block">
        <p className="rail-h">At a glance</p>
        <dl className="rail-facts">
          <div>
            <dt>Solar sensitivity, AC physics</dt>
            <dd>
              <Claim id="slope_AC" />
            </dd>
          </div>
          <div>
            <dt>Ordinary adapted GENCO (E5c)</dt>
            <dd>
              <Claim id="slope_E5c" />
            </dd>
          </div>
          <div>
            <dt>Response-aware GENCO (E5d)</dt>
            <dd>
              <Claim id="slope_E5d" />
            </dd>
          </div>
          <div>
            <dt>E5d import bias</dt>
            <dd>
              <Claim id="bias_E5d" />
            </dd>
          </div>
          <div>
            <dt>Clouds' extra import, 15 June</dt>
            <dd>
              <Claim id="day_cloud_mwh" /> · <Claim id="day_cloud_gbp" />
            </dd>
          </div>
        </dl>
        <p className="rail-note">
          Over <Claim id="n_states" bare /> real half-hours of 2024; the value is illustrative.
        </p>
      </div>
      <div className="rail-block">
        <p className="rail-h">What the tags mean</p>
        <ul className="rail-prov">
          {(Object.keys(PROV_LABEL) as Provenance[]).map((k) => (
            <li key={k}>
              <Prov kind={k} /> <span>{SHORT[k]}</span>
            </li>
          ))}
        </ul>
        <a className="rail-link" href="#/explore/data">
          Sources and verification
        </a>
      </div>
    </aside>
  );
}

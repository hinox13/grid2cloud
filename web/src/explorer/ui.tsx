import type { ComponentProps, ReactNode } from "react";
import { ScopeTag } from "../components/Scope";
import { PROV_LABEL } from "../data/load";
import { MODEL_EXP, MODEL_NAME } from "../data/format";
import type { ModelId, Provenance } from "../data/types";

export function PageHead({ title, lead, children }: { title: ReactNode; lead?: ReactNode; children?: ReactNode }) {
  return (
    <section className={`ex-pagehead ${children ? "has-aside" : ""}`}>
      <div className="ex-pagehead-main">
        <h1 className="ex-h1">{title}</h1>
        {lead && <p className="ex-lead">{lead}</p>}
      </div>
      {children && <div className="ex-pagehead-aside">{children}</div>}
    </section>
  );
}

const slug = (s: string) => "s-" + s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

/** One section of an Explorer page; its title feeds the rail's "On this page" index. */
export function Section({ title, id, children, aside, scope }: { title: string; id?: string; children: ReactNode; aside?: ReactNode; scope?: ComponentProps<typeof ScopeTag> }) {
  return (
    <section className="ex-section" id={id ?? slug(title)} data-title={title}>
      <h2 className="ex-h2">{title}</h2>
      {scope && <ScopeTag {...scope} />}
      {aside && <div className="ex-aside">{aside}</div>}
      {children}
    </section>
  );
}

export function Prov({ kind }: { kind: Provenance }) {
  return <span className={`prov-tag prov-${kind}`}>{PROV_LABEL[kind]}</span>;
}

export function ModelName({ m }: { m: ModelId }) {
  return (
    <span className="model-name">
      <i className="swatch" style={{ background: `var(--m-${m})` }} />
      {MODEL_NAME[m]}
      {MODEL_EXP[m] && <span className="exp-tag">{MODEL_EXP[m]}</span>}
    </span>
  );
}

export function Tiles({ items }: { items: { k: ReactNode; v: ReactNode; s?: ReactNode }[] }) {
  return (
    <div className="ex-tiles">
      {items.map((t, i) => (
        <div key={i} className="ex-tile">
          <span className="k">{t.k}</span>
          <span className="v">{t.v}</span>
          {t.s && <span className="s">{t.s}</span>}
        </div>
      ))}
    </div>
  );
}

export function Callout({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" }) {
  return <div className={`ex-callout tone-${tone}`}>{children}</div>;
}

export function Seg<T extends string>({ value, options, onChange, label }: { value: T; options: [T, ReactNode][]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="seg" role="radiogroup" aria-label={label}>
      {options.map(([k, l]) => (
        <button key={k} role="radio" aria-checked={value === k} className={value === k ? "on" : ""} onClick={() => onChange(k)}>
          {l}
        </button>
      ))}
    </div>
  );
}

export const setParams = (path: string, p: Record<string, string>) => {
  history.replaceState(null, "", `#${path}?${new URLSearchParams(p).toString()}`);
};

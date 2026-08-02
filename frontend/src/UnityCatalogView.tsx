import { useEffect, useState } from "react";
import { explorerApi, type Named } from "./explorerApi";
import { useSpotlight } from "./useSpotlight";
import { Icon } from "./Icon";

// G17 — the Unity Catalog section.
//
// This deliberately does NOT render a second <DatabricksTree />. The tree is
// mounted once, in the persistent Data Explorer panel; mounting it again here
// produced two independent instances with two catalog fetches and divergent
// expansion state — the exact duplication the persistent panel exists to
// remove (it was previously duplicated between Explorer and the chat sidebar).
// Instead this gives the target its own summary and hands browsing back to the
// one real tree.

export function UnityCatalogView({ onRevealInExplorer }: { onRevealInExplorer: () => void }) {
  const { spotlightProps } = useSpotlight();
  const [catalogs, setCatalogs] = useState<Named[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    explorerApi
      .databricksCatalogs()
      .then(setCatalogs)
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <div className="uc-view">
      <section className="card card-spotlight uc-card" {...spotlightProps}>
        <div className="uc-card-head">
          <span className="icon-tile uc-tile">
            <Icon name="catalog" size={21} />
          </span>
          <div>
            <span className="eyebrow">Target</span>
            <h2 className="uc-title">Unity Catalog</h2>
          </div>
        </div>

        <p className="muted">
          Every migration in this app writes into{" "}
          <span className="mono">lakebridge_demo.g3_migrations</span>, chosen by the backend (see{" "}
          <span className="mono">databricks_target.py</span>) rather than by the UI. Browsing,
          column inspection, data preview and function source all live in the one Databricks tree
          in the data explorer.
        </p>

        <button className="uc-reveal" onClick={onRevealInExplorer}>
          <Icon name="panel" size={15} />
          Open Databricks in the data explorer
        </button>
      </section>

      <section className="card uc-card">
        <span className="eyebrow">Real catalogs on this workspace</span>
        {error && <p className="error">{error}</p>}
        {!catalogs && !error && <p className="empty">Loading real catalogs…</p>}
        {catalogs && (
          <ul className="uc-catalog-list">
            {catalogs.map((c) => (
              <li key={c.name} className={c.name === "lakebridge_demo" ? "is-target" : ""}>
                <span className="sys-dot sys-databricks" />
                <span className="mono">{c.name}</span>
                {c.name === "lakebridge_demo" && <span className="pill state-ok">migration target</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

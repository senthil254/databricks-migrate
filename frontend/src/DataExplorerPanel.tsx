import { useState } from "react";
import { RedshiftTree } from "./RedshiftTree";
import { StarburstTree } from "./StarburstTree";
import { DatabricksTree } from "./DatabricksTree";
import { useMigrationActions } from "./MigrationActions";
import { Icon } from "./Icon";

// The Data Explorer. G18 moved it out of the shell and under the Migrations
// section, per the user's request that it not be a separate always-on panel.
// It is still mounted exactly ONCE — verification rejected a duplicate mount
// before, and chat deliberately uses chips rather than a second tree.
//
// Sections are stacked and independently collapsible rather than behind a
// switcher: a switcher would hide Redshift while you're looking at Starburst,
// which breaks the compare-and-drag workflow this panel exists for.

export type SystemKey = "redshift" | "starburst" | "databricks";

const SYSTEMS: { key: SystemKey; label: string; sub: string }[] = [
  { key: "redshift", label: "Redshift", sub: "source" },
  { key: "starburst", label: "Starburst", sub: "source" },
  { key: "databricks", label: "Databricks", sub: "target" },
];

// G19 — instant hover tip.
//
// The native `title` attribute cannot be used for this: the browser/OS applies
// a ~1s delay before showing it and there is no way to shorten that from CSS or
// JS. A CSS ::after tip is no good either — the panel scrolls on both axes now,
// so an in-flow pseudo-element gets clipped by the scroll container.
//
// So: one `position: fixed` element for the whole panel, driven by delegated
// mouseover. Fixed positioning escapes the scroll container's clipping, and
// delegation means no per-row listeners on a tree with hundreds of rows.
function useInstantTip() {
  const [tip, setTip] = useState<{ text: string; x: number; y: number } | null>(null);

  const onMouseOver = (e: React.MouseEvent) => {
    const el = (e.target as HTMLElement).closest?.("[data-tip]") as HTMLElement | null;
    if (!el) {
      setTip(null);
      return;
    }
    const text = el.getAttribute("data-tip");
    if (!text) return;
    const r = el.getBoundingClientRect();
    setTip({ text, x: r.left, y: r.bottom + 6 });
  };

  const tipElement = tip ? (
    <div className="hover-tip mono" style={{ left: tip.x, top: tip.y }} role="tooltip">
      {tip.text}
    </div>
  ) : null;

  return { onMouseOver, onMouseLeave: () => setTip(null), tipElement };
}

export function DataExplorerPanel({
  collapsed,
  onToggleCollapsed,
}: {
  collapsed: boolean;
  onToggleCollapsed: () => void;
}) {
  const actions = useMigrationActions();
  // Local again as of G18: the shell no longer needs to drive this, since the
  // Unity Catalog section that used to reveal a system is now hidden from nav.
  const [open, setOpen] = useState<Record<SystemKey, boolean>>({
    redshift: true,
    starburst: false,
    databricks: false,
  });
  const toggle = (key: SystemKey) => setOpen((prev) => ({ ...prev, [key]: !prev[key] }));
  const { onMouseOver, onMouseLeave, tipElement } = useInstantTip();

  if (collapsed) {
    return (
      <aside className="data-panel data-panel-collapsed" aria-label="Data explorer (collapsed)">
        <button className="panel-toggle" onClick={onToggleCollapsed} title="Show data explorer">
          <Icon name="panel" label="Show data explorer" />
        </button>
        <div className="data-panel-rail-dots">
          {SYSTEMS.map((s) => (
            <span key={s.key} className={`sys-dot sys-${s.key}`} title={s.label} />
          ))}
        </div>
      </aside>
    );
  }

  return (
    <aside className="data-panel" aria-label="Data explorer">
      <div className="data-panel-head">
        <span className="eyebrow">Data explorer</span>
        <button className="panel-toggle" onClick={onToggleCollapsed} title="Hide data explorer">
          <Icon name="panel" label="Hide data explorer" />
        </button>
      </div>

      <p className="data-panel-note">
        Live objects from <span className="mono">/explore/*</span>. Drag onto the target zone to migrate.
      </p>

      {tipElement}
      <div className="data-panel-scroll" onMouseOver={onMouseOver} onMouseLeave={onMouseLeave}>
        {SYSTEMS.map((s) => (
          <section key={s.key} className={`sys-section sys-${s.key} ${open[s.key] ? "open" : ""}`}>
            <button
              className="sys-section-head"
              onClick={() => toggle(s.key)}
              aria-expanded={open[s.key]}
            >
              <Icon name="chevron" size={14} className={`sys-caret ${open[s.key] ? "open" : ""}`} />
              <span className="sys-dot" />
              <span className="sys-section-name">{s.label}</span>
              <span className="sys-section-sub">{s.sub}</span>
            </button>

            {/* Kept mounted and display-toggled, not conditionally unmounted —
                unmounting destroys each tree's fetched expansion state, which
                is the whole reason this panel is persistent. */}
            <div className="sys-section-body" style={{ display: open[s.key] ? "block" : "none" }}>
              {s.key === "redshift" && (
                <RedshiftTree
                  onRequestDataCopy={(schema, table) => actions.requestDataCopy("redshift", schema, table)}
                  onRequestSchemaBatch={actions.requestSchemaBatch}
                  onRequestDdlMigration={actions.runDdlMigration}
                  selectMode={actions.selectMode}
                  isSelected={actions.isSelected}
                  onToggleSelect={actions.toggleSelect}
                />
              )}
              {s.key === "starburst" && (
                <StarburstTree
                  onRequestDdlMigration={actions.runDdlMigration}
                  onRequestDdlMigrationCustom={actions.runDdlMigrationCustom}
                  onRequestDataCopy={(catalog, schema, table) =>
                    actions.requestDataCopy("starburst", schema, table, catalog)
                  }
                  onRequestSchemaBatch={(catalog, schema) => actions.requestSchemaBatch(schema, catalog)}
                  selectMode={actions.selectMode}
                  isSelected={actions.isSelected}
                  onToggleSelect={actions.toggleSelect}
                />
              )}
              {s.key === "databricks" && <DatabricksTree />}
            </div>
          </section>
        ))}
      </div>
    </aside>
  );
}

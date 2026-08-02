import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { explorerApi, type Column, type PreviewResult, type RoutineSource } from "./explorerApi";
import { Icon } from "./Icon";

// G19 — the preview moved OUT of the data explorer and into the centre pane.
//
// Why: the explorer now lives in the 372px left rail, and a data grid does not
// belong in a 372px column — it forced a nested horizontal scrollbar inside an
// already-scrolling panel and truncated every value. The eye button now opens
// here instead, where there is room for a real table.
//
// Two independently collapsible sections, per the user's brief:
//   • tables   → "Structure" (real columns + data types) and "Data" (real rows)
//   • routines → "Source SQL" (real SHOW PROCEDURE / pg_proc.prosrc /
//                SHOW CREATE FUNCTION text)
//
// Deliberate honesty note: there is no backend route that returns a source
// table's CREATE statement, so the table view shows its real column list rather
// than a reconstructed `CREATE TABLE` — which would be invented SQL presented
// as if the source system had emitted it.

export type PreviewSystem = "redshift" | "starburst" | "databricks";

export type PreviewTarget =
  | { kind: "table"; system: PreviewSystem; catalog?: string; schema: string; name: string }
  | {
      kind: "routine";
      system: PreviewSystem;
      catalog?: string;
      /** Undefined for Starburst UDFs — they are global to galaxy.functions. */
      schema?: string;
      name: string;
      routineType?: string;
    };

interface PreviewContextValue {
  target: PreviewTarget | null;
  openPreview: (t: PreviewTarget) => void;
  closePreview: () => void;
}

const PreviewContext = createContext<PreviewContextValue | null>(null);

export function PreviewProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<PreviewTarget | null>(null);
  const openPreview = useCallback((t: PreviewTarget) => setTarget(t), []);
  const closePreview = useCallback(() => setTarget(null), []);
  return (
    <PreviewContext.Provider value={{ target, openPreview, closePreview }}>{children}</PreviewContext.Provider>
  );
}

export function usePreview() {
  const ctx = useContext(PreviewContext);
  if (!ctx) throw new Error("usePreview must be used inside <PreviewProvider>");
  return ctx;
}

function qualified(t: PreviewTarget) {
  return [t.catalog, t.kind === "routine" ? t.schema : t.schema, t.name].filter(Boolean).join(".");
}

function targetKey(t: PreviewTarget) {
  return `${t.kind}:${t.system}:${qualified(t)}`;
}

/** One collapsible block. Kept as a real <button> + region so it is operable
 *  by keyboard and announced correctly, rather than a styled <div>. */
function Section({
  title,
  meta,
  open,
  onToggle,
  children,
}: {
  title: string;
  meta?: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <section className={`pv-section ${open ? "open" : ""}`}>
      <button className="pv-section-head" onClick={onToggle} aria-expanded={open}>
        <Icon name="chevron" size={13} className={`pv-caret ${open ? "open" : ""}`} />
        <span className="pv-section-title">{title}</span>
        {meta && <span className="pv-section-meta">{meta}</span>}
      </button>
      {/* display-toggled, not unmounted — collapsing must not refetch. */}
      <div className="pv-section-body" style={{ display: open ? "block" : "none" }}>
        {children}
      </div>
    </section>
  );
}

export function PreviewPane() {
  const { target, closePreview } = usePreview();

  const [columns, setColumns] = useState<Column[] | null>(null);
  const [rows, setRows] = useState<PreviewResult | null>(null);
  const [source, setSource] = useState<RoutineSource | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [openStruct, setOpenStruct] = useState(true);
  const [openData, setOpenData] = useState(true);

  const key = target ? targetKey(target) : null;

  useEffect(() => {
    if (!target) return;
    let cancelled = false;

    setColumns(null);
    setRows(null);
    setSource(null);
    setError(null);
    setLoading(true);

    async function load(t: PreviewTarget) {
      if (t.kind === "routine") {
        const src =
          t.system === "starburst"
            ? await explorerApi.starburstUdfSource(t.name)
            : t.system === "databricks"
              ? await explorerApi.databricksFunctionSource(t.catalog!, t.schema!, t.name)
              : await explorerApi.redshiftRoutineSource(t.schema!, t.name);
        if (!cancelled) setSource(src);
        return;
      }

      // Structure and data are fetched together but settled independently: a
      // column-list failure must not blank the rows, and vice versa.
      const cols =
        t.system === "starburst"
          ? explorerApi.starburstColumns(t.catalog!, t.schema, t.name)
          : t.system === "databricks"
            ? explorerApi.databricksColumns(t.catalog!, t.schema, t.name)
            : explorerApi.redshiftColumns(t.schema, t.name);
      const data =
        t.system === "starburst"
          ? explorerApi.starburstPreview(t.catalog!, t.schema, t.name)
          : t.system === "databricks"
            ? explorerApi.databricksPreview(t.catalog!, t.schema, t.name)
            : explorerApi.redshiftPreview(t.schema, t.name);

      const [c, d] = await Promise.allSettled([cols, data]);
      if (cancelled) return;
      if (c.status === "fulfilled") setColumns(c.value);
      if (d.status === "fulfilled") setRows(d.value);
      if (c.status === "rejected" && d.status === "rejected") {
        throw d.reason instanceof Error ? d.reason : new Error(String(d.reason));
      }
    }

    load(target)
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // `key` is the identity of what we're showing; `target` is a fresh object
    // on every open of the same thing and would refetch needlessly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  // Esc closes, matching the ConfirmDialog convention already in the app.
  useEffect(() => {
    if (!target) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closePreview();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [target, closePreview]);

  if (!target) return null;

  const isRoutine = target.kind === "routine";
  const typeLabel = isRoutine ? (target.routineType ?? "ROUTINE").toLowerCase() : "table";

  return (
    <section className="preview-pane card fade-up" aria-label={`Preview of ${qualified(target)}`}>
      <header className="pv-head">
        <span className={`sys-dot sys-${target.system}`} aria-hidden="true" />
        <div className="pv-head-titles">
          <span className="eyebrow">Preview · {target.system}</span>
          <h3 className="pv-title mono">{qualified(target)}</h3>
        </div>
        <span className="pill pv-type">{typeLabel}</span>
        <button className="pv-close" onClick={closePreview} title="Close preview (Esc)" aria-label="Close preview">
          <Icon name="x" size={16} />
        </button>
      </header>

      {loading && <p className="muted">Loading real data from the source system…</p>}
      {error && (
        <div className="callout-warn">
          <strong>Preview failed:</strong> {error}
        </div>
      )}

      {isRoutine && source && (
        <Section
          title="Source SQL"
          meta={`${source.source.split("\n").length} lines`}
          open={openStruct}
          onToggle={() => setOpenStruct((o) => !o)}
        >
          <div className="pv-scroll pv-scroll-code">
            <pre className="mono code-block">{source.source}</pre>
          </div>
        </Section>
      )}

      {!isRoutine && (
        <>
          <Section
            title="Structure"
            meta={columns ? `${columns.length} columns` : undefined}
            open={openStruct}
            onToggle={() => setOpenStruct((o) => !o)}
          >
            {columns === null && !error && <p className="muted">Loading columns…</p>}
            {columns && (
              <div className="pv-scroll">
                <table className="preview-table pv-table">
                  <thead>
                    <tr>
                      <th>Column</th>
                      <th>Type</th>
                    </tr>
                  </thead>
                  <tbody>
                    {columns.map((c) => (
                      <tr key={c.name}>
                        <td className="mono">{c.name}</td>
                        <td>
                          <span className="column-type-badge">{c.data_type}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>

          <Section
            title="Data"
            meta={rows ? `${rows.row_count} rows` : undefined}
            open={openData}
            onToggle={() => setOpenData((o) => !o)}
          >
            {rows === null && !error && <p className="muted">Loading rows…</p>}
            {rows && rows.row_count === 0 && <p className="empty">This table is empty.</p>}
            {rows && rows.row_count > 0 && (
              // pv-scroll-rows caps the visible height at about five rows; the
              // rest scroll. All fetched rows are still here — nothing is
              // dropped, so the "N rows" count above stays truthful.
              <div className="pv-scroll pv-scroll-rows">
                <table className="preview-table pv-table">
                  <thead>
                    <tr>
                      {rows.columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.rows.map((row, i) => (
                      <tr key={i}>
                        {row.map((cell, j) => (
                          <td key={j}>{cell === null ? <em className="pv-null">null</em> : String(cell)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
        </>
      )}
    </section>
  );
}

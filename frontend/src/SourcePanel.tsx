import { useEffect, useState } from "react";
import { explorerApi, type RoutineSource } from "./explorerApi";

// G15 Phase A — read-only source/DDL view for Redshift routines
// (procedure/function), fetched via the new, dedicated
// GET /explore/redshift/schemas/{schema}/routines/{name}/source route.
// Deliberately separate from PreviewPanel: this renders code text, not
// tabular row data, and never triggers a real migration record.
// G17 — `load` is optional so the existing Redshift call sites keep working
// unchanged; the Databricks tree passes its own fetcher (the UC function
// source route) instead of duplicating this panel. `source_available` is
// only sent by the Databricks route — when it is explicitly false the panel
// says so rather than presenting the placeholder text as if it were a body.
export function SourcePanel({
  schema,
  name,
  onClose,
  qualifier,
  load,
}: {
  schema: string;
  name: string;
  onClose: () => void;
  qualifier?: string;
  load?: () => Promise<RoutineSource>;
}) {
  const [source, setSource] = useState<string | null>(null);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSource(null);
    setAvailable(null);
    setError(null);
    (load ? load() : explorerApi.redshiftRoutineSource(schema, name))
      .then((r) => {
        setSource(r.source);
        setAvailable(r.source_available ?? null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    // `load` is recreated per render at the call sites, so it is deliberately
    // not a dependency — schema/name/qualifier fully identify what to fetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schema, name, qualifier]);

  return (
    <div className="source-view-panel">
      <div className="preview-panel-header">
        <strong>
          Source: {qualifier ? `${qualifier}.` : ""}
          {schema}.{name}
        </strong>
        <button className="mini-btn" onClick={onClose}>
          close
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {!error && source === null && <p className="empty">Loading real source…</p>}
      {available === false && (
        <p className="empty">
          source body not available — Unity Catalog holds no routine_definition for this function; only the
          signature below is real
        </p>
      )}
      {source !== null && <pre className="mono code-block source-code-block">{source}</pre>}
    </div>
  );
}

// Starburst UDFs: Trino's SHOW FUNCTIONS only exposes the signature, not
// the body — this is a genuine upstream limitation, not a bug, so the eye
// button explains it rather than firing a network call that would just
// error.
export function UnavailableSourcePanel({ name, onClose }: { name: string; onClose: () => void }) {
  return (
    <div className="source-view-panel">
      <div className="preview-panel-header">
        <strong>Source: {name}</strong>
        <button className="mini-btn" onClick={onClose}>
          close
        </button>
      </div>
      <p className="empty">source not available — Trino only exposes function signatures</p>
    </div>
  );
}

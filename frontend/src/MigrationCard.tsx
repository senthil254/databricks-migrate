import { useState } from "react";
import { explorerApi, type Migration, type PreviewResult } from "./explorerApi";
import { PipelineFlow } from "./PipelineFlow";
import { useSpotlight } from "./useSpotlight";
import { Icon } from "./Icon";
import { Collapsible, ScrollBox } from "./Collapsible";

export interface Job {
  key: string;
  system: "redshift" | "starburst";
  objectType: string;
  name: string;
  // G15 Phase A — "create-and-copy" is the new combined drag-drop path for
  // table/view (real object creation + real data copy in one backend call).
  action: "ddl" | "ddl-custom" | "data" | "create-and-copy";
  triggeredAt: string;
  migration: Migration | null;
  clientError: string | null; // set when the POST itself rejected (e.g. 400 UDF-not-supported)
  settled: boolean;
}

// Real engine strings the backend actually returns (Migration.engine) — the
// authoritative source once a migration record exists. job.action is only a
// pre-response guess for the brief "dispatching" window before that.
const ENGINE_LABELS: Record<string, string> = {
  "lakebridge-transpile": "lakebridge-transpile (deterministic)",
  "llm-transpile-experimental": "llm-transpile (experimental)",
  "starburst-custom-ddl": "custom-ddl (deterministic)",
  "data-copy": "data-copy",
  "create-and-copy": "create object + copy data",
};

function engineLabel(job: Job) {
  if (job.migration?.engine) return ENGINE_LABELS[job.migration.engine] ?? job.migration.engine;
  if (job.action === "create-and-copy") return "create object + copy data";
  if (job.action === "data") return "data-copy";
  if (job.action === "ddl-custom") return "custom-ddl (deterministic)";
  return job.system === "redshift" ? "lakebridge-transpile (deterministic)" : "llm-transpile (experimental)";
}

function engineClass(job: Job): "data" | "lakebridge" | "experimental" {
  if (job.migration?.engine) {
    if (job.migration.engine === "data-copy" || job.migration.engine === "create-and-copy") return "data";
    if (job.migration.engine === "llm-transpile-experimental") return "experimental";
    return "lakebridge"; // lakebridge-transpile and starburst-custom-ddl are both deterministic — green
  }
  if (job.action === "data" || job.action === "create-and-copy") return "data";
  if (job.action === "ddl-custom") return "lakebridge";
  return job.system === "redshift" ? "lakebridge" : "experimental";
}

export function ViewDataAction({ migration }: { migration: Migration }) {
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    // G19 bugfix: this used to `return` when a preview was already cached, so
    // the FIRST result was kept forever. Since `migrate` began creating the
    // object, a create-and-copy briefly has a real-but-empty target table
    // between its DDL leg and its data leg — open the panel in that window and
    // the card showed "rows copied: 201" above "0 rows", permanently. A preview
    // is one cheap query against a warm connection, so just re-read it.
    setLoading(true);
    setError(null);
    try {
      // Same real preview endpoint DatabricksTree uses — GET
      // /explore/databricks/catalogs/{catalog}/schemas/{schema}/tables/{table}/preview
      const result = await explorerApi.databricksPreview(
        migration.target_catalog!,
        migration.target_schema!,
        migration.target_table!,
      );
      setPreview(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="migration-card-view-data">
      <button type="button" className="mini-btn" onClick={toggle}>
        {open ? "hide data" : "view data"}
      </button>
      {open && (
        <div className="preview-panel">
          <p className="muted mono">
            {migration.target_catalog}.{migration.target_schema}.{migration.target_table}
          </p>
          {loading && <p className="muted">loading real preview…</p>}
          {error && (
            <div className="callout-warn">
              <strong>Preview failed:</strong> {error}
            </div>
          )}
          {preview && (
            // G19: was a bare table with no disclosure. Now the same
            // Collapsible + ScrollBox every other data/SQL surface uses, so a
            // long result can be folded away and never scrolls the page.
            <Collapsible title="Data" meta={`${preview.row_count} rows`}>
              <ScrollBox variant="rows">
                <table className="preview-table pv-table">
                  <thead>
                    <tr>
                      {preview.columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.rows.map((row, i) => (
                      <tr key={i}>
                        {row.map((cell, j) => (
                          <td key={j}>{cell === null ? <em className="pv-null">null</em> : String(cell)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </ScrollBox>
            </Collapsible>
          )}
        </div>
      )}
    </div>
  );
}

// G19: the Migrations surface renders an "Active pipeline" hero for the newest
// job AND a card per job — so that newest job's pipeline appeared twice on one
// screen. The card takes `showPipeline={false}` in exactly that case. Default
// stays true so every other mount site (chat transcript, older cards) is
// unaffected.
export function MigrationCard({ job, showPipeline = true }: { job: Job; showPipeline?: boolean }) {
  const { spotlightProps } = useSpotlight();
  // G19 — drag-and-drop several objects and the session list grew without
  // bound, pushing everything below off-screen. Each card folds to its header.
  const [folded, setFolded] = useState(false);
  const status = job.clientError ? "failed" : job.migration?.status ?? "dispatching";
  // Data-copy migrations (and only those) get real target_catalog/schema/table
  // values populated by migrate.py; DDL-only migrations correctly leave these
  // null, so the "view data" action only appears when there's real data to view.
  const canViewData =
    status === "completed" &&
    !!job.migration?.target_catalog &&
    !!job.migration?.target_schema &&
    !!job.migration?.target_table;

  return (
    <div className={`migration-card card card-spotlight status-${status}`} {...spotlightProps}>
      <div className="migration-card-head">
        <span className={`engine-dot ${engineClass(job)}`} />
        <strong>{job.name}</strong>
        <span className="muted">{job.objectType}</span>
        <span className={`status-pill status-${status}`}>{status}</span>
        <button
          className="card-fold"
          aria-expanded={!folded}
          aria-label={folded ? `Expand ${job.name}` : `Collapse ${job.name}`}
          title={folded ? "Expand" : "Collapse"}
          onClick={() => setFolded((f) => !f)}
        >
          <Icon name="chevron" size={13} className={`pv-caret ${folded ? "" : "open"}`} />
        </button>
      </div>
      <div className="migration-card-engine">{engineLabel(job)}</div>

      <div style={{ display: folded ? "none" : "block" }}>

      {showPipeline && <PipelineFlow job={job} />}

      {status === "dispatching" && (
        <p className="muted">
          Real request dispatched to the backend
          {job.system === "starburst" && job.action === "ddl"
            ? " — llm-transpile jobs can take 5+ minutes; this card will update from real GET /migrations polling, not a fake timer."
            : "…"}
        </p>
      )}
      {status === "running" && (
        <p className="muted">Real migration in progress (backend-reported, polled from GET /migrations/{job.migration?.id}).</p>
      )}

      {/* G19 — the backend short-circuits when the object is already in the
          target. Surface that as its own notice rather than leaving the user to
          read it out of the SQL block. */}
      {/* Two distinct outcomes, deliberately worded differently: a DDL migrate
          takes no action at all, whereas a data copy is a full refresh and DOES
          replace the rows. Telling the user "nothing changed" after a refresh
          would be false. */}
      {job.migration?.output_ddl?.startsWith("-- ALREADY MIGRATED (rows refreshed)") ? (
        <div className="callout-info">
          <strong>Already migrated — rows refreshed.</strong> The target already existed, so it was
          replaced and every row re-copied.
        </div>
      ) : job.migration?.output_ddl?.startsWith("-- ALREADY MIGRATED") ? (
        <div className="callout-info">
          <strong>Already migrated.</strong> This object already exists in Databricks, so nothing was
          re-created. Nothing changed in the target.
        </div>
      ) : null}

      {job.clientError && (
        <div className="callout-warn">
          <strong>Rejected by backend:</strong> {job.clientError}
        </div>
      )}

      {job.migration?.error && (
        <div className="callout-warn">
          <strong>Migration failed:</strong>
          <pre className="mono">{job.migration.error}</pre>
        </div>
      )}

      {/* G19: these were <details> with an unbounded <pre> inside — a long DDL
          stretched the card and scrolled the page horizontally. Same
          Collapsible + scroll box as everywhere else now. */}
      {job.migration?.source_ddl && (
        <Collapsible
          title="Source DDL"
          meta={`${job.migration.source_ddl.split("\n").length} lines`}
          defaultOpen={false}
        >
          <ScrollBox variant="code">
            <pre className="mono code-block">{job.migration.source_ddl}</pre>
          </ScrollBox>
        </Collapsible>
      )}

      {job.migration?.output_ddl && (
        <Collapsible title="Output" meta={`${job.migration.output_ddl.split("\n").length} lines`}>
          <ScrollBox variant="code">
            <pre className="mono code-block">{job.migration.output_ddl}</pre>
          </ScrollBox>
        </Collapsible>
      )}

      {job.migration?.row_count !== null && job.migration?.row_count !== undefined && (
        <p className="muted">rows copied: {job.migration.row_count}</p>
      )}

      {canViewData && job.migration && <ViewDataAction migration={job.migration} />}
      </div>
    </div>
  );
}

import type { BatchSummary } from "./batchApi";
import { useSpotlight } from "./useSpotlight";

// G3.4 — renders a real Batch's progress/results. Terminal states are
// "completed" (all items succeeded) and "completed_with_errors" (at least
// one item failed) — these are visually distinct on purpose per this
// project's "never hide a real failure" rule (see MEMORY.md's G3.4 backend
// entry: a batch that partially fails must never render as a plain success).
export function BatchCard({ label, batch }: { label: string; batch: BatchSummary }) {
  const { spotlightProps } = useSpotlight();
  const isTerminal = batch.status === "completed" || batch.status === "completed_with_errors";
  const settledCount = batch.completed_items + batch.failed_items;
  const pct = batch.total_items > 0 ? Math.round((settledCount / batch.total_items) * 100) : 0;

  return (
    <div className={`batch-card card card-spotlight batch-status-${batch.status}`} {...spotlightProps}>
      <div className="migration-card-head">
        <span
          className={`engine-dot ${batch.status === "completed" ? "lakebridge" : batch.status === "completed_with_errors" ? "batch-error" : "experimental"}`}
        />
        <strong>{label}</strong>
        <span className="muted mono">{batch.id}</span>
        <span className={`status-pill batch-pill-${batch.status}`}>{batch.status.replace(/_/g, " ")}</span>
      </div>

      <div className="batch-progress-row">
        <div className="batch-progress-bar">
          <div
            className={`batch-progress-fill ${batch.failed_items > 0 ? "has-errors" : ""}`}
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="muted mono">
          {settledCount}/{batch.total_items} settled
          {batch.dispatched_items < batch.total_items && ` (${batch.dispatched_items} dispatched)`}
          {" — "}
          {batch.completed_items} ok, {batch.failed_items} failed
        </span>
      </div>

      {!isTerminal && (
        <p className="muted">
          Real batch in progress — a whole-schema batch against real Redshift objects can take ~2 minutes;
          polled from real <span className="mono">GET /batches/{batch.id}</span>, not a fake timer.
        </p>
      )}

      {batch.status === "completed_with_errors" && (
        <div className="callout-warn">
          <strong>{batch.failed_items} of {batch.total_items} items failed.</strong> This batch did not fully
          succeed — see the per-item detail below for the real error(s). Other items still completed and are
          not being hidden by the failure.
        </div>
      )}

      {batch.migrations && batch.migrations.length > 0 && (
        <details open={isTerminal}>
          <summary>Per-item detail ({batch.migrations.length})</summary>
          <div className="batch-item-list">
            {batch.migrations.map((m) => (
              <div key={m.id} className={`batch-item status-${m.status}`}>
                <span className={`engine-dot ${m.source_system === "redshift" ? "lakebridge" : "experimental"}`} />
                <span className="mono">{m.object_name}</span>
                <span className="muted">{m.object_type}</span>
                <span className="muted">{m.engine}</span>
                <span className={`status-pill status-${m.status}`}>{m.status}</span>
                {m.row_count !== null && m.row_count !== undefined && (
                  <span className="muted">rows: {m.row_count}</span>
                )}
                {m.error && <span className="batch-item-error">{m.error}</span>}
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

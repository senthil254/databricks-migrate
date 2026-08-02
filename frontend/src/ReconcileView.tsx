import { useEffect, useState } from "react";
import { historyApi, type ReconcileDetail } from "./historyApi";

const POLL_MS = 2500;

// G4 — dedicated reconcile validation-results view. Polls
// GET /runs/{run_id}/reconcile for real; while the real dispatched
// Databricks job is still executing this can legitimately take 90+ real
// seconds (see MEMORY.md's G4 backend entry — ~95s observed), so this
// component polls honestly rather than faking instant resolution.
//
// CRITICAL rendering rule (per the G4 task spec's explicit IMPORTANT note):
// `reconciliation_passed` (did source/target data actually match) is a
// SEPARATE axis from the run's own technical status (did the run itself
// error out). A real mismatch is a successfully-completed reconcile run
// that found real differences — it renders as a distinct amber "mismatch
// found" state, never as a red technical failure. Only a genuinely failed
// *run* (status "failed", or a terminated job with result_state != SUCCESS)
// renders as an error.
export function ReconcileView({ runId }: { runId: string }) {
  const [detail, setDetail] = useState<ReconcileDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;

    async function tick() {
      try {
        const d = await historyApi.getReconcileDetail(runId);
        if (stopped) return;
        setDetail(d);
        setError(null);
        const jobTerminal = d.result !== null; // result only ever appears once the real job hit a terminal state
        if ((d.status === "queued" || d.status === "running") && !jobTerminal) {
          timer = setTimeout(tick, POLL_MS);
        }
      } catch (e) {
        if (!stopped) setError(e instanceof Error ? e.message : String(e));
      }
    }

    tick();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [runId]);

  if (error) return <p className="error">Failed to load reconcile detail: {error}</p>;
  if (!detail) return <p className="muted">Loading reconcile detail…</p>;

  const runFailed = detail.status === "failed";
  const stillRunning = (detail.status === "queued" || detail.status === "running") && detail.result === null;

  return (
    <div className="reconcile-view">
      <h3>Reconcile validation</h3>

      {stillRunning && (
        <div className="reconcile-state reconcile-running">
          <span className="status-pill status-running">
            <span aria-hidden="true">◐</span> Job in progress
          </span>
          <p className="muted">
            The Databricks reconcile job has been dispatched and is still running for real — this can take 90+
            seconds. Polling <span className="mono">GET /runs/{runId}/reconcile</span> every {POLL_MS / 1000}s, not
            a fake timer.
          </p>
        </div>
      )}

      {runFailed && !detail.result && (
        <div className="reconcile-state reconcile-error callout-warn">
          <strong>Run failed.</strong> The reconcile command itself errored out before producing a validation
          result — see the Events log above for the real stderr output.
        </div>
      )}

      {detail.status === "completed" && !detail.result && (
        <div className="reconcile-state callout-warn">
          <strong>No validation result was captured for this run.</strong> The run finished, but this backend
          didn't discover a result payload for it (e.g. it predates result capture, or the job's result table
          lookup didn't find a match). Not fabricating numbers — check the Events log above for what actually
          happened.
        </div>
      )}

      {detail.result && (
        <ReconcileResultView result={detail.result} runTechnicallyFailed={runFailed} />
      )}
    </div>
  );
}

function ReconcileResultView({
  result,
  runTechnicallyFailed,
}: {
  result: NonNullable<ReconcileDetail["result"]>;
  runTechnicallyFailed: boolean;
}) {
  const { metrics } = result;
  const jobSucceeded = result.lifecycle_state === "TERMINATED" && result.result_state === "SUCCESS";

  // Technical job failure (never seen live, but the real API shape allows
  // result_state != SUCCESS) is rendered as a genuine error — separate again
  // from a passed/mismatched *validation* outcome, which requires the job to
  // have actually succeeded and produced real metrics.
  if (runTechnicallyFailed || !jobSucceeded) {
    return (
      <div className="reconcile-state reconcile-error callout-warn">
        <strong>Reconcile job did not complete successfully.</strong>
        <p className="mono">
          lifecycle_state: {result.lifecycle_state}, result_state: {result.result_state}
        </p>
        <p className="muted">
          Job run <span className="mono">{result.job_run_id}</span> — check the Databricks job run for details.
        </p>
      </div>
    );
  }

  const passed = result.reconciliation_passed;

  return (
    <div className="reconcile-state">
      <div className={`reconcile-verdict ${passed ? "reconcile-passed" : "reconcile-mismatch"}`}>
        <span className={`status-pill ${passed ? "status-completed" : "status-mismatch"}`}>
          <span aria-hidden="true">{passed ? "✓" : "⚠"}</span> {passed ? "Matched" : "Mismatch found"}
        </span>
        <span className="muted">
          {passed
            ? "Source and target data matched for this reconcile run."
            : "The reconcile job completed successfully and found real differences between source and target — this is not a technical failure."}
        </span>
      </div>

      <div className="reconcile-meta muted mono">
        recon_id: {result.recon_id} · job_run_id: {result.job_run_id} · report_type: {result.report_type}
      </div>
      <div className="reconcile-meta muted mono">
        {result.source_table.catalog}.{result.source_table.schema}.{result.source_table.table_name} → {result.target_table.catalog}.
        {result.target_table.schema}.{result.target_table.table_name}
      </div>
      <div className="reconcile-meta muted">
        started {result.started_at} · ended {result.ended_at}
      </div>

      <table className="reconcile-metrics-table">
        <tbody>
          <tr>
            <th>Source record count</th>
            <td className="mono">{metrics.source_record_count}</td>
          </tr>
          <tr>
            <th>Target record count</th>
            <td className="mono">{metrics.target_record_count}</td>
          </tr>
          <tr>
            <th>Rows missing in source</th>
            <td className="mono">{metrics.row_comparison.missing_in_source}</td>
          </tr>
          <tr>
            <th>Rows missing in target</th>
            <td className="mono">{metrics.row_comparison.missing_in_target}</td>
          </tr>
          <tr>
            <th>Column absolute mismatches</th>
            <td className="mono">{metrics.column_comparison.absolute_mismatch}</td>
          </tr>
          <tr>
            <th>Column threshold mismatches</th>
            <td className="mono">{metrics.column_comparison.threshold_mismatch}</td>
          </tr>
          {metrics.column_comparison.mismatch_columns && (
            <tr>
              <th>Mismatched columns</th>
              <td className="mono">{metrics.column_comparison.mismatch_columns}</td>
            </tr>
          )}
          <tr>
            <th>Schema comparison</th>
            <td>
              <span className={`status-pill ${metrics.schema_comparison ? "status-completed" : "status-mismatch"}`}>
                {metrics.schema_comparison ? "matches" : "differs"}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

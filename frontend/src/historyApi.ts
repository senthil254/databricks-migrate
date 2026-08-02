// G4 — thin client for the new unified history + reconcile-detail endpoints
// (backend/app/main.py, "---------------------------------------------- G4"
// section). Same rule as every other *Api.ts file: hits the real FastAPI
// backend at 8811 only, never mocked.

import { API_BASE as BASE } from "./apiBase";
async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${path} -> HTTP ${res.status} ${body}`);
  }
  return res.json();
}

// ------------------------------------------------------------ /history

interface HistoryBase {
  sort_key: string | null;
}

export interface HistoryRunItem extends HistoryBase {
  kind: "run";
  id: string;
  command: string;
  status: string;
  started_at: string | null;
  ended_at: string | null;
  exit_code: number | null;
  result: ReconcileResult | null;
}

export interface HistoryMigrationItem extends HistoryBase {
  kind: "migration";
  id: string;
  source_system: string;
  object_type: string;
  object_name: string;
  engine: string;
  status: string;
  source_ddl: string | null;
  output_ddl: string | null;
  error: string | null;
  row_count: number | null;
  started_at: string | null;
  ended_at: string | null;
  target_catalog: string | null;
  target_schema: string | null;
  target_table: string | null;
}

export interface HistoryBatchItem extends HistoryBase {
  kind: "batch";
  id: string;
  status: string;
  total_items: number;
  completed_items: number;
  failed_items: number;
  dispatched_items: number;
  created_at: string | null;
  started_at: string | null;
  ended_at: string | null;
}

export type HistoryItem = HistoryRunItem | HistoryMigrationItem | HistoryBatchItem;
export type HistoryKind = HistoryItem["kind"];

// ------------------------------------------------------- reconcile detail

export interface ReconcileTableRef {
  catalog: string;
  schema: string;
  table_name: string;
}

export interface ReconcileMetrics {
  source_record_count: number;
  target_record_count: number;
  row_comparison: { missing_in_source: number; missing_in_target: number };
  column_comparison: { absolute_mismatch: number; threshold_mismatch: number; mismatch_columns: string };
  schema_comparison: boolean;
}

export interface ReconcileResult {
  job_run_id: string;
  lifecycle_state: string;
  result_state: string;
  recon_id: string;
  source_table: ReconcileTableRef;
  target_table: ReconcileTableRef;
  report_type: string;
  started_at: string;
  ended_at: string;
  metrics: ReconcileMetrics;
  reconciliation_passed: boolean;
}

// run.status here — "queued" | "running" | "completed" | "failed" (mirrors
// the real Run's own status, see main.py's get_reconcile_detail docstring:
// the Run stays "running" for real until the dispatched Databricks job
// reaches a real terminal state).
export interface ReconcileDetail {
  run_id: string;
  status: string;
  started_at: string | null;
  ended_at: string | null;
  result: ReconcileResult | null;
}

export const historyApi = {
  list: () => get<HistoryItem[]>("/history"),
  getReconcileDetail: (runId: string) => get<ReconcileDetail>(`/runs/${encodeURIComponent(runId)}/reconcile`),
};

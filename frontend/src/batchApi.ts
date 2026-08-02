// G3.4 — thin client for the real batch endpoints (backend built and
// curl-verified in a prior session — see MEMORY.md's "G3.4 backend" entry).
// Same rules as explorerApi.ts: real FastAPI backend only, never mocked.

import type { Migration } from "./explorerApi";

import { API_BASE as BASE } from "./apiBase";
export type BatchStatus = "pending" | "running" | "completed" | "completed_with_errors";

export interface BatchSummary {
  id: string;
  status: BatchStatus;
  total_items: number;
  completed_items: number;
  failed_items: number;
  dispatched_items: number;
  created_at: string | null;
  started_at: string | null;
  ended_at: string | null;
  migrations?: Migration[];
}

export interface BatchItem {
  source_system: "redshift" | "starburst";
  object_type: string;
  schema_name: string;
  name: string;
  catalog?: string;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${path} -> HTTP ${res.status} ${body}`);
  }
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const respBody = await res.text().catch(() => "");
    const err = new Error(`${path} -> HTTP ${res.status} ${respBody}`) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export const batchApi = {
  // Returns immediately with a pending/running batch summary — the real
  // per-object work runs on a background thread server-side. Callers must
  // poll getBatch() to observe progress/terminal state, same
  // dispatch-vs-completion distinction as single-object /migrate/* calls.
  migrateRedshiftSchemaBatch: (schema: string, includeData: boolean) =>
    post<BatchSummary>(`/migrate/redshift/schema/${encodeURIComponent(schema)}/batch?include_data=${includeData}`),
  migrateStarburstSchemaBatch: (catalog: string, schema: string, includeData: boolean) =>
    post<BatchSummary>(
      `/migrate/starburst/catalog/${encodeURIComponent(catalog)}/schema/${encodeURIComponent(schema)}/batch?include_data=${includeData}`,
    ),
  migrateBatch: (items: BatchItem[]) => post<BatchSummary>("/migrate/batch", { items }),
  listBatches: () => get<BatchSummary[]>("/batches"),
  getBatch: (id: string) => get<BatchSummary>(`/batches/${id}`),
};

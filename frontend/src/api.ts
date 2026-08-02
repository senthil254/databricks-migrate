// Thin client for the real backend built in G1/G2 (backend/app/main.py).
// No mocking — every call here hits the real FastAPI adapter, which is the
// only thing allowed to invoke the Lakebridge CLI (see README.md).

import { API_BASE as BASE } from "./apiBase";
export type RunStatus = "queued" | "running" | "completed" | "failed";

export type Command = "describe-transpile" | "transpile" | "analyze" | "reconcile";

export interface Run {
  id: string;
  command: Command;
  status: RunStatus;
  started_at: string | null;
  ended_at: string | null;
  exit_code: number | null;
}

export interface RunEvent {
  id: number;
  timestamp: string;
  type: "stdout" | "stderr" | "status";
  message: string;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`);
  return res.json();
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`);
  return res.json();
}

export const api = {
  listRuns: () => get<Run[]>("/runs"),
  getRun: (id: string) => get<Run>(`/runs/${id}`),
  getEvents: (id: string) => get<RunEvent[]>(`/runs/${id}/events`),

  startDescribeTranspile: () => post<{ run_id: string }>("/runs/describe-transpile"),
  startTranspile: (source_dialect = "snowflake") =>
    post<{ run_id: string }>("/runs/transpile", { source_dialect }),
  startAnalyze: (source_tech = "Snowflake") =>
    post<{ run_id: string }>("/runs/analyze", { source_tech }),
  startReconcile: () => post<{ run_id: string }>("/runs/reconcile"),
};

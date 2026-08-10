// G6 — thin client for the real chat endpoints (backend/app/chat.py +
// main.py's POST /chat/plan, POST /chat/execute). Same rule as every other
// *Api.ts file: hits the real FastAPI backend at 8811 only, never mocked,
// and never calls the Lakebridge CLI directly (see CLAUDE.md).

import { API_BASE as BASE } from "./apiBase";
async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const respBody = await res.text().catch(() => "");
    throw new Error(`${path} -> HTTP ${res.status} ${respBody}`);
  }
  return res.json();
}

// -------------------------------------------------------------- /chat/plan

export type ChatAction =
  | { kind: "migrate_ddl"; source_system: string; object_type: string; schema: string; name: string }
  | { kind: "copy_table_data"; source_system: string; schema: string; name: string }
  | {
      kind: "migrate_schema_batch";
      source_system: string;
      schema: string;
      include_data: boolean;
      item_count: number;
    }
  | { kind: "reconcile" }
  // G16 Phase B — combined create-object + copy-data intent, triggered by
  // typed requests like "migrate schema.table and its data" as well as
  // ObjectChips clicks. Same plan->confirm->execute shape as migrate_ddl;
  // built against the backend contract documented in the G16 Phase B plan
  // (backend built in parallel — this shape is the agreed contract, not
  // yet necessarily live when this file was written).
  | {
      kind: "migrate_table_and_data";
      source_system: string;
      object_type: string;
      schema: string;
      name: string;
    };

export interface ChatPlanUnderstood {
  understood: true;
  plan_id: string;
  action: ChatAction;
  endpoint: string;
  explanation: string;
}

export interface ChatPlanRefused {
  understood: false;
  reason: string;
}

export type ChatPlanResponse = ChatPlanUnderstood | ChatPlanRefused;

// ----------------------------------------------------------- /chat/execute

export type ChatExecuteResult =
  | { kind: string; result_type: "migration"; migration_id: string }
  | { kind: string; result_type: "batch"; batch_id: string }
  | { kind: string; result_type: "run"; run_id: string }
  | { kind: string; result_type: "query"; columns: string[] | null; rows: unknown[][]; row_count: number }
  | { kind: string; result_type: "mcp_tool_call"; tool_name: string; result: unknown };

export const chatApi = {
  plan: (instruction: string) => post<ChatPlanResponse>("/chat/plan", { instruction }),
  execute: (planId: string) => post<ChatExecuteResult>("/chat/execute", { plan_id: planId }),
};

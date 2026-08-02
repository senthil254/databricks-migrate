// G3.3 — thin client for the real G3.1/G3.2 endpoints (explore + migrate).
// Same rule as api.ts: every call hits the real FastAPI backend at 8811,
// never mocked, never talks to Redshift/Starburst/Databricks directly.

import { API_BASE as BASE } from "./apiBase";
export type MigrationEngine =
  | "lakebridge-transpile"
  | "llm-transpile-experimental"
  | "data-copy"
  | "starburst-custom-ddl"
  | "create-and-copy";
export type MigrationStatus = "queued" | "running" | "completed" | "failed";

export interface Migration {
  id: string;
  source_system: "redshift" | "starburst";
  object_type: string;
  object_name: string;
  engine: MigrationEngine;
  status: MigrationStatus;
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

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${path} -> HTTP ${res.status} ${body}`);
  }
  return res.json();
}

async function post<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: "POST" });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    const err = new Error(`${path} -> HTTP ${res.status} ${body}`) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export interface Named { name: string }
export interface RedshiftTable { schema: string; name: string; type: string }
export interface RedshiftRoutine { schema: string; name: string; type: string }
export interface StarburstTable { catalog: string; schema: string; name: string; type: string }
// `argument_types` is a comma-separated STRING, not an array — the backend
// (connectors/starburst.py: `argument_types: str`) passes through what
// SHOW FUNCTIONS returns verbatim. It was mistyped as string[] here, which
// made StarburstTree call .join() on a string and throw at runtime.
export interface StarburstUdf { name: string; return_type: string; argument_types: string }
export interface Column { name: string; data_type: string; ordinal?: number }
export interface PreviewResult { columns: string[]; rows: unknown[][]; row_count: number }
// `catalog`/`type`/`source_available` are only present on the Databricks
// variant of this route (verified against the live response, see
// backend/app/connectors/databricks_browse.py:get_function_source); the
// Redshift route returns schema/name/source only, hence the optionals.
export interface RoutineSource {
  schema: string;
  name: string;
  source: string;
  catalog?: string;
  type?: string;
  source_available?: boolean;
}
// Same four fields as StarburstTable, but for a routine rather than a
// relation — kept as its own name so the tree code reads honestly.
export interface DatabricksRoutine { catalog: string; schema: string; name: string; type: string }

export const explorerApi = {
  // Redshift
  redshiftDatabases: () => get<Named[]>("/explore/redshift/databases"),
  redshiftSchemas: () => get<Named[]>("/explore/redshift/schemas"),
  redshiftTables: (schema: string) => get<RedshiftTable[]>(`/explore/redshift/schemas/${encodeURIComponent(schema)}/tables`),
  redshiftColumns: (schema: string, table: string) =>
    get<Column[]>(`/explore/redshift/schemas/${encodeURIComponent(schema)}/tables/${encodeURIComponent(table)}/columns`),
  redshiftRoutines: (schema: string) => get<RedshiftRoutine[]>(`/explore/redshift/schemas/${encodeURIComponent(schema)}/routines`),
  // G17 Stage 1: preview row limit unified at 100 across all three systems
  // (previews now scroll properly, so 10 was needlessly restrictive).
  redshiftPreview: (schema: string, table: string, limit = 100) =>
    get<PreviewResult>(
      `/explore/redshift/schemas/${encodeURIComponent(schema)}/tables/${encodeURIComponent(table)}/preview?limit=${limit}`,
    ),

  // Starburst
  starburstCatalogs: () => get<Named[]>("/explore/starburst/catalogs"),
  starburstSchemas: (catalog: string) => get<Named[]>(`/explore/starburst/catalogs/${encodeURIComponent(catalog)}/schemas`),
  starburstTables: (catalog: string, schema: string) =>
    get<StarburstTable[]>(`/explore/starburst/catalogs/${encodeURIComponent(catalog)}/schemas/${encodeURIComponent(schema)}/tables`),
  starburstColumns: (catalog: string, schema: string, table: string) =>
    get<Column[]>(`/explore/starburst/catalogs/${encodeURIComponent(catalog)}/schemas/${encodeURIComponent(schema)}/tables/${encodeURIComponent(table)}/columns`),
  starburstUdfs: () => get<StarburstUdf[]>("/explore/starburst/udfs"),
  starburstPreview: (catalog: string, schema: string, table: string, limit = 100) =>
    get<PreviewResult>(
      `/explore/starburst/catalogs/${encodeURIComponent(catalog)}/schemas/${encodeURIComponent(schema)}/tables/${encodeURIComponent(table)}/preview?limit=${limit}`,
    ),

  // Migration triggers — these POSTs don't resolve until the real migration
  // reaches a terminal state (see backend/app/migrate.py). Callers must NOT
  // await this to drive "in progress" UI — start polling listMigrations /
  // getMigration immediately after firing it instead.
  migrateRedshiftDdl: (objectType: string, schema: string, name: string) =>
    post<Migration>(`/migrate/redshift/ddl/${objectType}/${encodeURIComponent(schema)}/${encodeURIComponent(name)}`),
  migrateStarburstDdl: (objectType: string, catalog: string, schema: string, name: string) =>
    post<Migration>(`/migrate/starburst/ddl/${objectType}/${encodeURIComponent(catalog)}/${encodeURIComponent(schema)}/${encodeURIComponent(name)}`),
  migrateRedshiftData: (schema: string, table: string) =>
    post<Migration>(`/migrate/redshift/data/${encodeURIComponent(schema)}/${encodeURIComponent(table)}`),
  // G7 — deterministic, non-LLM Starburst DDL path (~seconds, not minutes).
  migrateStarburstDdlCustom: (objectType: string, catalog: string, schema: string, name: string) =>
    post<Migration>(
      `/migrate/starburst/ddl-custom/${objectType}/${encodeURIComponent(catalog)}/${encodeURIComponent(schema)}/${encodeURIComponent(name)}`,
    ),
  migrateStarburstData: (catalog: string, schema: string, table: string) =>
    post<Migration>(
      `/migrate/starburst/data/${encodeURIComponent(catalog)}/${encodeURIComponent(schema)}/${encodeURIComponent(table)}`,
    ),
  // G15 Phase A — combined create-object + copy-data in one backend call
  // (table/view only; backend 400s for procedure/function/udf). Same
  // "don't await for in-progress UI" rule as the other migrate* calls above.
  migrateRedshiftTableAndData: (schema: string, name: string) =>
    post<Migration>(`/migrate/redshift/table-and-data/${encodeURIComponent(schema)}/${encodeURIComponent(name)}`),
  migrateStarburstTableAndData: (catalog: string, schema: string, name: string) =>
    post<Migration>(
      `/migrate/starburst/table-and-data/${encodeURIComponent(catalog)}/${encodeURIComponent(schema)}/${encodeURIComponent(name)}`,
    ),

  // G15 Phase A — read-only routine source for the new eye-button on
  // Redshift procedures/functions. Deliberately a separate GET, not the
  // migrate POST, so viewing source never triggers a real migration record.
  redshiftRoutineSource: (schema: string, name: string) =>
    get<RoutineSource>(`/explore/redshift/schemas/${encodeURIComponent(schema)}/routines/${encodeURIComponent(name)}/source`),

  // G18 — real Starburst UDF source via SHOW CREATE FUNCTION (replaces the
  // fabricated "body not recoverable" stub). Global to galaxy.functions, so
  // it takes the bare function name only.
  starburstUdfSource: (name: string) =>
    get<RoutineSource>(`/explore/starburst/udfs/${encodeURIComponent(name)}/source`),

  listMigrations: () => get<Migration[]>("/migrations"),
  getMigration: (id: string) => get<Migration>(`/migrations/${id}`),

  // Databricks (target) browse + preview — NOTE: if Agent ii (DatabricksTree
  // build) also adds a `databricksPreview`/catalogs/schemas/tables function
  // to this file, these may duplicate at merge time; dedupe by keeping one
  // definition per name.
  databricksCatalogs: () => get<Named[]>("/explore/databricks/catalogs"),
  databricksSchemas: (catalog: string) => get<Named[]>(`/explore/databricks/catalogs/${encodeURIComponent(catalog)}/schemas`),
  databricksTables: (catalog: string, schema: string) =>
    get<StarburstTable[]>(`/explore/databricks/catalogs/${encodeURIComponent(catalog)}/schemas/${encodeURIComponent(schema)}/tables`),
  // G17 — column / function / function-source parity with the Redshift and
  // Starburst trees. Response shapes confirmed by curling the live backend,
  // not inferred from the route names.
  databricksColumns: (catalog: string, schema: string, table: string) =>
    get<Column[]>(
      `/explore/databricks/catalogs/${encodeURIComponent(catalog)}/schemas/${encodeURIComponent(schema)}/tables/${encodeURIComponent(table)}/columns`,
    ),
  databricksFunctions: (catalog: string, schema: string) =>
    get<DatabricksRoutine[]>(
      `/explore/databricks/catalogs/${encodeURIComponent(catalog)}/schemas/${encodeURIComponent(schema)}/functions`,
    ),
  databricksFunctionSource: (catalog: string, schema: string, name: string) =>
    get<RoutineSource>(
      `/explore/databricks/catalogs/${encodeURIComponent(catalog)}/schemas/${encodeURIComponent(schema)}/functions/${encodeURIComponent(name)}/source`,
    ),
  databricksPreview: (catalog: string, schema: string, table: string, limit = 100) =>
    get<PreviewResult>(
      `/explore/databricks/catalogs/${encodeURIComponent(catalog)}/schemas/${encodeURIComponent(schema)}/tables/${encodeURIComponent(table)}/preview?limit=${limit}`,
    ),
};

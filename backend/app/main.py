"""FastAPI adapter — G1 scope: describe-transpile and transpile only.

Every endpoint builds its own fixed, validated argument list; nothing from
the request body is ever concatenated into a shell command. See
executor.build_argv for the allowlist enforcement.
"""
from __future__ import annotations

import os
import pathlib

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# G3.1: real source-system credentials for the explore endpoints below.
# backend/.env is gitignored, chmod 600 — see MEMORY.md's 2026-08-01 entry
# on why (credentials were pasted into chat, moved here immediately).
load_dotenv(pathlib.Path(__file__).resolve().parents[1] / ".env")

from . import chat as chat_module
from . import migrate
from .connectors import databricks_browse
from .connectors import redshift as redshift_conn
from .connectors import starburst as starburst_conn
from .connectors.databricks_browse import BrowseError
from .connectors.redshift import ConnectorError as RedshiftError
from .connectors.starburst import ConnectorError as StarburstError
from .databricks_target import TargetError, preview_table
from .executor import run_command_async
from .models import RunStatus, batch_store, migration_store, store

app = FastAPI(title="Lakebridge Adapter", version="0.2.0-g3.1")

# G3: the frontend dev server (Vite, localhost:5173) needs cross-origin
# access to this API (localhost:8811). Scoped to localhost dev ports only —
# this is a local single-user tool, not a public API (see README.md: no
# auth model exists yet, add one only when a phase actually needs it).
#
# Overridable via ALLOWED_ORIGINS (comma-separated) so serving the UI from a
# different origin — a Codespace, a staging host — is a config change rather
# than a code edit. The default is the previous hardcoded pair, so local
# development is unchanged.
#
# Deliberately NOT accepting "*": this API creates real Databricks objects and
# copies real data, and there is still no auth model. A wildcard would let any
# page a user visits drive it. Origins must be named explicitly.
_DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",") if o.strip()
]
if "*" in ALLOWED_ORIGINS:
    raise RuntimeError(
        "ALLOWED_ORIGINS must name origins explicitly; '*' is refused because this "
        "API has no auth model and performs real writes."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SAMPLES_DIR = REPO_ROOT / "samples" / "snowflake"
OUTPUT_DIR = REPO_ROOT / "backend" / "_transpile_out"
ANALYZE_REPORT_DIR = REPO_ROOT / "backend" / "_analyze_out"


class TranspileRequest(BaseModel):
    source_dialect: str = "snowflake"


class AnalyzeRequest(BaseModel):
    source_tech: str = "Snowflake"


class BatchItemRequest(BaseModel):
    """One explicit object in a POST /migrate/batch request. `catalog` is
    only required for source_system="starburst" — validated per-item at
    dispatch time so a bad item shows a clear 400 rather than a vague
    KeyError deep in migrate.py."""

    source_system: str  # "redshift" | "starburst"
    object_type: str  # "table" | "view" | "function" | "procedure" | "table-data"
    schema_name: str
    name: str
    catalog: str | None = None


class BatchRequest(BaseModel):
    items: list[BatchItemRequest]
    # G19: batch select mode used to migrate DDL only, so selecting tables
    # produced converted SQL and no rows. Defaults to True so the batch does
    # what a drag-and-drop does; pass false for DDL-only.
    include_data: bool = True


class ChatPlanRequest(BaseModel):
    instruction: str


class ChatExecuteRequest(BaseModel):
    """Either the full `plan` object /chat/plan returned, or its `plan_id`
    (valid only within the same process lifetime — plans are an in-memory
    proposal cache, not a persistent store; see chat.py)."""

    plan: dict | None = None
    plan_id: str | None = None


@app.post("/runs/describe-transpile")
def start_describe_transpile() -> dict:
    run = store.create(command="describe-transpile", args=[])
    run_command_async(run.id, "describe-transpile", [])
    return {"run_id": run.id}


@app.post("/runs/transpile")
def start_transpile(req: TranspileRequest) -> dict:
    if not SAMPLES_DIR.exists():
        raise HTTPException(status_code=400, detail=f"samples dir not found: {SAMPLES_DIR}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    args = [
        "--input-source",
        str(SAMPLES_DIR),
        "--output-folder",
        str(OUTPUT_DIR),
        "--source-dialect",
        req.source_dialect,
        "--skip-validation",
        "true",
    ]
    run = store.create(command="transpile", args=args)
    run_command_async(run.id, "transpile", args)
    return {"run_id": run.id}


@app.post("/runs/analyze")
def start_analyze(req: AnalyzeRequest) -> dict:
    if not SAMPLES_DIR.exists():
        raise HTTPException(status_code=400, detail=f"samples dir not found: {SAMPLES_DIR}")
    ANALYZE_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_file = ANALYZE_REPORT_DIR / "analysis.xlsx"
    args = [
        "--source-directory",
        str(SAMPLES_DIR),
        "--report-file",
        str(report_file),
        "--source-tech",
        req.source_tech,
    ]
    run = store.create(command="analyze", args=args)
    run_command_async(run.id, "analyze", args)
    return {"run_id": run.id}


@app.post("/runs/reconcile")
def start_reconcile() -> dict:
    """Wraps `reconcile`, which takes no flags — it dispatches the job
    registered by a prior `configure-reconcile` run against workspace state.
    See docs/RECONCILE.md for how that job was provisioned. If that
    infrastructure doesn't exist for a given workspace, this will complete
    with a non-zero exit and a clear error in its event stream rather than
    silently pretending to succeed.
    """
    run = store.create(command="reconcile", args=[])
    run_command_async(run.id, "reconcile", [])
    return {"run_id": run.id}


@app.get("/runs")
def list_runs() -> list[dict]:
    return [_run_summary(r) for r in store.list()]


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _run_summary(run)


@app.get("/runs/{run_id}/events")
def get_run_events(run_id: str) -> list[dict]:
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return [
        {"id": e.id, "timestamp": e.timestamp, "type": e.type.value, "message": e.message}
        for e in run.events
    ]


# ---------------------------------------------------------------- G4
# Reconcile validation detail + unified history view.

@app.get("/runs/{run_id}/reconcile")
def get_reconcile_detail(run_id: str) -> dict:
    """Dedicated view of a `reconcile` run's real validation detail.

    While the real dispatched Databricks job hasn't reached a terminal state
    yet, this honestly reports `status: "running"` with no result (see
    executor.py's `_finish_reconcile_run` — the Run itself stays "running"
    for the same reason). Once the job terminates, `result` is the real
    payload discovered from `lakebridge_demo.reconcile_meta.{main,metrics}`
    (row/column comparison counts, `reconciliation_passed`, etc.) — see
    executor.py's `_fetch_reconcile_result` docstring for exactly how that
    was captured.
    """
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.command != "reconcile":
        raise HTTPException(status_code=400, detail=f"run {run_id} is a {run.command!r} run, not reconcile")
    return {
        "run_id": run.id,
        "status": run.status.value,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "result": run.result,
    }


@app.get("/history")
def get_history() -> list[dict]:
    """Unified, real-data view across all three existing stores — no new
    persistence, just a merged read of RunStore/MigrationStore/BatchStore,
    sorted newest-first by whichever timestamp each kind actually has
    (started_at if set, else created_at for batches, else None-sorts-last).
    """
    items: list[dict] = []
    for r in store.list():
        items.append({"kind": "run", "sort_key": r.started_at, **_run_summary(r)})
    for m in migration_store.list():
        items.append({"kind": "migration", "sort_key": m.started_at, **_migration_summary(m)})
    for b in batch_store.list():
        items.append({"kind": "batch", "sort_key": b.started_at or b.created_at, **_batch_summary(b)})
    items.sort(key=lambda i: i["sort_key"] or "", reverse=True)
    return items


# ---------------------------------------------------------------- G6
# Natural-language chat layer: instruction -> reviewable plan -> confirm ->
# execute, entirely through the same real functions the routes above call.
# See chat.py's module docstring for why NL parsing is real deterministic
# pattern-matching against live inventory, not an invented LLM contract.

@app.post("/chat/plan")
def chat_plan(req: ChatPlanRequest) -> dict:
    """Never executes anything — returns a plan for review only."""
    return chat_module.parse_instruction(req.instruction)


@app.post("/chat/execute")
def chat_execute(req: ChatExecuteRequest) -> dict:
    try:
        plan = chat_module.resolve_plan(req.plan, req.plan_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail="plan_id not found (plans are an in-memory proposal cache, not persisted — re-run /chat/plan or pass the full plan body)",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not plan.get("action"):
        raise HTTPException(status_code=400, detail="plan has no action to execute")
    try:
        return chat_module.execute_plan(plan)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"execution failed: {exc}")


# ---------------------------------------------------------------- G3.1
# Real explore endpoints — read-only, no migration side effects.
# Connector errors (bad credentials, unreachable host, etc.) are already
# redacted by the connector layer; surfaced here as 502 rather than 500 so
# a client can distinguish "source system unreachable" from "our bug."

@app.get("/explore/redshift/databases")
def redshift_databases() -> list[dict]:
    try:
        return [{"name": d.name} for d in redshift_conn.list_databases()]
    except RedshiftError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/explore/redshift/schemas")
def redshift_schemas() -> list[dict]:
    try:
        return [{"name": s.name} for s in redshift_conn.list_schemas()]
    except RedshiftError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/explore/redshift/schemas/{schema}/tables")
def redshift_tables(schema: str) -> list[dict]:
    try:
        return [{"schema": t.schema, "name": t.name, "type": t.type} for t in redshift_conn.list_tables(schema)]
    except RedshiftError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/explore/redshift/schemas/{schema}/tables/{table}/columns")
def redshift_columns(schema: str, table: str) -> list[dict]:
    try:
        return [{"name": c.name, "data_type": c.data_type, "ordinal": c.ordinal} for c in redshift_conn.list_columns(schema, table)]
    except RedshiftError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/explore/redshift/schemas/{schema}/routines")
def redshift_routines(schema: str) -> list[dict]:
    try:
        return [{"schema": r.schema, "name": r.name, "type": r.type} for r in redshift_conn.list_routines(schema)]
    except RedshiftError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ---------------------------------------------------------------- G15
# Read-only routine source preview. Deliberately NOT the migrate endpoint —
# no Migration record, no job-tracking side effects, just the same real
# get_procedure_ddl/get_function_ddl calls migrate_redshift_ddl already uses
# internally, exposed for the tree's eye-button preview. Function vs
# procedure is resolved the same way `list_routines` already reports it
# (information_schema.routines.routine_type), not guessed or re-derived.

@app.get("/explore/redshift/schemas/{schema}/routines/{name}/source")
def redshift_routine_source(schema: str, name: str) -> dict:
    try:
        routines = [r for r in redshift_conn.list_routines(schema) if r.name == name]
        if not routines:
            raise HTTPException(status_code=404, detail=f"routine not found: {schema}.{name}")
        routine_type = routines[0].type
        if routine_type == "PROCEDURE":
            source = redshift_conn.get_procedure_ddl(schema, name)
        elif routine_type == "FUNCTION":
            source = redshift_conn.get_function_ddl(schema, name)
        else:
            raise HTTPException(status_code=400, detail=f"unsupported routine type: {routine_type}")
        return {"schema": schema, "name": name, "type": routine_type, "source": source}
    except RedshiftError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/explore/starburst/catalogs")
def starburst_catalogs() -> list[dict]:
    try:
        return [{"name": c.name} for c in starburst_conn.list_catalogs()]
    except StarburstError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/explore/starburst/catalogs/{catalog}/schemas")
def starburst_schemas(catalog: str) -> list[dict]:
    try:
        return [{"name": s.name} for s in starburst_conn.list_schemas(catalog)]
    except StarburstError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/explore/starburst/catalogs/{catalog}/schemas/{schema}/tables")
def starburst_tables(catalog: str, schema: str) -> list[dict]:
    try:
        return [
            {"catalog": t.catalog, "schema": t.schema, "name": t.name, "type": t.type}
            for t in starburst_conn.list_tables(catalog, schema)
        ]
    except StarburstError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/explore/starburst/catalogs/{catalog}/schemas/{schema}/tables/{table}/columns")
def starburst_columns(catalog: str, schema: str, table: str) -> list[dict]:
    try:
        return [{"name": c.name, "data_type": c.data_type} for c in starburst_conn.list_columns(catalog, schema, table)]
    except StarburstError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/explore/starburst/udfs")
def starburst_udfs() -> list[dict]:
    """UDFs live only in galaxy.functions — see connectors/starburst.py."""
    try:
        return [{"name": u.name, "return_type": u.return_type, "argument_types": u.argument_types} for u in starburst_conn.list_udfs()]
    except StarburstError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ---------------------------------------------------------------- G18
# Read-only Starburst UDF source. Mirrors the Redshift routine-source route's
# response shape exactly (RoutineSource) so SourcePanel can consume both.
# Backed by the real SHOW CREATE FUNCTION statement — see the G18 correction
# in connectors/starburst.py; this route replaces a previously fabricated stub.

@app.get("/explore/starburst/udfs/{name}/source")
def starburst_udf_source(name: str) -> dict:
    try:
        starburst_conn._ident(name)  # reject injection-shaped names before any query
        udfs = [u for u in starburst_conn.list_udfs() if u.name == name]
        if not udfs:
            raise HTTPException(status_code=404, detail=f"udf not found: galaxy.functions.{name}")
        source = starburst_conn.get_udf_ddl(name)
        return {
            "catalog": "galaxy",
            "schema": "functions",
            "name": name,
            "type": "FUNCTION",
            "source": source,
            "source_available": True,
        }
    except StarburstError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ---------------------------------------------------------------- G9.1
# Source-side table preview — same response shape as the existing
# /explore/databricks/.../preview route so the frontend can reuse its
# PreviewResult type. Real SELECT ... LIMIT against the live source
# systems, columns/rows guarded by each connector's own _ident().

@app.get("/explore/redshift/schemas/{schema}/tables/{table}/preview")
def redshift_preview(schema: str, table: str, limit: int = 10) -> dict:
    try:
        columns, rows = redshift_conn.preview_table(schema, table, limit=limit)
        return {"columns": columns, "rows": [list(r) for r in rows], "row_count": len(rows)}
    except RedshiftError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/explore/starburst/catalogs/{catalog}/schemas/{schema}/tables/{table}/preview")
def starburst_preview(catalog: str, schema: str, table: str, limit: int = 10) -> dict:
    try:
        columns, rows = starburst_conn.preview_table(catalog, schema, table, limit=limit)
        return {"columns": columns, "rows": [list(r) for r in rows], "row_count": len(rows)}
    except StarburstError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ---------------------------------------------------------------- G3.2
# Real migration execution. DDL/code endpoints run synchronously — real
# transpile/llm-transpile calls take a few seconds to tens of seconds,
# acceptable for this phase's scope (async streaming is a G3.3 UI concern,
# not needed to prove the migration logic itself works).

@app.post("/migrate/redshift/ddl/{object_type}/{schema}/{name}")
def migrate_redshift_ddl_endpoint(object_type: str, schema: str, name: str, force: bool = False) -> dict:
    if object_type not in ("table", "view", "function", "procedure"):
        raise HTTPException(status_code=400, detail=f"unsupported object_type: {object_type}")
    mig = migrate.migrate_redshift_ddl(object_type, schema, name, force=force)
    return _migration_summary(mig)


@app.post("/migrate/starburst/ddl/{object_type}/{catalog}/{schema}/{name}")
def migrate_starburst_ddl_endpoint(object_type: str, catalog: str, schema: str, name: str, force: bool = False) -> dict:
    if object_type not in ("table", "view"):
        raise HTTPException(
            status_code=400,
            detail=f"unsupported object_type for Starburst: {object_type} (UDF logic isn't recoverable — see connectors/starburst.py)",
        )
    mig = migrate.migrate_starburst_ddl(object_type, catalog, schema, name, force=force)
    return _migration_summary(mig)


@app.post("/migrate/redshift/data/{schema}/{table}")
def migrate_redshift_data_endpoint(schema: str, table: str) -> dict:
    mig = migrate.copy_redshift_table_data(schema, table)
    return _migration_summary(mig)


# ---------------------------------------------------------------- G15
# Combined create-object + copy-data in one call, for drag-drop's new
# "no separate copy-data step" behavior. Table/view only — functions and
# procedures have no data of their own and stay on the DDL-only routes
# above. object_type comes in as a query param (default "table") to match
# the two-shape distinction migrate_redshift_ddl already uses, without
# adding it to the URL path (no path segment for it in the plan's route
# shape: /migrate/redshift/table-and-data/{schema}/{name}).

@app.post("/migrate/redshift/table-and-data/{schema}/{name}")
def migrate_and_copy_redshift_table_endpoint(schema: str, name: str, object_type: str = "table") -> dict:
    if object_type not in ("table", "view"):
        raise HTTPException(status_code=400, detail=f"unsupported object_type: {object_type} (must be table or view)")
    mig = migrate.migrate_and_copy_redshift_table(schema, name, object_type)
    return _migration_summary(mig)


@app.post("/migrate/starburst/table-and-data/{catalog}/{schema}/{name}")
def migrate_and_copy_starburst_table_endpoint(catalog: str, schema: str, name: str, object_type: str = "table") -> dict:
    if object_type not in ("table", "view"):
        raise HTTPException(status_code=400, detail=f"unsupported object_type: {object_type} (must be table or view)")
    mig = migrate.migrate_and_copy_starburst_table(catalog, schema, name, object_type)
    return _migration_summary(mig)


# ---------------------------------------------------------------- G7
# Custom, deterministic Starburst pipeline — genuinely separate endpoints
# from /migrate/starburst/ddl/... above (the llm-transpile path), which is
# untouched and stays fully live per this phase's requirements.

@app.post("/migrate/starburst/ddl-custom/{object_type}/{catalog}/{schema}/{name}")
def migrate_starburst_ddl_custom_endpoint(object_type: str, catalog: str, schema: str, name: str, force: bool = False) -> dict:
    if object_type not in ("table", "view"):
        raise HTTPException(
            status_code=400,
            # G18: the old wording here also claimed "UDF bodies aren't
            # recoverable", which is FALSE — SHOW CREATE FUNCTION returns the
            # real body (see connectors/starburst.py). This translator is
            # table/view-only for a different reason: it has no UDF rules.
            detail=f"unsupported object_type for this Starburst translator: {object_type} "
            "(it handles tables and views only). Starburst has no stored procedures at all — "
            "CREATE PROCEDURE is a grammar-level syntax error on Trino. UDF source IS readable "
            "via GET /explore/starburst/udfs/{name}/source.",
        )
    mig = migrate.migrate_starburst_ddl_custom(object_type, catalog, schema, name, force=force)
    return _migration_summary(mig)


@app.post("/migrate/starburst/data/{catalog}/{schema}/{table}")
def migrate_starburst_data_endpoint(catalog: str, schema: str, table: str) -> dict:
    mig = migrate.copy_starburst_table_data(catalog, schema, table)
    return _migration_summary(mig)


# ---------------------------------------------------------------- G3.4
# Batch/whole-schema migration. Returns immediately with a pending batch id
# — real per-object work runs on a background thread (migrate.start_batch),
# the same async-dispatch shape already used for /runs/* (executor.py) and
# the Starburst llm-transpile dispatch-then-poll path (migrate.py). A batch
# must never report "completed" if any real member migration failed — see
# `_batch_summary`'s status derivation and BatchStatus.COMPLETED_WITH_ERRORS.

@app.post("/migrate/redshift/schema/{schema}/batch")
def migrate_redshift_schema_batch_endpoint(schema: str, include_data: bool = True) -> dict:
    """Migrates every real table/view/function/procedure in a Redshift
    schema, enumerated live via redshift_conn (never a hardcoded list).
    include_data=true additionally copies every real base table's rows."""
    try:
        items = migrate.build_redshift_schema_batch_items(schema, include_data=include_data)
    except RedshiftError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    if not items:
        raise HTTPException(status_code=400, detail=f"no real objects found in redshift schema: {schema}")
    batch = migrate.start_batch(items)
    return _batch_summary(batch)


# ---------------------------------------------------------------- G9
# Starburst whole-schema batch. Deliberately NOT `migrate.start_batch`/
# `run_batch` above — those still dispatch Starburst DDL items to the old
# `migrate_starburst_ddl` llm-transpile path via `_run_single_batch_item`.
# `migrate.start_starburst_schema_batch`/`run_starburst_schema_batch` (moved
# here from chat.py, where G8's chat "batch-migrate schema" intent already
# exercised this exact code) dispatch only to G7's fast deterministic path
# (`migrate.migrate_starburst_ddl_custom`, `migrate.copy_starburst_table_data`).
# Same response shape as the Redshift batch route above (`_batch_summary`).

@app.post("/migrate/starburst/catalog/{catalog}/schema/{schema}/batch")
def migrate_starburst_schema_batch_endpoint(catalog: str, schema: str, include_data: bool = True) -> dict:
    """Migrates every real table/view in a Starburst catalog.schema,
    enumerated live via starburst_conn (never a hardcoded list), using G7's
    fast deterministic custom-DDL path. include_data=true additionally
    copies every real base table's rows."""
    try:
        batch = migrate.start_starburst_schema_batch(catalog, schema, include_data)
    except StarburstError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return _batch_summary(batch)


@app.post("/migrate/batch")
def migrate_batch_endpoint(req: BatchRequest) -> dict:
    """Explicit multi-object batch — an arbitrary caller-selected mix of
    real Redshift and/or Starburst objects, one migration each."""
    if not req.items:
        raise HTTPException(status_code=400, detail="items must be non-empty")
    items: list[dict] = []
    for i in req.items:
        if i.source_system not in ("redshift", "starburst"):
            raise HTTPException(status_code=400, detail=f"unsupported source_system: {i.source_system}")
        if i.source_system == "redshift" and i.object_type not in ("table", "view", "function", "procedure", "table-data"):
            raise HTTPException(status_code=400, detail=f"unsupported object_type for redshift: {i.object_type}")
        if i.source_system == "starburst":
            if i.object_type not in ("table", "view"):
                raise HTTPException(status_code=400, detail=f"unsupported object_type for starburst: {i.object_type}")
            if not i.catalog:
                raise HTTPException(status_code=400, detail="catalog is required for starburst batch items")
        item = {"source_system": i.source_system, "object_type": i.object_type, "schema": i.schema_name, "name": i.name}
        if i.catalog:
            item["catalog"] = i.catalog
        items.append(item)
    items = migrate.expand_batch_items(items, req.include_data)
    batch = migrate.start_batch(items)
    return _batch_summary(batch)


@app.get("/batches")
def list_batches() -> list[dict]:
    return [_batch_summary(b) for b in batch_store.list()]


@app.get("/batches/{batch_id}")
def get_batch(batch_id: str) -> dict:
    batch = batch_store.get(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="batch not found")
    return _batch_summary(batch, include_migrations=True)


def _batch_summary(batch, include_migrations: bool = False) -> dict:  # noqa: ANN001
    migrations = [migration_store.get(mid) for mid in batch.migration_ids]
    migrations = [m for m in migrations if m is not None]
    completed = sum(1 for m in migrations if m.status == RunStatus.COMPLETED)
    failed = sum(1 for m in migrations if m.status == RunStatus.FAILED)
    summary = {
        "id": batch.id,
        "status": batch.status.value,
        "total_items": batch.total_items,
        "completed_items": completed,
        "failed_items": failed,
        "dispatched_items": len(migrations),
        "created_at": batch.created_at,
        "started_at": batch.started_at,
        "ended_at": batch.ended_at,
    }
    if include_migrations:
        summary["migrations"] = [_migration_summary(m) for m in migrations]
    return summary


@app.get("/migrations")
def list_migrations() -> list[dict]:
    return [_migration_summary(m) for m in migration_store.list()]


@app.get("/migrations/{migration_id}")
def get_migration(migration_id: str) -> dict:
    mig = migration_store.get(migration_id)
    if mig is None:
        raise HTTPException(status_code=404, detail="migration not found")
    return _migration_summary(mig)


def _migration_summary(mig) -> dict:  # noqa: ANN001
    return {
        "id": mig.id,
        "source_system": mig.source_system,
        "object_type": mig.object_type,
        "object_name": mig.object_name,
        "engine": mig.engine.value,
        "status": mig.status.value,
        "source_ddl": mig.source_ddl,
        "output_ddl": mig.output_ddl,
        "error": mig.error,
        "row_count": mig.row_count,
        "started_at": mig.started_at,
        "ended_at": mig.ended_at,
        "target_catalog": mig.target_catalog,
        "target_schema": mig.target_schema,
        "target_table": mig.target_table,
    }


def _run_summary(run) -> dict:  # noqa: ANN001
    return {
        "id": run.id,
        "command": run.command,
        "status": run.status.value,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "exit_code": run.exit_code,
        "result": run.result,
    }


# --- G8: Databricks (target) browse + preview routes — new block, appended
# by Agent A. Mirrors the /explore/starburst/* routes above exactly. Only
# this file is touched for this block (no models.py/migrate.py edits here).

@app.get("/explore/databricks/catalogs")
def databricks_catalogs() -> list[dict]:
    try:
        return [{"name": c} for c in databricks_browse.list_catalogs()]
    except BrowseError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/explore/databricks/catalogs/{catalog}/schemas")
def databricks_schemas(catalog: str) -> list[dict]:
    try:
        return [{"name": s} for s in databricks_browse.list_schemas(catalog)]
    except BrowseError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/explore/databricks/catalogs/{catalog}/schemas/{schema}/tables")
def databricks_tables(catalog: str, schema: str) -> list[dict]:
    try:
        return [
            {"catalog": t.catalog, "schema": t.schema, "name": t.name, "type": t.type}
            for t in databricks_browse.list_tables(catalog, schema)
        ]
    except BrowseError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# --- G17 Stage 1 (items 3 + 4): Databricks column listing and UC functions.
# Response shapes deliberately match the existing Redshift routes exactly
# (`name`/`data_type`/`ordinal` for columns; `schema`/`name`/`type` for
# routines; `schema`/`name`/`type`/`source` for routine source) so the
# frontend's ColumnsList and SourcePanel render them unchanged.

@app.get("/explore/databricks/catalogs/{catalog}/schemas/{schema}/tables/{table}/columns")
def databricks_columns(catalog: str, schema: str, table: str) -> list[dict]:
    try:
        return [
            {"name": c.name, "data_type": c.data_type, "ordinal": c.ordinal}
            for c in databricks_browse.list_columns(catalog, schema, table)
        ]
    except BrowseError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/explore/databricks/catalogs/{catalog}/schemas/{schema}/functions")
def databricks_functions(catalog: str, schema: str) -> list[dict]:
    try:
        return [
            {"catalog": r.catalog, "schema": r.schema, "name": r.name, "type": r.type}
            for r in databricks_browse.list_functions(catalog, schema)
        ]
    except BrowseError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/explore/databricks/catalogs/{catalog}/schemas/{schema}/functions/{name}/source")
def databricks_function_source(catalog: str, schema: str, name: str) -> dict:
    try:
        result = databricks_browse.get_function_source(catalog, schema, name)
    except BrowseError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    if not result:
        raise HTTPException(status_code=404, detail=f"function not found: {catalog}.{schema}.{name}")
    return result


@app.get("/explore/databricks/catalogs/{catalog}/schemas/{schema}/tables/{table}/preview")
def databricks_preview(catalog: str, schema: str, table: str, limit: int = 100) -> dict:
    try:
        columns, rows = preview_table(catalog, schema, table, limit=limit)
        return {"columns": columns, "rows": [list(r) for r in rows], "row_count": len(rows)}
    except TargetError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

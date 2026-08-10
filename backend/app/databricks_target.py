"""Real connection to the Databricks SQL warehouse — the migration TARGET.

This is deliberately separate from executor.py (which shells out to the
`databricks` CLI for Lakebridge commands). This module runs actual SQL
against the workspace warehouse: creating the migration output schema,
executing transpiled DDL, and copying real row data — the capability
Lakebridge itself doesn't have (see PLAN.md's G3 rebuild section / MEMORY.md
2026-08-01, verified against the live CLI and Databricks' own docs).
"""
from __future__ import annotations

import os
import threading
import time

from databricks import sql
from databricks.sdk.core import Config

from .redact import redact

TARGET_CATALOG = os.getenv("DATABRICKS_TARGET_CATALOG", "lakebridge_demo")
TARGET_SCHEMA = os.getenv("DATABRICKS_TARGET_SCHEMA", "g3_migrations")

# Overridable from .env so pointing at a different SQL warehouse (e.g. a paid
# one, to get past the free tier's daily query cap) is a config change rather
# than a code edit. The defaults are the existing eval warehouse, so behaviour
# is unchanged when the vars are absent.
#
# databricks_browse.py deliberately reuses this module's _connect(), so these
# two values govern EVERY Databricks read and write in the app.
_WAREHOUSE_HOSTNAME = os.getenv(
    "DATABRICKS_WAREHOUSE_HOSTNAME", "<old-workspace>.cloud.databricks.com"
)
_WAREHOUSE_HTTP_PATH = os.getenv(
    "DATABRICKS_WAREHOUSE_HTTP_PATH", "/sql/1.0/warehouses/<old-warehouse-id>"
)
_DATABRICKS_PROFILE = os.getenv("DATABRICKS_PROFILE", "lakebridge-eval")


class TargetError(RuntimeError):
    pass


def _connect():
    try:
        # executor.databricks_config() resolves profile-vs-environment auth in
        # one place, so this works both on a laptop (named profile) and in a
        # container with no ~/.databrickscfg (env vars).
        from .executor import databricks_config

        cfg = databricks_config()
        return sql.connect(
            server_hostname=_WAREHOUSE_HOSTNAME,
            http_path=_WAREHOUSE_HTTP_PATH,
            credentials_provider=lambda: cfg.authenticate,
        )
    except Exception as exc:  # noqa: BLE001
        raise TargetError(redact(str(exc))) from exc


def _ident(name: str) -> str:
    """Minimal identifier guard for names interpolated into statements that
    don't support parameter binding for identifiers (SHOW ... IN, table
    names in FROM). Mirrors connectors/starburst.py's `_ident()` exactly —
    G8 addition."""
    if not name.replace("_", "").replace("-", "").isalnum():
        raise TargetError(f"invalid identifier: {name!r}")
    return name


def preview_table(catalog: str, schema: str, table: str, limit: int = 100) -> tuple[list[str], list[tuple]]:
    """Real SELECT * ... LIMIT against the target warehouse. Returns
    (columns, rows) — columns come from cursor.description, not fabricated.
    Identifier-guarded (G8)."""
    fq = f"{_ident(catalog)}.{_ident(schema)}.{_ident(table)}"
    # G19: shares the cached connection like execute() does — this is the route
    # behind every eye-button preview, so it paid the ~4.6s handshake on each.
    with _conn_lock:
        conn = _shared_connection()
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM {fq} LIMIT {int(limit)}")
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()
            return columns, [tuple(r) for r in rows]
        except Exception as exc:  # noqa: BLE001
            raise TargetError(redact(str(exc))) from exc


# ---------------------------------------------------------------- G19
# Connection reuse.
#
# Measured against this warehouse, not assumed: `_connect()` costs ~4.6s
# (auth + session setup) while the statements themselves cost ~0.4s. Every
# call used to open and close its own connection, so a single create-and-copy
# paid that 4.6s four times over in the data-copy leg alone (DROP, CREATE,
# INSERT, verifying SELECT COUNT(*)) — about 18s of the ~48s a chat-driven
# migration took, spent entirely on handshakes.
#
# One cached connection, guarded by a lock because FastAPI runs these sync
# endpoints in a threadpool and two migrations can overlap. Statements are
# ~0.4s, so serialising them costs far less than reconnecting would.
_conn_lock = threading.RLock()
_shared_conn = None
_last_used = 0.0
# A warehouse-side session can be reaped while idle. Past this long unused, we
# spend one cheap round-trip proving the connection is alive rather than
# discovering it isn't partway through a real statement.
_IDLE_PROBE_AFTER_S = 120.0


def _shared_connection():
    """Live connection, reconnecting only when genuinely necessary."""
    global _shared_conn, _last_used
    if _shared_conn is not None and (time.monotonic() - _last_used) > _IDLE_PROBE_AFTER_S:
        try:
            cur = _shared_conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchall()
        except Exception:  # noqa: BLE001 — stale session; drop it and redial
            try:
                _shared_conn.close()
            except Exception:  # noqa: BLE001
                pass
            _shared_conn = None
    if _shared_conn is None:
        _shared_conn = _connect()
    _last_used = time.monotonic()
    return _shared_conn


def close_shared_connection() -> None:
    """Explicit teardown, for tests and shutdown."""
    global _shared_conn
    with _conn_lock:
        if _shared_conn is not None:
            try:
                _shared_conn.close()
            except Exception:  # noqa: BLE001
                pass
            _shared_conn = None


def execute(statement: str, params: tuple | None = None) -> list[tuple]:
    """Run one statement against the target warehouse; returns rows if any.

    Deliberately does NOT retry a failed statement on a fresh connection: an
    INSERT that failed partway is not safe to blindly re-run, and we cannot
    reliably tell a dead socket from a rejected statement. Staleness is handled
    by the idle probe above instead.
    """
    with _conn_lock:
        conn = _shared_connection()
        try:
            cur = conn.cursor()
            cur.execute(statement, params) if params else cur.execute(statement)
            try:
                return cur.fetchall()
            except Exception:  # noqa: BLE001 — DDL/DML statements have no result set
                return []
        except Exception as exc:  # noqa: BLE001
            raise TargetError(redact(str(exc))) from exc


_REDSHIFT_TO_DATABRICKS_TYPE = {
    "smallint": "SMALLINT",
    "integer": "INT",
    "bigint": "BIGINT",
    "character varying": "STRING",
    "character": "STRING",
    "double precision": "DOUBLE",
    "real": "FLOAT",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "timestamp without time zone": "TIMESTAMP",
    "numeric": "DECIMAL(18,4)",
}


def databricks_type_for(source_type: str) -> str:
    """Best-effort type mapping for the data-copy path's CREATE TABLE.
    This is intentionally separate from Lakebridge's own transpiler output —
    it only needs to be good enough to land real rows, not to be the
    authoritative DDL (that's what the transpile path in migrate.py is for).
    """
    base = source_type.split("(")[0].strip().lower()
    return _REDSHIFT_TO_DATABRICKS_TYPE.get(base, "STRING")


def create_target_table(
    table_name: str,
    columns: list[tuple[str, str]],
    type_mapper=databricks_type_for,
) -> str:
    """columns: list of (name, source_data_type). Returns the fully-qualified
    target table name. Existing table of the same name is replaced, since
    this is demo/migration-output space, not production data.

    `type_mapper` defaults to the existing Redshift mapper (`databricks_type_for`)
    so the Redshift call site's behavior is unchanged — G7 added this
    parameter so `copy_starburst_table_data` can pass
    `starburst_type_map.databricks_type_for_trino` instead, without
    duplicating this DROP/CREATE logic in a second function."""
    fq = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.{table_name}"
    col_defs = ", ".join(f"`{name}` {type_mapper(dtype)}" for name, dtype in columns)
    execute(f"DROP TABLE IF EXISTS {fq}")
    execute(f"CREATE TABLE {fq} ({col_defs})")
    return fq


def insert_rows(fq_table: str, columns: list[str], rows: list[tuple], chunk_size: int = 500) -> int:
    """Chunked INSERT — real tables here are small, but this must not assume
    that forever (PLAN.md's G3.2 requirement). Returns total rows inserted.

    G15 apostrophe-bug fix: previously built each INSERT as fully-inlined SQL
    text via `_sql_literal`, which doubled `'` -> `''` per the normal SQL
    escaping convention. That convention is correct SQL, but real testing
    against the live warehouse (see MEMORY.md's G14 finding and G15's
    follow-up investigation) showed the Databricks SQL connector's own
    `execute()` silently strips the escaped apostrophe from inlined text
    (`SELECT 'Dick''s...'` -> `Dicks...`) — a connector-level defect in how
    it handles doubled-quote text, not a logic error in the escaping itself.
    Confirmed root cause and fix by direct comparison against the real
    warehouse: bound (`%(name)s`-style) parameters round-trip every value
    tested untouched (apostrophes, NULL, bool, float, multi-row single
    INSERT with per-row-unique parameter names) while inlined literals do
    not. Switched to always binding parameters instead of inlining values,
    for every value shape, not just strings — this also removes any
    inlined-literal SQL-injection surface as a side effect."""
    if not rows:
        return 0
    col_list = ", ".join(f"`{c}`" for c in columns)
    total = 0
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start : start + chunk_size]
        params: dict[str, object] = {}
        row_placeholders = []
        for row_idx, row in enumerate(chunk):
            names = [f"c{row_idx}_{col_idx}" for col_idx in range(len(row))]
            for name, value in zip(names, row):
                params[name] = value
            row_placeholders.append("(" + ", ".join(f"%({n})s" for n in names) + ")")
        values_sql = ", ".join(row_placeholders)
        execute(f"INSERT INTO {fq_table} ({col_list}) VALUES {values_sql}", params)
        total += len(chunk)
    return total


# ---------------------------------------------------------------- G19
# Creating the migrated object in Databricks from transpiled DDL.
#
# Until now `migrate` produced converted SQL text and nothing else — the object
# that appeared in the target came from `create_target_table` on the data-copy
# path, built from the source column types, never from Lakebridge's output.
# This is the piece that actually applies the transpiled DDL.
#
# Names are rewritten to the flat `{system}_{schema}_{name}` convention the
# copied tables already use (e.g. redshift_public_venue), so everything lands in
# one target schema and names can't collide across source systems.

# Lakebridge emits transpiler annotations between the keywords, e.g.
#   CREATE
#       /* DISTSTYLE AUTO */
#       TABLE demo_fast_test.customers
# so the gap between tokens has to allow block and line comments, not just
# whitespace. Found by running it, not by reading the transpiler.
_SQL_GAP = r"(?:\s|/\*.*?\*/|--[^\n]*\n)+"
_CREATE_OBJECT_RE_TMPL = (
    r"(?is)\b(CREATE" + _SQL_GAP + r"(?:OR" + _SQL_GAP + r"REPLACE" + _SQL_GAP + r")?"
    r"(?:(?:EXTERNAL|TEMPORARY|TEMP)" + _SQL_GAP + r")?"
    r"(TABLE|VIEW|FUNCTION|PROCEDURE)" + _SQL_GAP + r")"
    # 0-2 leading qualifiers: the Redshift transpiler emits `schema.name` while
    # the Starburst translator emits `catalog.schema.name`. Matching only
    # `{schema}.` meant every Starburst view failed with "could not locate a
    # CREATE statement" — found by running one, not by reading the translator.
    # NB: braces doubled — this template goes through str.format().
    r"(?:(?:\"|`)?[A-Za-z_][\w$]*(?:\"|`)?\s*\.\s*){{0,2}}"
    r"(?:\"|`)?{name}(?:\"|`)?"
)


def target_object_name(source_system: str, schema: str, name: str, catalog: str | None = None) -> str:
    """The flat target name, matching what copy_*_table_data already produces.

    The catalog segment is NOT optional decoration: copy_starburst_table_data
    names its tables `starburst_{catalog}_{schema}_{table}`. Omitting it here
    made the DDL path and the data path create two differently-named tables for
    the same Starburst object during a single create-and-copy.
    """
    parts = [source_system, catalog, schema, name] if catalog else [source_system, schema, name]
    return "_".join(parts)


def rewrite_ddl_target(
    output_ddl: str, source_system: str, schema: str, name: str, catalog: str | None = None
) -> tuple[str, str]:
    """Point the transpiled DDL's CREATE at our target catalog/schema.

    Returns (rewritten_ddl, fully_qualified_target). Raises TargetError if the
    object being created can't be found in the DDL — better to refuse than to
    execute a statement we don't understand against the warehouse.
    """
    import re

    target = target_object_name(source_system, _ident(schema), _ident(name), _ident(catalog) if catalog else None)
    fq = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.{target}"
    pattern = _CREATE_OBJECT_RE_TMPL.format(schema=re.escape(schema), name=re.escape(name))

    def _replace(m: "re.Match[str]") -> str:
        # Normalise to CREATE OR REPLACE. Without it a second `migrate` of the
        # same object fails with TABLE_OR_VIEW_ALREADY_EXISTS, so migrating
        # anything twice would error — and re-running a migration is the normal
        # case here. This matches create_target_table's existing DROP+CREATE
        # convention: the target schema is migration output, not source data.
        keyword = m.group(2).upper()
        return f"CREATE OR REPLACE {keyword} {fq}"

    rewritten, count = re.subn(pattern, _replace, output_ddl, count=1)
    if count == 0:
        raise TargetError(
            f"could not locate a CREATE statement for {schema}.{name} in the transpiled DDL, "
            "so it was not applied to Databricks"
        )
    return rewritten, fq


def create_object_from_ddl(
    output_ddl: str, source_system: str, schema: str, name: str, catalog: str | None = None
) -> str:
    """Execute the transpiled DDL against the target warehouse. Returns the
    fully-qualified name created. Any engine rejection propagates as TargetError
    — a routine Databricks SQL genuinely cannot express must surface as a real
    failure, not be swallowed into a green migration."""
    rewritten, fq = rewrite_ddl_target(output_ddl, source_system, schema, name, catalog)
    execute(rewritten)
    return fq


def object_exists(name: str) -> bool:
    """Does `name` already exist in the target schema, as a relation, function
    or procedure? Used to answer "this was already migrated" before spending
    ~12s re-reading and re-transpiling the source.

    Checks relations AND routines: a migrated procedure is invisible to
    `SHOW TABLES`, and `SHOW TABLES` alone would report "not migrated" for every
    function and procedure.

    Uses `information_schema` rather than `SHOW ...`. The first version ran
    `USE CATALOG` first, because `SHOW USER FUNCTIONS IN <catalog>.<schema>`
    fails with CROSS_CATALOG_SCHEMA_REFERENCE_NOT_SUPPORTED — but `USE CATALOG`
    mutates the session, and this module now shares ONE connection across every
    caller, so a lookup was silently changing the default catalog for unrelated
    queries. `information_schema` is fully qualifiable, so nothing about the
    session changes. (databricks_browse.py already relies on
    `information_schema.routines` in this workspace.)
    """
    schema_lit = TARGET_SCHEMA.replace("'", "''")
    name_lit = name.replace("'", "''")
    with _conn_lock:
        try:
            relations = execute(
                f"SELECT 1 FROM {TARGET_CATALOG}.information_schema.tables "
                f"WHERE table_schema = '{schema_lit}' AND table_name = '{name_lit}' LIMIT 1"
            )
            if relations:
                return True
            routines = execute(
                f"SELECT 1 FROM {TARGET_CATALOG}.information_schema.routines "
                f"WHERE routine_schema = '{schema_lit}' AND routine_name = '{name_lit}' LIMIT 1"
            )
            return bool(routines)
        except TargetError:
            # If we can't tell, don't claim it exists — fall through to a real
            # migration rather than wrongly reporting "already migrated".
            return False


# ---------------------------------------------------------------- demo reset
#
# Repeated testing fills the target schema with migrated objects, which makes a
# demo confusing: you cannot tell what the migration you just ran produced from
# what a previous test left behind. This resets the schema to a known small
# baseline — one object from each source plus the MCP probe function — so the
# next migration is visibly new.
#
# The three kept names are the demo baseline: a Redshift table, a Starburst
# table, and mcp_fallback_ping (which tests/test_databricks_mcp_client.py
# asserts exists and does NOT create, so dropping it would break that test).
DEMO_KEEP_OBJECTS = (
    "redshift_demo_fast_test_customers",
    "starburst_mcp2ohio_test_writes_churn_metrics",
    "mcp_fallback_ping",
)


def list_target_objects() -> list[dict]:
    """Every table/view and routine in the configured target schema, tagged with
    whether the reset would keep or drop it. Read-only: this is what the UI
    shows BEFORE anything is dropped, so a destructive click is never blind."""
    schema_lit = TARGET_SCHEMA.replace("'", "''")
    out: list[dict] = []
    with _conn_lock:
        rows = execute(
            f"SELECT table_name, table_type FROM {TARGET_CATALOG}.information_schema.tables "
            f"WHERE table_schema = '{schema_lit}' ORDER BY table_name"
        )
        for name, ttype in rows:
            out.append({
                "name": name,
                "kind": "VIEW" if str(ttype).upper() == "VIEW" else "TABLE",
                "keep": name in DEMO_KEEP_OBJECTS,
            })
        routines = execute(
            f"SELECT routine_name, routine_type FROM {TARGET_CATALOG}.information_schema.routines "
            f"WHERE routine_schema = '{schema_lit}' ORDER BY routine_name"
        )
        for name, rtype in routines:
            out.append({
                "name": name,
                "kind": str(rtype).upper() or "FUNCTION",
                "keep": name in DEMO_KEEP_OBJECTS,
            })
    return out


def reset_target_schema() -> dict:
    """Drop everything in the target schema except DEMO_KEEP_OBJECTS.

    Scoped to TARGET_CATALOG.TARGET_SCHEMA and nothing else — it cannot reach
    another schema, because the object list it works from is itself read from
    that schema's information_schema. Every dropped object is reproducible by
    re-running the migration that created it, which is what makes this safe to
    offer as a button.
    """
    objects = list_target_objects()
    dropped, failed = [], []
    for obj in objects:
        if obj["keep"]:
            continue
        name = _ident(obj["name"])
        fq = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.{name}"
        kind = obj["kind"]
        stmt = {
            "VIEW": f"DROP VIEW IF EXISTS {fq}",
            "PROCEDURE": f"DROP PROCEDURE IF EXISTS {fq}",
            "FUNCTION": f"DROP FUNCTION IF EXISTS {fq}",
        }.get(kind, f"DROP TABLE IF EXISTS {fq}")
        try:
            execute(stmt)
            dropped.append({"name": obj["name"], "kind": kind})
        except Exception as exc:  # noqa: BLE001
            failed.append({"name": obj["name"], "kind": kind, "error": redact(str(exc))[:200]})

    remaining = list_target_objects()
    kept = [o["name"] for o in remaining]
    # A kept baseline object that isn't there was already gone before the reset;
    # say so rather than implying the reset removed it.
    missing = [n for n in DEMO_KEEP_OBJECTS if n not in kept]
    return {
        "catalog": TARGET_CATALOG,
        "schema": TARGET_SCHEMA,
        "dropped": dropped,
        "failed": failed,
        "kept": kept,
        "missing_baseline": missing,
    }

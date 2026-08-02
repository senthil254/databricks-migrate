"""Real connector for browsing the Databricks migration TARGET (G8).

Deliberately thin — reuses `databricks_target._connect()` (same warehouse
connection, same auth) rather than duplicating connection/auth logic. Mirrors
the shape of `connectors/starburst.py`'s list_catalogs/list_schemas/list_tables.
"""
from __future__ import annotations

from dataclasses import dataclass

from .. import databricks_target
from ..databricks_target import TargetError, _ident
from ..redact import redact


class BrowseError(RuntimeError):
    pass


@dataclass
class TableRef:
    catalog: str
    schema: str
    name: str
    type: str = "table"


@dataclass
class ColumnRef:
    name: str
    data_type: str
    ordinal: int


@dataclass
class RoutineRef:
    catalog: str
    schema: str
    name: str
    type: str


def list_catalogs() -> list[str]:
    try:
        conn = databricks_target._connect()
    except Exception as exc:  # noqa: BLE001
        raise BrowseError(redact(str(exc))) from exc
    try:
        cur = conn.cursor()
        cur.execute("SHOW CATALOGS")
        return [r[0] for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        raise BrowseError(redact(str(exc))) from exc
    finally:
        conn.close()


def list_schemas(catalog: str) -> list[str]:
    try:
        catalog = _ident(catalog)  # validated before connecting — no live call for a bad identifier
    except TargetError as exc:
        raise BrowseError(str(exc)) from exc
    try:
        conn = databricks_target._connect()
    except Exception as exc:  # noqa: BLE001
        raise BrowseError(redact(str(exc))) from exc
    try:
        cur = conn.cursor()
        cur.execute(f"SHOW SCHEMAS IN {catalog}")
        return [r[0] for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        raise BrowseError(redact(str(exc))) from exc
    finally:
        conn.close()


def list_tables(catalog: str, schema: str) -> list[TableRef]:
    try:
        catalog = _ident(catalog)  # validated before connecting
        schema = _ident(schema)
    except TargetError as exc:
        raise BrowseError(str(exc)) from exc
    try:
        conn = databricks_target._connect()
    except Exception as exc:  # noqa: BLE001
        raise BrowseError(redact(str(exc))) from exc
    try:
        cur = conn.cursor()
        cur.execute(f"SHOW TABLES IN {catalog}.{schema}")
        rows = cur.fetchall()
        # SHOW TABLES columns: database, tableName, isTemporary (no reliable
        # table_type column across DBR versions) — default to "table".
        return [TableRef(catalog=catalog, schema=schema, name=r[1], type="table") for r in rows]
    except Exception as exc:  # noqa: BLE001
        raise BrowseError(redact(str(exc))) from exc
    finally:
        conn.close()


# ---------------------------------------------------------------- G17 Stage 1
# Columns + UC routines (functions) for the Databricks tree, mirroring the
# equivalent Redshift/Starburst explore capabilities.
#
# Sourcing decision, made against the REAL warehouse rather than guessed
# (probed 2026-08-02 on lakebridge_demo.g3_migrations):
#   * `information_schema.columns` / `.routines` / `.parameters` all answer
#     with bound `?` parameters for schema/table/function VALUES — only the
#     catalog is an identifier and it goes through `_ident()` first.
#   * `DESCRIBE FUNCTION EXTENDED` was tried and REJECTED as the source of
#     body text: it returns no body at all, and buries the signature under
#     ~100 rows of unrelated `spark.databricks.*` Configs lines.
#   * `SHOW USER FUNCTIONS IN cat.sch` fails outright on this warehouse with
#     CROSS_CATALOG_SCHEMA_REFERENCE_NOT_SUPPORTED.
#   * `information_schema.routines.routine_definition` DOES return the real
#     body (verified: `mcp_fallback_ping` -> "'databricks mcp fallback is
#     live'", and system.ai.python_exec -> its real multi-line Python body).

def _rows(statement: str, params: tuple) -> list:
    """Run a bound query via databricks_target.execute (which owns the
    connection inside its own try/except — no connect-outside-try)."""
    try:
        return databricks_target.execute(statement, params)
    except TargetError as exc:
        raise BrowseError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise BrowseError(redact(str(exc))) from exc


def list_columns(catalog: str, schema: str, table: str) -> list[ColumnRef]:
    try:
        catalog = _ident(catalog)  # identifier — validated before any live call
    except TargetError as exc:
        raise BrowseError(str(exc)) from exc
    rows = _rows(
        f"SELECT column_name, full_data_type, ordinal_position "
        f"FROM {catalog}.information_schema.columns "
        f"WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
        (schema, table),
    )
    return [ColumnRef(name=r[0], data_type=r[1], ordinal=int(r[2])) for r in rows]


def list_functions(catalog: str, schema: str) -> list[RoutineRef]:
    try:
        catalog = _ident(catalog)
    except TargetError as exc:
        raise BrowseError(str(exc)) from exc
    rows = _rows(
        f"SELECT routine_schema, routine_name, routine_type "
        f"FROM {catalog}.information_schema.routines "
        f"WHERE routine_schema = ? ORDER BY routine_name",
        (schema,),
    )
    return [RoutineRef(catalog=catalog, schema=r[0], name=r[1], type=r[2]) for r in rows]


def get_function_source(catalog: str, schema: str, name: str) -> dict:
    """Real function metadata + body from Unity Catalog's information_schema.

    Returns a dict with `source` ALWAYS a string (SourcePanel.tsx renders
    `source === null` as a permanent "Loading…" state) and an explicit
    `source_available` flag. When UC genuinely has no definition text for a
    routine, the returned text says so rather than fabricating a body — same
    honesty rule already applied to Starburst UDFs.
    """
    try:
        catalog = _ident(catalog)
    except TargetError as exc:
        raise BrowseError(str(exc)) from exc
    rows = _rows(
        f"SELECT routine_type, full_data_type, routine_body, routine_definition, "
        f"external_language, is_deterministic, comment "
        f"FROM {catalog}.information_schema.routines "
        f"WHERE routine_schema = ? AND routine_name = ?",
        (schema, name),
    )
    if not rows:
        return {}
    routine_type, returns, body_kind, definition, language, deterministic, comment = rows[0]

    params = _rows(
        f"SELECT parameter_name, full_data_type "
        f"FROM {catalog}.information_schema.parameters "
        f"WHERE specific_schema = ? AND specific_name = ? AND parameter_mode = 'IN' "
        f"ORDER BY ordinal_position",
        (schema, name),
    )
    arg_list = ", ".join(f"{p[0]} {p[1]}" for p in params)

    header = (
        "-- Reconstructed from Unity Catalog information_schema.routines/.parameters\n"
        "-- (real metadata from the live warehouse; DESCRIBE FUNCTION EXTENDED\n"
        "--  returns no body text on Databricks, so it is not used here).\n"
    )
    signature = f"CREATE FUNCTION {catalog}.{schema}.{name}({arg_list})\nRETURNS {returns}"
    if comment:
        signature += f"\nCOMMENT {comment!r}"
    if deterministic == "true":
        signature += "\nDETERMINISTIC"
    if language:
        signature += f"\nLANGUAGE {language}"

    if definition:
        available = True
        body = f"RETURN {definition}" if (body_kind or "").upper() == "SQL" else f"AS $$\n{definition}\n$$"
        source = f"{header}{signature}\n{body}"
    else:
        available = False
        source = (
            f"{header}{signature}\n"
            f"-- routine_body = {body_kind!r}: Unity Catalog returned no routine_definition\n"
            f"-- for this function, so its body is genuinely not available here.\n"
            f"-- Nothing is being substituted for it."
        )
    return {
        "catalog": catalog,
        "schema": schema,
        "name": name,
        "type": routine_type,
        "source": source,
        "source_available": available,
    }

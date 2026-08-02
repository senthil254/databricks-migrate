"""Real connector for the Redshift source system — G3.1 explore-only scope.

Every function here runs a real query against the live cluster configured
in backend/.env. No mocking, no synthetic data — see MEMORY.md's 2026-08-01
"G3 rejected, rebuilt" entry for how this cluster's real object inventory
was discovered.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import redshift_connector

from ..redact import redact


class ConnectorError(RuntimeError):
    """Raised for connection/query failures. Message is pre-redacted."""


def _connect():
    try:
        return redshift_connector.connect(
            host=os.environ["REDSHIFT_HOST"],
            port=int(os.environ["REDSHIFT_PORT"]),
            database=os.environ["REDSHIFT_DATABASE"],
            user=os.environ["REDSHIFT_USER"],
            password=os.environ["REDSHIFT_PASSWORD"],
            timeout=15,
        )
    except KeyError as exc:
        raise ConnectorError(f"missing required env var: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        # redshift_connector exceptions can embed host/user in their message;
        # redact before it ever reaches an API response or log line.
        raise ConnectorError(redact(str(exc))) from exc


@dataclass
class Database:
    name: str


@dataclass
class Schema:
    name: str


@dataclass
class TableRef:
    schema: str
    name: str
    type: str  # "table" | "view"


@dataclass
class Column:
    name: str
    data_type: str
    ordinal: int


@dataclass
class Routine:
    schema: str
    name: str
    type: str  # "FUNCTION" | "PROCEDURE"


def list_databases() -> list[Database]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY 1")
        return [Database(name=r[0]) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(redact(str(exc))) from exc
    finally:
        conn.close()


def list_schemas() -> list[Schema]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT table_schema FROM information_schema.tables "
            "WHERE table_schema NOT IN ('information_schema','pg_catalog','pg_internal') "
            "ORDER BY 1"
        )
        return [Schema(name=r[0]) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(redact(str(exc))) from exc
    finally:
        conn.close()


def list_tables(schema: str) -> list[TableRef]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT table_name, table_type FROM information_schema.tables "
            "WHERE table_schema = %s ORDER BY 1",
            (schema,),
        )
        return [
            TableRef(schema=schema, name=r[0], type="view" if r[1] == "VIEW" else "table")
            for r in cur.fetchall()
        ]
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(redact(str(exc))) from exc
    finally:
        conn.close()


def list_columns(schema: str, table: str) -> list[Column]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT column_name, data_type, ordinal_position FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
            (schema, table),
        )
        return [Column(name=r[0], data_type=r[1], ordinal=r[2]) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(redact(str(exc))) from exc
    finally:
        conn.close()


def list_routines(schema: str) -> list[Routine]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT routine_schema, routine_name, routine_type FROM information_schema.routines "
            "WHERE routine_schema = %s ORDER BY 2",
            (schema,),
        )
        return [Routine(schema=r[0], name=r[1], type=r[2]) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(redact(str(exc))) from exc
    finally:
        conn.close()


def get_table_ddl(schema: str, table: str) -> str:
    """Real Redshift-specific DDL via SHOW TABLE — includes ENCODE/DISTSTYLE/
    SORTKEY clauses a transpiler genuinely has to handle, not a generic
    reconstruction from information_schema."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(f"SHOW TABLE {_ident(schema)}.{_ident(table)}")
        rows = cur.fetchall()
        return "\n".join(r[0] for r in rows)
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(redact(str(exc))) from exc
    finally:
        conn.close()


def get_procedure_ddl(schema: str, name: str) -> str:
    """SHOW PROCEDURE works directly in this Redshift version (unlike
    SHOW FUNCTION, which doesn't exist here — see get_function_ddl)."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(f"SHOW PROCEDURE {_ident(schema)}.{_ident(name)}")
        rows = cur.fetchall()
        return "\n".join(r[0] for r in rows)
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(redact(str(exc))) from exc
    finally:
        conn.close()


def get_function_ddl(schema: str, name: str) -> str:
    """`SHOW FUNCTION` is not a real statement in this Redshift version
    (confirmed live 2026-08-01 — parser rejects it immediately after the
    keyword). Reconstruct CREATE FUNCTION from pg_proc + information_schema
    instead, which genuinely exist and were used to verify this project's
    own real functions."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT p.prosrc, l.lanname FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace "
            "JOIN pg_language l ON l.oid = p.prolang "
            "WHERE n.nspname = %s AND p.proname = %s",
            (schema, name),
        )
        row = cur.fetchone()
        if row is None:
            raise ConnectorError(f"function not found: {schema}.{name}")
        body, language = row

        cur.execute(
            "SELECT parameter_name, data_type, ordinal_position FROM information_schema.parameters "
            "WHERE specific_schema = %s AND specific_name LIKE %s ORDER BY ordinal_position",
            (schema, f"{name}_%"),
        )
        params = [(r[0], r[1]) for r in cur.fetchall()]

        cur.execute(
            "SELECT data_type FROM information_schema.routines "
            "WHERE routine_schema = %s AND routine_name = %s AND routine_type = 'FUNCTION'",
            (schema, name),
        )
        ret_row = cur.fetchone()
        return_type = ret_row[0] if ret_row else "unknown"

        arg_list = ", ".join(f"{pname} {ptype}" for pname, ptype in params)
        return (
            f"CREATE OR REPLACE FUNCTION {schema}.{name}({arg_list})\n"
            f"RETURNS {return_type}\n"
            f"AS $$ {body.strip()} $$\n"
            f"LANGUAGE {language}"
        )
    except ConnectorError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(redact(str(exc))) from exc
    finally:
        conn.close()


def preview_table(schema: str, table: str, limit: int = 10) -> tuple[list[str], list[tuple]]:
    """Real SELECT * ... LIMIT against the source Redshift cluster. Returns
    (columns, rows) — columns come from cursor.description, not fabricated.
    Identifier-guarded schema/table via _ident(); limit is bound as a real
    query param since psycopg/redshift_connector support that for LIMIT."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM {_ident(schema)}.{_ident(table)} LIMIT %s",
            (limit,),
        )
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return columns, [tuple(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(redact(str(exc))) from exc
    finally:
        conn.close()


def _ident(name: str) -> str:
    """Guard for names interpolated into SHOW statements — Redshift's SHOW
    TABLE/PROCEDURE don't support parameter binding. Only ever called with
    names that came from a prior list_*() call."""
    if not name.replace("_", "").isalnum():
        raise ConnectorError(f"invalid identifier: {name!r}")
    return name

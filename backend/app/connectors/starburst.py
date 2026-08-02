"""Real connector for the Starburst (Trino/Galaxy) source system — G3.1
explore-only scope.

Every function runs a real query against the live catalog configured in
backend/.env. Key real finding this connector encodes (see MEMORY.md):
Starburst Galaxy UDFs are NOT discoverable per-catalog via
information_schema.routines (that table doesn't exist there) — persistent
UDFs live specifically in the `galaxy.functions` catalog/schema, and
SHOW FUNCTIONS FROM galaxy.functions is the only reliable way to list them.

Correction (G18, verified live): an earlier claim in this module — that
"Trino has no SHOW CREATE FUNCTION" — is WRONG for this server.
`SHOW CREATE FUNCTION galaxy.functions.<name>` returns the complete real
function body. See get_udf_ddl. (Passing a signature, e.g. `...f(double)`,
IS a real SYNTAX_ERROR — pass the bare qualified name.)
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from trino.auth import BasicAuthentication
from trino.dbapi import connect

from ..redact import redact


class ConnectorError(RuntimeError):
    pass


def _connect(catalog: str | None = None, schema: str | None = None):
    try:
        return connect(
            host=os.environ["STARBURST_HOST"],
            port=int(os.environ["STARBURST_PORT"]),
            http_scheme="https",
            auth=BasicAuthentication(os.environ["STARBURST_USER"], os.environ["STARBURST_PASSWORD"]),
            catalog=catalog,
            schema=schema,
        )
    except KeyError as exc:
        raise ConnectorError(f"missing required env var: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(redact(str(exc))) from exc


@dataclass
class Catalog:
    name: str


@dataclass
class Schema:
    name: str


@dataclass
class TableRef:
    catalog: str
    schema: str
    name: str
    type: str = "table"


@dataclass
class Column:
    name: str
    data_type: str


@dataclass
class Udf:
    name: str
    return_type: str
    argument_types: str


def list_catalogs() -> list[Catalog]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SHOW CATALOGS")
        return [Catalog(name=r[0]) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(redact(str(exc))) from exc


def list_schemas(catalog: str) -> list[Schema]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(f"SHOW SCHEMAS FROM {_ident(catalog)}")
        return [Schema(name=r[0]) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(redact(str(exc))) from exc


def list_tables(catalog: str, schema: str) -> list[TableRef]:
    """Uses information_schema.tables (not SHOW TABLES) specifically to get
    the real table_type column — SHOW TABLES cannot distinguish a real
    table from a real view, which caused a real bug: G7's DDL-custom path
    needs the correct object_type (table vs view) to route to the right
    translator function, and a view sent through as "table" produces a
    real Trino error ("is a view, not a table")."""
    conn = _connect(catalog=catalog, schema=schema)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT table_name, table_type FROM information_schema.tables "
            "WHERE table_schema = ? ORDER BY 1",
            (schema,),
        )
        return [
            TableRef(catalog=catalog, schema=schema, name=r[0], type="view" if r[1] == "VIEW" else "table")
            for r in cur.fetchall()
        ]
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(redact(str(exc))) from exc


def list_columns(catalog: str, schema: str, table: str) -> list[Column]:
    conn = _connect(catalog=catalog, schema=schema)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
            (schema, table),
        )
        return [Column(name=r[0], data_type=r[1]) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(redact(str(exc))) from exc


def list_udfs() -> list[Udf]:
    """Persistent UDFs live only in galaxy.functions — see module docstring."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SHOW FUNCTIONS FROM galaxy.functions")
        rows = cur.fetchall()
        # SHOW FUNCTIONS columns: Function, Return Type, Argument Types, ...
        return [Udf(name=r[0], return_type=r[1], argument_types=r[2]) for r in rows]
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(redact(str(exc))) from exc


def get_table_ddl(catalog: str, schema: str, table: str) -> str:
    """Real Iceberg/Delta DDL via SHOW CREATE TABLE — can be slow (~30s
    observed live) since Trino resolves real storage metadata; callers
    should use a generous timeout, not the default connect() timeout."""
    conn = _connect(catalog=catalog, schema=schema)
    try:
        cur = conn.cursor()
        cur.execute(f"SHOW CREATE TABLE {_ident(catalog)}.{_ident(schema)}.{_ident(table)}")
        rows = cur.fetchall()
        return "\n".join(r[0] for r in rows)
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(redact(str(exc))) from exc


def get_udf_ddl(name: str) -> str:
    """Real UDF source via SHOW CREATE FUNCTION galaxy.functions.<name>.

    G18 correction: this project previously asserted "Trino has no SHOW
    CREATE FUNCTION" and returned a fabricated stub containing
    "-- body not recoverable via SHOW FUNCTIONS". That claim is FALSE
    against this server — SHOW CREATE FUNCTION returns the complete real
    body, verified live. The reconstruction path below is kept ONLY as a
    genuine fallback for when that statement really fails, and when it is
    used the returned text says so explicitly.

    Note: the name must be passed UNQUALIFIED by signature — SHOW CREATE
    FUNCTION galaxy.functions.f(double) is a real SYNTAX_ERROR on this
    server; only the name form works.
    """
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(f"SHOW CREATE FUNCTION galaxy.functions.{_ident(name)}")
        rows = cur.fetchall()
        if rows:
            # SHOW CREATE FUNCTION's first column is the real CREATE
            # FUNCTION text; one row per overload of the same name.
            ddl = "\n\n".join(str(r[0]) for r in rows if r and r[0])
            if ddl.strip():
                return ddl
    except ConnectorError:
        raise
    except Exception:  # noqa: BLE001
        # Fall through to the reconstruction path below — deliberately not
        # re-raised, because a real fallback exists. Failures of the
        # fallback itself DO raise.
        pass

    return _reconstruct_udf_ddl(name)


def _reconstruct_udf_ddl(name: str) -> str:
    """Fallback only: signature-level reconstruction from SHOW FUNCTIONS.
    Used when SHOW CREATE FUNCTION genuinely fails; the returned text is
    labelled as reconstructed so it can never be mistaken for real source."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SHOW FUNCTIONS FROM galaxy.functions")
        row = next((r for r in cur.fetchall() if r[0] == name), None)
        if row is None:
            raise ConnectorError(f"udf not found in galaxy.functions: {name}")
        return_type, argument_types = row[1], row[2]
        return (
            "-- RECONSTRUCTED signature only: SHOW CREATE FUNCTION failed for this\n"
            "-- function, so only SHOW FUNCTIONS metadata was available. This is NOT\n"
            "-- the real source text.\n"
            f"CREATE FUNCTION galaxy.functions.{name}({argument_types})\n"
            f"RETURNS {return_type}"
        )
    except ConnectorError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(redact(str(exc))) from exc


def get_view_ddl(catalog: str, schema: str, name: str) -> str:
    """Real view DDL via SHOW CREATE VIEW — same shape as get_table_ddl.
    G7 addition (2026-08-01)."""
    conn = _connect(catalog=catalog, schema=schema)
    try:
        cur = conn.cursor()
        cur.execute(f"SHOW CREATE VIEW {_ident(catalog)}.{_ident(schema)}.{_ident(name)}")
        rows = cur.fetchall()
        return "\n".join(r[0] for r in rows)
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(redact(str(exc))) from exc


def read_table_rows(catalog: str, schema: str, table: str, columns: list[str]) -> list[tuple]:
    """Real row read for the G7 custom data-copy path. `columns` must
    already be real, known-good column names (e.g. from list_columns()) —
    every identifier here, including each column name, is guarded via
    _ident() before being interpolated into the SELECT, matching every
    other identifier-interpolating function in this file. Unlike the rest
    of this file today, this function closes its connection in a `finally`
    — a deliberate G7 improvement, not applied retroactively to the older
    functions above to keep this change additive-only."""
    conn = _connect(catalog=catalog, schema=schema)
    try:
        cur = conn.cursor()
        col_list_sql = ", ".join(_ident(c) for c in columns)
        cur.execute(
            f"SELECT {col_list_sql} FROM {_ident(catalog)}.{_ident(schema)}.{_ident(table)}"
        )
        return [tuple(r) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(redact(str(exc))) from exc
    finally:
        conn.close()


def preview_table(catalog: str, schema: str, table: str, limit: int = 10) -> tuple[list[str], list[tuple]]:
    """Real SELECT * ... LIMIT against the source Trino/Galaxy catalog.
    Returns (columns, rows). Trino's driver doesn't reliably bind LIMIT ?,
    so limit is validated as a small positive int and interpolated
    directly (never attacker-controlled — clamped here, not trusted)."""
    limit = min(max(int(limit), 1), 1000)
    conn = _connect(catalog=catalog, schema=schema)
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM {_ident(catalog)}.{_ident(schema)}.{_ident(table)} LIMIT {limit}"
        )
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return columns, [tuple(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(redact(str(exc))) from exc
    finally:
        conn.close()


def _ident(name: str) -> str:
    """Minimal identifier guard for names interpolated into SHOW ... FROM
    statements, which Trino does not support parameter binding for. Explore
    endpoints only ever pass catalog/schema names that themselves came from
    a prior list_catalogs()/list_schemas() call, never raw user text."""
    if not name.replace("_", "").replace("-", "").isalnum():
        raise ConnectorError(f"invalid identifier: {name!r}")
    return name

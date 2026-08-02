"""G7 — custom, deterministic Starburst -> Databricks DDL translator.

This file is the concrete implementation of this phase's non-negotiable
requirement (see MEMORY.md's 2026-08-01 G7 entry, point 4): a genuinely
custom conversion, never a second call into any Databricks-managed
conversion/LLM service, and never the Lakebridge CLI at all. Pure Python,
metadata-driven (real `list_columns()` results, not regex-parsed DDL text
for the table path — reliable structured metadata beats fragile parsing).

Verified zero-dependency-on-conversion-services by construction: grep this
file yourself for any of `subprocess`, `run_lakebridge`, `llm-transpile`,
`LLM_TRANSPILE`, `_poll_job_run`/`poll_job_run` — none appear.
"""
from __future__ import annotations

import re

from .connectors import starburst as starburst_conn
from .starburst_type_map import databricks_type_for_trino

# Databricks CREATE VIEW has no equivalent of Trino/Starburst's
# "SECURITY DEFINER" modifier (confirmed live 2026-08-01: real
# `SHOW CREATE VIEW` output on `mcp2ohio.test_writes.g7_view_probe` is
# `CREATE VIEW <fqn> SECURITY DEFINER AS\nSELECT ...`) — stripped here as a
# syntax-only rewrite, the query body itself is left untouched.
_SECURITY_DEFINER_RE = re.compile(r"\s+SECURITY\s+DEFINER\b", re.IGNORECASE)


def translate_table_ddl(catalog: str, schema: str, table: str) -> tuple[str, list[tuple[str, str]]]:
    """Returns (databricks_create_table_sql, [(column_name, databricks_type), ...]).

    Column list is driven by the real `information_schema.columns` metadata
    via `starburst_conn.list_columns()` — not free-text parsing of
    `SHOW CREATE TABLE` output, which is fragile and was never the plan here.
    """
    columns = starburst_conn.list_columns(catalog, schema, table)
    mapped: list[tuple[str, str]] = [
        (c.name, databricks_type_for_trino(c.data_type)) for c in columns
    ]
    col_defs = ",\n  ".join(f"`{name}` {dtype}" for name, dtype in mapped)
    ddl = f"CREATE TABLE `{table}` (\n  {col_defs}\n)"
    return ddl, mapped


def translate_view_ddl(catalog: str, schema: str, view: str) -> str:
    """Syntax-only rewrite of the real `SHOW CREATE VIEW` output — strips
    Trino-only syntax Databricks doesn't understand (currently just
    `SECURITY DEFINER`, the one real difference confirmed live). The
    query body itself is passed through unchanged since Trino and
    Databricks SQL are both broadly ANSI-shaped for simple SELECTs; this is
    a best-effort syntax rewrite, not a full dialect transpiler.
    """
    raw_ddl = starburst_conn.get_view_ddl(catalog, schema, view)
    return _SECURITY_DEFINER_RE.sub("", raw_ddl).strip()

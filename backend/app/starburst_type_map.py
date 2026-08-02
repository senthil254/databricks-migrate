"""G7 — deterministic Trino/Starburst -> Databricks type mapping.

Real shapes confirmed live (2026-08-01) against the live `mcp2ohio` Starburst
catalog (see MEMORY.md's G7 entry) via a throwaway probe table
(`mcp2ohio.test_writes.g7_type_probe`, created then dropped in the same
session — never left behind).

Note: a second real fixture, `mcp2ohio.test_writes.g7_view_probe`, was also
created for confirming SHOW CREATE VIEW's real shape (see
starburst_ddl_translator.py) and is **left in place** as a persistent
fixture for the new live view-DDL test in test_api.py — same convention
already used for other persistent real objects this project's tests rely
on (e.g. Redshift's `venue`), not a throwaway.

Type shapes confirmed via the table probe:

    CREATE TABLE mcp2ohio.test_writes.g7_type_probe (
       id integer,
       name varchar(50),
       amount decimal(10, 2),
       created_at timestamp,
       created_tz timestamp with time zone,
       is_active boolean
    )

confirmed via SHOW CREATE TABLE and, separately, via
`information_schema.columns` (what `starburst_ddl_translator.py` actually
drives off of, per the plan):

    id           -> integer
    name         -> varchar            (NOTE: Iceberg on this live catalog
                                          silently drops the varchar(50)
                                          length constraint entirely — the
                                          real stored/reported type is bare
                                          "varchar", not "varchar(50)". The
                                          mapper below still defensively
                                          handles a parenthesized length in
                                          case a different table/connector
                                          ever reports one.)
    amount       -> decimal(10,2)      (information_schema.columns form,
                                          no space; SHOW CREATE TABLE prints
                                          "decimal(10, 2)" with a space — the
                                          mapper tolerates both)
    created_at   -> timestamp(6)       (real precision digit present)
    created_tz   -> timestamp(6) with time zone
    is_active    -> boolean

This is intentionally separate from `databricks_target.py`'s
`_REDSHIFT_TO_DATABRICKS_TYPE`/`databricks_type_for` — different source
system, different real type-string shapes — never merged into one dict.
"""
from __future__ import annotations

import re

_TRINO_TO_DATABRICKS_TYPE = {
    "varchar": "STRING",
    "char": "STRING",
    "integer": "INT",
    "int": "INT",
    "bigint": "BIGINT",
    "smallint": "SMALLINT",
    "tinyint": "TINYINT",
    "double": "DOUBLE",
    "real": "FLOAT",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "timestamp": "TIMESTAMP",
    "timestamp with time zone": "TIMESTAMP",
}

# Matches "decimal(10,2)" (information_schema.columns form) and
# "decimal(10, 2)" (SHOW CREATE TABLE form) — both confirmed live.
_DECIMAL_RE = re.compile(r"^decimal\(\s*(\d+)\s*,\s*(\d+)\s*\)$")

# Strips a parenthesized precision/length, e.g. "varchar(50)" -> "varchar",
# "timestamp(6)" -> "timestamp", "timestamp(6) with time zone" ->
# "timestamp with time zone" — confirmed shapes above. Decimal is handled
# separately above since precision+scale must be preserved, not stripped.
_PRECISION_STRIP_RE = re.compile(r"\(\s*\d+\s*\)")


def databricks_type_for_trino(source_type: str) -> str:
    """Best-effort, deterministic type mapping for the custom Starburst DDL
    path — this project's own logic, no Lakebridge/LLM job involved (see
    starburst_ddl_translator.py's module docstring for the "no conversion
    service" requirement this exists to satisfy).

    Honest fallback: any type not explicitly known (array/row/map and any
    other complex/nested Trino type) maps to STRING rather than guessing —
    documented, not silently wrong, matching this project's existing
    Redshift `databricks_type_for` convention.
    """
    normalized = source_type.strip().lower()

    decimal_match = _DECIMAL_RE.match(normalized)
    if decimal_match:
        precision, scale = decimal_match.group(1), decimal_match.group(2)
        return f"DECIMAL({precision},{scale})"
    if normalized == "decimal":
        # Bare "decimal" with no precision/scale reported — Databricks
        # DECIMAL requires both; fall back to its own max-safe default
        # rather than guessing at data-specific precision.
        return "DECIMAL(38,18)"

    stripped = _PRECISION_STRIP_RE.sub("", normalized).strip()
    return _TRINO_TO_DATABRICKS_TYPE.get(stripped, "STRING")

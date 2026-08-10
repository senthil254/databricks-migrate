"""G6 backend — natural-language chat layer: instruction -> reviewable plan
-> confirm -> execute via the *same* real adapter functions G1-G5 already
proved safe. See PLAN.md's G6 row and CLAUDE.md's ordering rule (chat only
gains real execution power over things already proven safe).

Design decision on NL parsing (recorded here, not just in a commit
message): this project already runs one real Databricks LLM job — the
"Switch" job backing `migrate.migrate_starburst_ddl`'s `llm-transpile`
path (see MEMORY.md's 2026-08-01 G3.2 entry). It was considered and
rejected for chat intent parsing: it's a real code-transpilation model
with a fixed SQL-in/SQL-out, Workspace-folder job contract, not a
general-purpose chat/intent classifier, and there is no verified way to
hand it a free-text instruction and get back a structured
`{action, args}` decision. Inventing that contract would itself be the
"unverified capability" CLAUDE.md prohibits. Instead this module does
honest, deterministic pattern matching: a small fixed verb vocabulary
(migrate/transpile/convert, copy+data, reconcile/validate,
batch-migrate+schema) plus matching against the REAL current object
inventory fetched live via the existing G3.1 `redshift_conn` connector —
never a hardcoded or invented object list. If a match isn't unambiguous,
`parse_instruction` refuses rather than guessing (`understood: false`).

Every real action this module can request already exists end-to-end from
G1-G5 — this module never builds SQL, never calls the Lakebridge CLI
itself, and never bypasses `_ident()`; it only ever calls
`migrate.migrate_redshift_ddl`, `migrate.copy_redshift_table_data`,
`migrate.build_redshift_schema_batch_items` + `migrate.start_batch`, or
dispatches a `reconcile` run through the exact same
`RunStore.create` + `run_command_async` pair `main.py`'s own
`POST /runs/reconcile` uses. No new Lakebridge invocation shape, no new
connector method, no second implementation of "how to migrate a table."

G8 addition (2026-08-01): Starburst is now wired in too, resolved live
against `starburst_conn.list_catalogs/list_schemas/list_tables` (three
levels, not Redshift's two) with the same "refuse rather than guess" rule
— extended here to cover ambiguity *across* catalogs/schemas, not just
name collisions within one. Resolved Starburst objects are dispatched
ONLY to G7's fast deterministic path (`migrate.migrate_starburst_ddl_custom`,
`migrate.copy_starburst_table_data`) — never to `migrate.migrate_starburst_ddl`
(the older `llm-transpile` path). That distinction matters enough that this
module deliberately does NOT reuse `migrate.start_batch`/`run_batch` for a
Starburst whole-schema batch: `migrate._run_single_batch_item` still
dispatches Starburst DDL items to the old LLM path, so reusing it here
would silently reintroduce exactly what G7 was built to avoid. Instead
`migrate.start_starburst_schema_batch`/`migrate.run_starburst_schema_batch`
(G9: relocated here from this module — see the comment further down) are
a small, self-contained mirror of that orchestration loop built only from
real store objects (`batch_store`, `migrate.migration_store`) and G7's two
custom functions — the same functions the new G9
`POST /migrate/starburst/catalog/{catalog}/schema/{schema}/batch` REST
route in main.py now also calls.

G9 addition: an open-ended "ask a real data question about Databricks"
fallback, tried only after every structured verb above has failed to
match. Deliberately NOT an MCP server and NOT a free-form LLM call — this
project already rejected inventing unverified capability shape (see the
NL-parsing decision above). Instead it's the same honest, deterministic
pattern this whole module already uses: a small explicit keyword/phrase
set (`_DATABRICKS_KEYWORD_RE` / `_DATA_QUESTION_RE`) plus resolution
against the REAL live Unity Catalog inventory via
`connectors/databricks_browse.py` (`list_catalogs/list_schemas/
list_tables`), mirroring `_find_matching_starburst_object`'s three-level
resolution and its "refuse rather than guess" contract exactly. Resolved
questions execute via `databricks_target.preview_table` (the safe path,
preferred whenever a real object can be resolved). A literal `select ...`
fragment is instead passed to `databricks_target.execute()`, but ONLY
after `_is_safe_select_fragment` rejects anything that isn't a single
plain SELECT (no `;`-chained statements, no DML/DDL keywords anywhere) —
matching CLAUDE.md's "never run unsanitised SQL" rule.
"""
from __future__ import annotations

import os
import re
import time
import uuid

from . import databricks_mcp_client, databricks_target, llm_planner, migrate
from .connectors import databricks_browse
from .connectors import redshift as redshift_conn
from .connectors import starburst as starburst_conn
from .connectors.databricks_browse import BrowseError as DatabricksBrowseError
from .databricks_mcp_client import DatabricksMCPError
from .connectors.redshift import ConnectorError as RedshiftError
from .connectors.starburst import ConnectorError as StarburstError
from .executor import run_command_async
from .models import store

# A chat plan is a *proposal*, never part of the audit trail — deliberately
# NOT a new persistent store (per this task's own scope note: reuse
# Run/Migration/Batch for anything that's actually executed). Held only
# long enough for a client to review and then either re-POST the full plan
# body or reference it by id in the same process lifetime.
_PLAN_CACHE: dict[str, dict] = {}

# G12: the G10/G11 Databricks Managed MCP fallback (below, in
# `is_databricks_question`) is disabled by default. Real round trips have
# measured 78-120s+ and shown occasional transient 500s in this
# environment (see MEMORY.md's 2026-08-01 G10/G10-follow-up entries) — too
# slow/unreliable for interactive chat. Kept in the codebase, not deleted:
# flip this back to True once acceptable latency/reliability is confirmed.
# This is a G12 decision, not a removal of the feature.
DATABRICKS_MCP_FALLBACK_ENABLED = False

DEFAULT_SCHEMA = "public"

_OBJECT_TYPE_WORDS = {
    "views": "view",
    "view": "view",
    "functions": "function",
    "function": "function",
    "procedures": "procedure",
    "procedure": "procedure",
    "proc": "procedure",
    "tables": "table",
    "table": "table",
}

_RECONCILE_RE = re.compile(r"\b(reconcile|validate|verify)\b", re.I)
_SCHEMA_BATCH_RE = re.compile(
    r"\b(batch[- ]?migrate|migrate)\b.{0,40}\b(whole|entire|all)\b.{0,20}\bschema\b"
    r"|\bbatch[- ]?migrate\b.{0,20}\bschema\b",
    re.I,
)
_DATA_COPY_RE = re.compile(
    r"\bcopy\b.{0,20}\bdata\b|\bdata\b.{0,20}\bcopy\b|\bcopy\b.{0,10}\brows\b", re.I
)
_MIGRATE_RE = re.compile(r"\b(migrate|transpile|convert)\b", re.I)
# G16 Phase B — combined create+copy in one instruction, e.g. "migrate the
# customers table and its data" / "migrate table X and data". Deliberately
# checked BEFORE _DATA_COPY_RE/_MIGRATE_RE below so a combined phrasing
# routes to the new migrate_table_and_data intent instead of being caught by
# either single-purpose branch first — mirrors the ordering comment already
# on _PREVIEW_RE for the same reason.
_MIGRATE_AND_DATA_RE = re.compile(
    r"\b(migrate|transpile|convert)\b.{0,120}\b(and|with|plus)\b.{0,20}\b(its\s+)?data\b", re.I
)
# G12 — preview real SOURCE Starburst/Redshift table rows (no migration, no
# copy). Deliberately checked AFTER _DATA_COPY_RE/_MIGRATE_RE in
# parse_instruction so "copy the data for table X"/"migrate table X" still
# route to their existing branches first; this regex additionally excludes
# copy/migrate keywords itself as a second, belt-and-suspenders guard.
_PREVIEW_RE = re.compile(
    r"\b(preview|show|query|display)\b(?!.{0,60}\b(copy|migrate|transpile|convert)\b)"
    r".{0,60}\b(data|rows|table)\b",
    re.I,
)
_SCHEMA_NAME_RE = re.compile(r"\bschema\s+([a-zA-Z_][a-zA-Z0-9_]*)\b", re.I)
_STARBURST_KEYWORD_RE = re.compile(r"\b(starburst|trino)\b", re.I)
_CATALOG_NAME_RE = re.compile(r"\bcatalog\s+([a-zA-Z_][a-zA-Z0-9_]*)\b", re.I)
_QUALIFIED_NAME_RE = re.compile(
    r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b"
)
# Two-part `schema.table`, the Redshift form. The lookarounds stop it matching
# inside a three-part Starburst name (catalog.schema.table), which must stay the
# job of _QUALIFIED_NAME_RE alone.
_TWO_PART_NAME_RE = re.compile(
    r"(?<![\w.])([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)(?![\w.])"
)

# G9 — Databricks data-question fallback. Kept a small, explicit, documented
# set on purpose (no free-form LLM classification, see module docstring).
_DATABRICKS_KEYWORD_RE = re.compile(r"\bdatabricks\b", re.I)
_DATA_QUESTION_RE = re.compile(
    r"what'?s in\b|\bshow me\b|\bhow many rows\b|\bpreview\b|\bselect\s", re.I
)
_SELECT_FRAGMENT_RE = re.compile(r"\bselect\b.*", re.I | re.S)
_SQL_STATEMENT_SEPARATOR_RE = re.compile(r";\s*\S")
_SQL_FORBIDDEN_KEYWORDS_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|merge|exec|execute)\b", re.I
)


def _extract_schema(text: str) -> str:
    m = _SCHEMA_NAME_RE.search(text)
    if m:
        return m.group(1)
    # `schema.table` is the ordinary way people write a Redshift object, but only
    # the phrase "schema X" used to be understood — so "migrate
    # demo_fast_test.customers" silently searched schema 'public' and refused
    # with a message naming a schema the user never mentioned. Confusing, and
    # wrong in a way that looked like the object didn't exist.
    two = _TWO_PART_NAME_RE.search(text)
    if two:
        return two.group(1)
    return DEFAULT_SCHEMA


def _extract_object_type_hint(text: str) -> str | None:
    for word, otype in _OBJECT_TYPE_WORDS.items():
        if re.search(rf"\b{word}\b", text, re.I):
            return otype
    return None


def _find_matching_object(text: str, schema: str) -> tuple[str, str] | None:
    """Returns (object_type, name) for the one real table/view/routine in
    `schema` whose name appears as a whole word in `text`, or None if zero
    or more than one match. Real inventory only, fetched live — never an
    invented or hardcoded name."""
    try:
        tables = redshift_conn.list_tables(schema)
        routines = redshift_conn.list_routines(schema)
    except RedshiftError:
        return None
    candidates: list[tuple[str, str]] = [(t.type, t.name) for t in tables]
    candidates += [
        ("function" if r.type == "FUNCTION" else "procedure", r.name) for r in routines
    ]
    # Longest names first so "venue_sales_summary" wins over "venue" when
    # both appear as whole-word substrings of the instruction.
    candidates.sort(key=lambda c: len(c[1]), reverse=True)
    matches = [c for c in candidates if re.search(rf"\b{re.escape(c[1])}\b", text, re.I)]
    if len(matches) != 1:
        return None
    return matches[0]


def _find_matching_starburst_object(text: str) -> tuple[str, object]:
    """Starburst mirror of `_find_matching_object`, extended for the extra
    (catalog) level. Returns one of:
      ("ok", (catalog, schema, object_type, name))
      ("ambiguous", [(catalog, schema, object_type, name), ...])  -- 2+ real
          matches (e.g. same table name in two catalogs/schemas, or an
          explicit qualifier that still leaves more than one real match)
      ("none", None)          -- no real object in `text` at all
      ("error", "<message>")  -- could not reach Starburst to check

    Real inventory only, fetched live via list_catalogs/list_schemas/
    list_tables — never an invented or hardcoded name, matching
    `_find_matching_object`'s own contract.
    """
    qualified = _QUALIFIED_NAME_RE.search(text)
    catalog_hint = None
    schema_hint = None
    if qualified:
        catalog_hint, schema_hint = qualified.group(1), qualified.group(2)
    else:
        m = _CATALOG_NAME_RE.search(text)
        if m:
            catalog_hint = m.group(1)
        m2 = _SCHEMA_NAME_RE.search(text)
        if m2:
            schema_hint = m2.group(1)

    try:
        catalogs = starburst_conn.list_catalogs()
    except StarburstError as exc:
        return ("error", f"could not reach real starburst to list catalogs: {exc}")

    candidates: list[tuple[str, str, str, str]] = []
    for c in catalogs:
        if catalog_hint and c.name.lower() != catalog_hint.lower():
            continue
        try:
            schemas = starburst_conn.list_schemas(c.name)
        except StarburstError:
            continue
        for s in schemas:
            if schema_hint and s.name.lower() != schema_hint.lower():
                continue
            try:
                tables = starburst_conn.list_tables(c.name, s.name)
            except StarburstError:
                continue
            for t in tables:
                candidates.append((c.name, s.name, t.type, t.name))

    # Longest names first so a longer real table name wins over a shorter
    # one that also happens to appear as a whole-word substring.
    candidates.sort(key=lambda c: len(c[3]), reverse=True)
    matches = [c for c in candidates if re.search(rf"\b{re.escape(c[3])}\b", text, re.I)]
    if not matches:
        return ("none", None)
    top_len = len(matches[0][3])
    top_matches = [m for m in matches if len(m[3]) == top_len]
    if len(top_matches) > 1:
        return ("ambiguous", top_matches)
    return ("ok", top_matches[0])


def _find_matching_databricks_table(text: str) -> tuple[str, object]:
    """Databricks mirror of `_find_matching_starburst_object`, resolved
    against the REAL migration target's Unity Catalog via
    `connectors/databricks_browse.py` (catalog/schema/table, three levels,
    same shape as Starburst's). Returns one of:
      ("ok", (catalog, schema, name))
      ("ambiguous", [(catalog, schema, name), ...])
      ("none", None)
      ("error", "<message>")

    Real inventory only — never an invented or hardcoded name, and refuses
    rather than guesses on ambiguity, matching this module's existing
    contract exactly.
    """
    qualified = _QUALIFIED_NAME_RE.search(text)
    catalog_hint = None
    schema_hint = None
    if qualified:
        catalog_hint, schema_hint = qualified.group(1), qualified.group(2)
    else:
        m = _CATALOG_NAME_RE.search(text)
        if m:
            catalog_hint = m.group(1)
        m2 = _SCHEMA_NAME_RE.search(text)
        if m2:
            schema_hint = m2.group(1)

    try:
        catalogs = databricks_browse.list_catalogs()
    except DatabricksBrowseError as exc:
        return ("error", f"could not reach real databricks to list catalogs: {exc}")

    candidates: list[tuple[str, str, str]] = []
    for cat in catalogs:
        if catalog_hint and cat.lower() != catalog_hint.lower():
            continue
        try:
            schemas = databricks_browse.list_schemas(cat)
        except DatabricksBrowseError:
            continue
        for sch in schemas:
            if schema_hint and sch.lower() != schema_hint.lower():
                continue
            try:
                tables = databricks_browse.list_tables(cat, sch)
            except DatabricksBrowseError:
                continue
            for t in tables:
                candidates.append((cat, sch, t.name))

    # Longest names first so a longer real table name wins over a shorter
    # one that also happens to appear as a whole-word substring.
    candidates.sort(key=lambda c: len(c[2]), reverse=True)
    matches = [c for c in candidates if re.search(rf"\b{re.escape(c[2])}\b", text, re.I)]
    if not matches:
        return ("none", None)
    top_len = len(matches[0][2])
    top_matches = [m for m in matches if len(m[2]) == top_len]
    if len(top_matches) > 1:
        return ("ambiguous", top_matches)
    return ("ok", top_matches[0])


def _is_safe_select_fragment(sql: str) -> bool:
    """Only a single, plain SELECT is ever allowed through to
    `databricks_target.execute()` — matches CLAUDE.md's "never run
    unsanitised SQL" rule. Rejects anything with a second `;`-separated
    statement or any DML/DDL keyword anywhere in the text (not just at the
    start), erring toward refusal."""
    s = sql.strip()
    if not re.match(r"(?i)^select\b", s):
        return False
    if _SQL_STATEMENT_SEPARATOR_RE.search(s):
        return False
    if _SQL_FORBIDDEN_KEYWORDS_RE.search(s):
        return False
    return True


# `_run_starburst_schema_batch`/`_start_starburst_schema_batch` moved to
# `migrate.py` in G9 as `migrate.run_starburst_schema_batch` /
# `migrate.start_starburst_schema_batch`, so the new
# `POST /migrate/starburst/catalog/{catalog}/schema/{schema}/batch` REST
# route in main.py can call the exact same code this module exercises —
# see migrate.py's "G9 / relocated from chat.py (G8)" section for the full
# reasoning (still: never route through `migrate.start_batch`/`run_batch`,
# whose `_run_single_batch_item` still dispatches Starburst DDL to the old
# LLM path).


def parse_instruction(instruction: str) -> dict:
    """Returns a reviewable plan. NEVER executes anything.

    Understood shape:
      {"understood": True, "plan_id": ..., "action": {...}, "endpoint": "...",
       "explanation": "..."}
    Refused shape:
      {"understood": False, "reason": "..."}
    """
    text = (instruction or "").strip()
    if not text:
        return {"understood": False, "reason": "empty instruction"}
    # A three-part `catalog.schema.name` is itself a Starburst signal: Redshift
    # objects are addressed with two parts, and only Starburst has catalogs.
    # Requiring the literal word "starburst" meant the UI's own Starburst chips
    # ("migrate mcp2ohio.test_writes.X and its data") fell through to the
    # Redshift branch and failed against schema 'public' — a real defect hit in
    # the chat UI, not a hypothetical one.
    #
    # `explicit_starburst` is kept separate so a three-part name that matches no
    # real Starburst catalog can fall through to Redshift instead of hard-failing
    # with a Starburst-worded refusal.
    explicit_starburst = bool(_STARBURST_KEYWORD_RE.search(text))
    is_starburst = explicit_starburst or bool(_QUALIFIED_NAME_RE.search(text))

    if _RECONCILE_RE.search(text):
        action = {"kind": "reconcile"}
        return _make_plan(
            action,
            "POST /runs/reconcile",
            "Dispatches the real configured reconcile job (identical to the Runs tab's reconcile action).",
        )

    if _SCHEMA_BATCH_RE.search(text) and is_starburst:
        schema = _extract_schema(text)
        include_data = bool(re.search(r"\bdata\b", text, re.I))
        m = _CATALOG_NAME_RE.search(text)
        if not m:
            return {
                "understood": False,
                "reason": "a starburst whole-schema batch needs an explicit catalog (e.g. \"catalog analytics\") — three-level namespace, can't guess it",
            }
        catalog = m.group(1)
        try:
            real_catalogs = {c.name.lower() for c in starburst_conn.list_catalogs()}
            if catalog.lower() not in real_catalogs:
                return {"understood": False, "reason": f"no real starburst catalog named {catalog!r}"}
            real_schemas = {s.name.lower() for s in starburst_conn.list_schemas(catalog)}
            if schema.lower() not in real_schemas:
                return {
                    "understood": False,
                    "reason": f"no real schema {schema!r} in starburst catalog {catalog!r}",
                }
            tables = starburst_conn.list_tables(catalog, schema)
        except StarburstError as exc:
            return {
                "understood": False,
                "reason": f"could not enumerate real starburst {catalog}.{schema}: {exc}",
            }
        if not tables:
            return {
                "understood": False,
                "reason": f"no real objects found in starburst schema {catalog}.{schema}",
            }
        item_count = len(tables) + (sum(1 for t in tables if t.type == "table") if include_data else 0)
        action = {
            "kind": "migrate_starburst_schema_batch",
            "source_system": "starburst",
            "catalog": catalog,
            "schema": schema,
            "include_data": include_data,
            "item_count": item_count,
        }
        return _make_plan(
            action,
            f"chat-only: batch-migrates {len(tables)} real starburst objects in {catalog}.{schema} "
            f"via migrate_starburst_ddl_custom (+ copy_starburst_table_data for tables if include_data)",
            f"Batch-migrates all {item_count} real objects currently in starburst {catalog}.{schema} "
            "via G7's custom deterministic path (never llm-transpile).",
        )

    if _SCHEMA_BATCH_RE.search(text):
        schema = _extract_schema(text)
        include_data = bool(re.search(r"\bdata\b", text, re.I))
        try:
            items = migrate.build_redshift_schema_batch_items(schema, include_data=include_data)
        except RedshiftError as exc:
            return {
                "understood": False,
                "reason": f"could not enumerate real redshift schema {schema!r}: {exc}",
            }
        if not items:
            return {
                "understood": False,
                "reason": f"no real objects found in redshift schema {schema!r}",
            }
        action = {
            "kind": "migrate_schema_batch",
            "source_system": "redshift",
            "schema": schema,
            "include_data": include_data,
            "item_count": len(items),
        }
        return _make_plan(
            action,
            f"POST /migrate/redshift/schema/{schema}/batch?include_data={str(include_data).lower()}",
            f"Batch-migrates all {len(items)} real objects currently in redshift schema {schema!r}.",
        )

    if _MIGRATE_AND_DATA_RE.search(text) and is_starburst:
        status, payload = _find_matching_starburst_object(text)
        if status == "error":
            return {"understood": False, "reason": payload}
        if status == "none":
            return {
                "understood": False,
                "reason": "could not confidently match exactly one real starburst object to migrate",
            }
        if status == "ambiguous":
            locs = ", ".join(f"{c}.{s}.{n}" for c, s, _t, n in payload)
            return {
                "understood": False,
                "reason": f"instruction matches real starburst objects in more than one place ({locs}) — "
                "refusing rather than guessing; qualify with \"catalog X schema Y\"",
            }
        catalog, schema, object_type, name = payload
        hint = _extract_object_type_hint(text)
        if hint is not None and hint != object_type:
            return {
                "understood": False,
                "reason": (
                    f"instruction said {hint!r} but the real matching object {name!r} in starburst "
                    f"{catalog}.{schema} is actually a {object_type!r} — refusing rather than guessing"
                ),
            }
        if object_type not in ("table", "view"):
            return {
                "understood": False,
                "reason": f"{catalog}.{schema}.{name} is a real {object_type} — migrate-and-copy-data only "
                "applies to tables/views (no data on functions/procedures)",
            }
        action = {
            "kind": "migrate_table_and_data",
            "source_system": "starburst",
            "object_type": object_type,
            "catalog": catalog,
            "schema": schema,
            "name": name,
        }
        return _make_plan(
            action,
            f"internal: migrate.migrate_and_copy_starburst_table({catalog!r}, {schema!r}, {name!r})",
            f"Creates the real destination object AND copies all real rows for starburst "
            f"{catalog}.{schema}.{name} ({object_type}) via G7's custom deterministic path, in one step.",
        )

    if _MIGRATE_AND_DATA_RE.search(text):
        schema = _extract_schema(text)
        match = _find_matching_object(text, schema)
        if match is None:
            return {
                "understood": False,
                "reason": f"could not confidently match exactly one real object in redshift schema {schema!r} to migrate",
            }
        object_type, name = match
        hint = _extract_object_type_hint(text)
        if hint is not None and hint != object_type:
            return {
                "understood": False,
                "reason": (
                    f"instruction said {hint!r} but the real matching object {name!r} in schema "
                    f"{schema!r} is actually a {object_type!r} — refusing rather than guessing"
                ),
            }
        if object_type not in ("table", "view"):
            return {
                "understood": False,
                "reason": f"{name!r} is a real {object_type} — migrate-and-copy-data only applies to "
                "tables/views (no data on functions/procedures)",
            }
        action = {
            "kind": "migrate_table_and_data",
            "source_system": "redshift",
            "object_type": object_type,
            "schema": schema,
            "name": name,
        }
        return _make_plan(
            action,
            f"internal: migrate.migrate_and_copy_redshift_table({schema!r}, {name!r})",
            f"Creates the real destination object AND copies all real rows for redshift "
            f"{schema}.{name} ({object_type}) via Lakebridge, in one step.",
        )

    if _DATA_COPY_RE.search(text) and is_starburst:
        status, payload = _find_matching_starburst_object(text)
        if status == "error":
            return {"understood": False, "reason": payload}
        if status == "none":
            return {
                "understood": False,
                "reason": "could not confidently match exactly one real starburst table for a data copy",
            }
        if status == "ambiguous":
            locs = ", ".join(f"{c}.{s}.{n}" for c, s, _t, n in payload)
            return {
                "understood": False,
                "reason": f"instruction matches real starburst objects in more than one place ({locs}) — "
                "refusing rather than guessing; qualify with \"catalog X schema Y\"",
            }
        catalog, schema, object_type, name = payload
        if object_type != "table":
            return {
                "understood": False,
                "reason": f"{catalog}.{schema}.{name} is a real {object_type}, not a table — data copy only applies to tables",
            }
        action = {
            "kind": "copy_table_data",
            "source_system": "starburst",
            "catalog": catalog,
            "schema": schema,
            "name": name,
        }
        return _make_plan(
            action,
            f"POST /migrate/starburst/data/{catalog}/{schema}/{name}",
            f"Copies all real rows of starburst {catalog}.{schema}.{name} into a Databricks target table.",
        )

    if _DATA_COPY_RE.search(text):
        schema = _extract_schema(text)
        match = _find_matching_object(text, schema)
        if match is None:
            return {
                "understood": False,
                "reason": f"could not confidently match exactly one real table in redshift schema {schema!r} for a data copy",
            }
        object_type, name = match
        if object_type != "table":
            return {
                "understood": False,
                "reason": f"{name!r} is a real {object_type}, not a table — data copy only applies to tables",
            }
        action = {"kind": "copy_table_data", "source_system": "redshift", "schema": schema, "name": name}
        return _make_plan(
            action,
            f"POST /migrate/redshift/data/{schema}/{name}",
            f"Copies all real rows of redshift {schema}.{name} into a Databricks target table.",
        )

    if _MIGRATE_RE.search(text) and is_starburst:
        status, payload = _find_matching_starburst_object(text)
        if status == "error":
            return {"understood": False, "reason": payload}
        if status == "none":
            return {
                "understood": False,
                "reason": "could not confidently match exactly one real starburst object to migrate",
            }
        if status == "ambiguous":
            locs = ", ".join(f"{c}.{s}.{n}" for c, s, _t, n in payload)
            return {
                "understood": False,
                "reason": f"instruction matches real starburst objects in more than one place ({locs}) — "
                "refusing rather than guessing; qualify with \"catalog X schema Y\"",
            }
        catalog, schema, object_type, name = payload
        hint = _extract_object_type_hint(text)
        if hint is not None and hint != object_type:
            return {
                "understood": False,
                "reason": (
                    f"instruction said {hint!r} but the real matching object {name!r} in starburst "
                    f"{catalog}.{schema} is actually a {object_type!r} — refusing rather than guessing"
                ),
            }
        if object_type not in ("table", "view"):
            return {
                "understood": False,
                "reason": f"{catalog}.{schema}.{name} is a real {object_type} — starburst chat migration only supports table/view",
            }
        action = {
            "kind": "migrate_ddl",
            "source_system": "starburst",
            "object_type": object_type,
            "catalog": catalog,
            "schema": schema,
            "name": name,
        }
        return _make_plan(
            action,
            f"POST /migrate/starburst/ddl-custom/{object_type}/{catalog}/{schema}/{name}",
            f"Transpiles the real DDL of starburst {catalog}.{schema}.{name} ({object_type}) via G7's "
            "custom deterministic translator (never llm-transpile).",
        )

    if _MIGRATE_RE.search(text):
        schema = _extract_schema(text)
        match = _find_matching_object(text, schema)
        if match is None:
            return {
                "understood": False,
                "reason": f"could not confidently match exactly one real object in redshift schema {schema!r} to migrate",
            }
        object_type, name = match
        hint = _extract_object_type_hint(text)
        if hint is not None and hint != object_type:
            return {
                "understood": False,
                "reason": (
                    f"instruction said {hint!r} but the real matching object {name!r} in schema "
                    f"{schema!r} is actually a {object_type!r} — refusing rather than guessing"
                ),
            }
        action = {
            "kind": "migrate_ddl",
            "source_system": "redshift",
            "object_type": object_type,
            "schema": schema,
            "name": name,
        }
        return _make_plan(
            action,
            f"POST /migrate/redshift/ddl/{object_type}/{schema}/{name}",
            f"Transpiles the real DDL of redshift {schema}.{name} ({object_type}) via Lakebridge.",
        )

    if _PREVIEW_RE.search(text) and is_starburst:
        status, payload = _find_matching_starburst_object(text)
        if status == "error":
            return {"understood": False, "reason": payload}
        if status == "none":
            return {
                "understood": False,
                "reason": "could not confidently match exactly one real starburst table to preview",
            }
        if status == "ambiguous":
            locs = ", ".join(f"{c}.{s}.{n}" for c, s, _t, n in payload)
            return {
                "understood": False,
                "reason": f"instruction matches real starburst objects in more than one place ({locs}) — "
                "refusing rather than guessing; qualify with \"catalog X schema Y\"",
            }
        catalog, schema, object_type, name = payload
        if object_type != "table":
            return {
                "understood": False,
                "reason": f"{catalog}.{schema}.{name} is a real {object_type}, not a table — preview only applies to tables",
            }
        action = {
            "kind": "preview_source_table",
            "source_system": "starburst",
            "catalog": catalog,
            "schema": schema,
            "table": name,
            "limit": 10,
        }
        return _make_plan(
            action,
            f"internal: connectors.starburst.preview_table({catalog!r}, {schema!r}, {name!r}, limit=10)",
            f"Previews up to 10 real rows of starburst {catalog}.{schema}.{name}.",
        )

    if _PREVIEW_RE.search(text) and not _DATABRICKS_KEYWORD_RE.search(text):
        schema = _extract_schema(text)
        match = _find_matching_object(text, schema)
        if match is None:
            return {
                "understood": False,
                "reason": f"could not confidently match exactly one real table in redshift schema {schema!r} to preview",
            }
        object_type, name = match
        if object_type != "table":
            return {
                "understood": False,
                "reason": f"{name!r} is a real {object_type}, not a table — preview only applies to tables",
            }
        action = {
            "kind": "preview_source_table",
            "source_system": "redshift",
            "schema": schema,
            "table": name,
            "limit": 10,
        }
        return _make_plan(
            action,
            f"internal: connectors.redshift.preview_table({schema!r}, {name!r}, limit=10)",
            f"Previews up to 10 real rows of redshift {schema}.{name}.",
        )

    is_databricks_question = bool(_DATABRICKS_KEYWORD_RE.search(text)) or bool(_DATA_QUESTION_RE.search(text))
    if is_databricks_question:
        sql_match = _SELECT_FRAGMENT_RE.search(text)
        if sql_match:
            candidate_sql = sql_match.group(0).strip()
            if not _is_safe_select_fragment(candidate_sql):
                return {
                    "understood": False,
                    "reason": "sql-like fragment refused: only a single plain SELECT is allowed "
                    "(no ;-chained statements, no insert/update/delete/drop/alter/create/etc anywhere)",
                }
            action = {"kind": "databricks_query", "mode": "raw_select", "sql": candidate_sql}
            return _make_plan(
                action,
                "internal: databricks_target.execute() (validated single SELECT only)",
                f"Executes a real read-only SELECT against Databricks: {candidate_sql!r}",
            )

        status, payload = _find_matching_databricks_table(text)
        if status == "ok":
            catalog, schema, name = payload
            action = {
                "kind": "databricks_query",
                "mode": "preview",
                "catalog": catalog,
                "schema": schema,
                "table": name,
                "limit": 100,
            }
            return _make_plan(
                action,
                f"internal: databricks_target.preview_table({catalog!r}, {schema!r}, {name!r})",
                f"Previews up to 100 real rows of databricks {catalog}.{schema}.{name}.",
            )

        if status == "ambiguous":
            locs = ", ".join(f"{c}.{s}.{n}" for c, s, n in payload)
            return {
                "understood": False,
                "reason": f"instruction matches real databricks tables in more than one place ({locs}) — "
                "refusing rather than guessing; qualify with \"catalog X schema Y\"",
            }

        if status == "error":
            # A real infrastructure/connection failure occurred (e.g. a
            # Databricks connection or quota error).
            #
            # G20: this used to return immediately, which dead-ended the request
            # before the LLM method could try — verified live: "I'd like the
            # f_customer_tenure routine moved across to databricks" was routed
            # here by the word "databricks", hit the warehouse quota, and never
            # reached the model even though the instruction was a perfectly
            # ordinary Redshift migrate request. The LLM is the LAST method, so
            # a failure here must fall through to it rather than terminate.
            llm_plan = _plan_via_llm(instruction)
            if llm_plan is not None:
                return llm_plan
            # Still surface the REAL error rather than the generic refusal —
            # masking a quota/connection failure as "I didn't understand" would
            # send the user hunting for a phrasing problem that doesn't exist.
            return {
                "understood": False,
                "reason": f"could not check databricks: {payload}",
            }

        # status is "none" — G9's table resolution genuinely couldn't
        # answer this. G10: try the real Databricks Managed MCP
        # (Unity Catalog Functions) endpoint for TARGET_CATALOG.TARGET_SCHEMA
        # before giving up with `understood: False`.
        if not DATABRICKS_MCP_FALLBACK_ENABLED:
            return {
                "understood": False,
                "reason": "the databricks mcp fallback is temporarily disabled",
            }
        try:
            tools = databricks_mcp_client.list_tools_sync(
                databricks_target.TARGET_CATALOG, databricks_target.TARGET_SCHEMA
            )
        except DatabricksMCPError as exc:
            return {"understood": False, "reason": f"could not reach real databricks mcp endpoint: {exc}"}

        if not tools:
            return {
                "understood": False,
                "reason": "no MCP tools are currently registered in "
                f"{databricks_target.TARGET_CATALOG}.{databricks_target.TARGET_SCHEMA} "
                "(checked the real Databricks Managed MCP endpoint — it responded, "
                "but there are no Unity Catalog functions there yet)",
            }

        # Deterministic case-insensitive substring match against real tool
        # names only — no LLM/free-form matching, same "refuse rather than
        # guess" contract as every other resolver in this module. Matches on
        # either the full catalog__schema__function qualified name, or just
        # the bare function name (last "__"-separated segment) — realistic
        # chat text will reference the short name, not the qualified one.
        text_lower = text.lower()
        matches = [
            t
            for t in tools
            if t["name"].lower() in text_lower
            or t["name"].lower().rsplit("__", 1)[-1] in text_lower
        ]
        if not matches:
            names = ", ".join(t["name"] for t in tools)
            return {
                "understood": False,
                "reason": f"instruction did not match any real registered mcp tool name ({names})",
            }
        if len(matches) > 1:
            names = ", ".join(t["name"] for t in matches)
            return {
                "understood": False,
                "reason": f"instruction matches more than one real registered mcp tool ({names}) — "
                "refusing rather than guessing",
            }
        tool = matches[0]
        schema_props = (tool.get("input_schema") or {}).get("properties") or {}
        required = (tool.get("input_schema") or {}).get("required") or []
        if required or schema_props:
            return {
                "understood": False,
                "reason": f"mcp tool {tool['name']!r} exists but requires arguments "
                f"({', '.join(required) or ', '.join(schema_props)}) — chat cannot safely infer "
                "tool arguments yet, refusing rather than guessing",
            }
        action = {
            "kind": "databricks_mcp_tool",
            "catalog": databricks_target.TARGET_CATALOG,
            "schema": databricks_target.TARGET_SCHEMA,
            "tool_name": tool["name"],
            "arguments": {},
        }
        return _make_plan(
            action,
            f"internal: databricks_mcp_client.call_tool_sync(..., {tool['name']!r}, {{}})",
            f"Calls the real registered mcp tool {tool['name']!r} (zero required arguments) "
            f"in databricks {databricks_target.TARGET_CATALOG}.{databricks_target.TARGET_SCHEMA}.",
        )

    # ---------------------------------------------------------------- G20
    # 4th method: an external AI model, for instructions the fixed vocabulary
    # above cannot interpret. Reached only here, so a regex-matchable
    # instruction never pays for it. Disabled by default (llm_planner.is_enabled),
    # in which case this is a no-op and the refusal below is returned exactly as
    # it was before this branch existed.
    llm_plan = _plan_via_llm(instruction)
    if llm_plan is not None:
        return llm_plan

    return {
        "understood": False,
        "reason": _refusal_reason(),
    }


def _refusal_reason() -> str:
    """One message for both the regex-only and LLM-enabled cases. When the LLM
    is on, an unmatched instruction means the model also declined — which for an
    off-topic request is the correct, intended outcome, so the wording states
    the console's scope rather than implying a malfunction."""
    scope = (
        "I can only help with migrating objects, copying table data, previewing tables, "
        "batch-migrating a schema, and reconciling."
    )
    if llm_planner.is_enabled():
        return f"{scope} That request looks like something else, so nothing was planned."
    return (
        "instruction did not match any supported verb (migrate/copy data/reconcile/"
        f"batch-migrate-schema/databricks data question). {scope}"
    )


# Building the inventory means walking every Starburst catalog -> schema ->
# table. Measured live: 122.7s. Paying that on a chat request would reproduce
# the exact "it keeps getting stuck" problem the LLM method exists to fix, so
# the walk is (a) time-boxed and (b) cached.
_LLM_INVENTORY_TTL_S = float(os.getenv("LLM_INVENTORY_TTL_S", "600"))
_LLM_INVENTORY_BUDGET_S = float(os.getenv("LLM_INVENTORY_BUDGET_S", "15"))
_llm_inventory_cache: tuple[float, str] | None = None


def _llm_inventory() -> str:
    """A compact, REAL inventory handed to the model so it can only name things
    that actually exist.

    Time-boxed and cached. Best-effort by design: a source that can't be reached,
    or that we run out of budget for, is omitted — and the omission is stated in
    the text so the model is never told it has seen everything when it hasn't.
    Anything missing here still cannot be hallucinated into a plan, because
    `_plan_via_llm` re-resolves every name against the live systems afterwards.
    """
    global _llm_inventory_cache
    now = time.monotonic()
    if _llm_inventory_cache is not None and (now - _llm_inventory_cache[0]) < _LLM_INVENTORY_TTL_S:
        return _llm_inventory_cache[1]

    deadline = now + _LLM_INVENTORY_BUDGET_S
    lines: list[str] = []
    truncated = False

    # Redshift first: it is the small, fast one (a handful of schemas), so it
    # always makes it into the budget.
    try:
        for sc in redshift_conn.list_schemas():
            tables = [t.name for t in redshift_conn.list_tables(sc.name)]
            routines = [r.name for r in redshift_conn.list_routines(sc.name)]
            if tables or routines:
                lines.append(f"redshift schema {sc.name}: tables={tables} routines={routines}")
            if time.monotonic() > deadline:
                truncated = True
                break
    except RedshiftError:
        pass

    try:
        for cat in starburst_conn.list_catalogs():
            if time.monotonic() > deadline:
                truncated = True
                break
            for sch in starburst_conn.list_schemas(cat.name):
                if time.monotonic() > deadline:
                    truncated = True
                    break
                tables = [t.name for t in starburst_conn.list_tables(cat.name, sch.name)]
                if tables:
                    lines.append(f"starburst {cat.name}.{sch.name}: tables={tables}")
    except StarburstError:
        pass

    if truncated:
        lines.append(
            "(NOTE: this inventory is partial — enumeration was time-boxed. If the object the "
            "user names is not listed above, respond understood:false rather than guessing.)"
        )
    text = "\n".join(lines) if lines else "(inventory unavailable)"
    _llm_inventory_cache = (time.monotonic(), text)
    return text


def _plan_via_llm(instruction: str) -> dict | None:
    """Ask the model for one action, then re-validate everything it named
    against the live inventory before turning it into a plan.

    GUARDRAIL 3. llm_planner already enforces the kind allowlist; this function
    enforces that the objects are real. A hallucinated table cannot get past
    here, because the same resolution helpers the regex planner uses have to
    find it.
    """
    if not llm_planner.is_enabled():
        return None
    action = llm_planner.interpret(instruction, _llm_inventory())
    if action is None:
        return None

    kind = action["kind"]

    if kind == "reconcile":
        return _make_plan(
            action,
            "internal: executor.run_command_async(reconcile)",
            "Dispatches the configured reconcile job (interpreted by the AI model).",
        )

    # Everything else names objects. Re-resolve each against real inventory.
    if kind in ("migrate_schema_batch", "migrate_starburst_schema_batch"):
        schema = action.get("schema", "")
        if kind == "migrate_starburst_schema_batch":
            catalog = action.get("catalog", "")
            try:
                real = {s.name for s in starburst_conn.list_schemas(catalog)}
            except StarburstError:
                return None
            if schema not in real:
                return None
        else:
            try:
                real = {s.name for s in redshift_conn.list_schemas()}
            except RedshiftError:
                return None
            if schema not in real:
                return None
        return _make_plan(
            action,
            f"internal: batch migrate schema {schema}",
            f"Batch-migrates every real object in {schema} (interpreted by the AI model).",
        )

    if kind == "databricks_query":
        status, payload = _find_matching_databricks_table(action.get("table", ""))
        if status != "ok":
            return None
        catalog, schema, table = payload  # type: ignore[misc]
        checked = {"kind": "databricks_query", "mode": "preview", "catalog": catalog, "schema": schema, "table": table}
        return _make_plan(
            checked,
            f"internal: databricks_target.preview_table({catalog!r}, {schema!r}, {table!r})",
            f"Previews real rows from {catalog}.{schema}.{table} (interpreted by the AI model).",
        )

    source_system = action.get("source_system")
    if source_system == "starburst":
        status, payload = _find_matching_starburst_object(action.get("name", ""))
        if status != "ok":
            return None
        catalog, schema, object_type, name = payload  # type: ignore[misc]
        checked = dict(action, catalog=catalog, schema=schema, name=name)
        if kind != "copy_table_data":
            checked["object_type"] = object_type
        qualified = f"{catalog}.{schema}.{name}"
    elif source_system == "redshift":
        schema = action.get("schema", "")
        try:
            real_schemas = {s.name for s in redshift_conn.list_schemas()}
        except RedshiftError:
            return None
        if schema not in real_schemas:
            return None
        found = _find_matching_object(action.get("name", ""), schema)
        if found is None:
            return None
        object_type, name = found
        checked = dict(action, schema=schema, name=name)
        if kind != "copy_table_data":
            checked["object_type"] = object_type
        qualified = f"{schema}.{name}"
    else:
        return None

    # Data actions are meaningless for routines — refuse rather than dispatch a
    # call the backend would reject.
    if kind in ("copy_table_data", "migrate_table_and_data") and object_type not in ("table", "view"):
        return None

    return _make_plan(
        checked,
        f"internal: {kind} for {qualified}",
        f"{kind.replace('_', ' ')} for real {source_system} object {qualified} "
        "(interpreted by the AI model, then re-checked against live inventory).",
    )


def _make_plan(action: dict, endpoint: str, explanation: str) -> dict:
    plan_id = f"plan_{uuid.uuid4().hex[:12]}"
    plan = {"plan_id": plan_id, "action": action, "endpoint": endpoint, "explanation": explanation}
    _PLAN_CACHE[plan_id] = plan
    return {"understood": True, **plan}


def resolve_plan(plan: dict | None, plan_id: str | None) -> dict:
    if plan is not None:
        return plan
    if plan_id is not None:
        cached = _PLAN_CACHE.get(plan_id)
        if cached is None:
            raise KeyError(plan_id)
        return cached
    raise ValueError("either plan or plan_id must be provided")


def execute_plan(plan: dict) -> dict:
    """Executes a previously-returned plan through the exact same real
    functions the normal REST endpoints already call — one real code
    path, never a second reimplementation. Returns enough to look the
    record up via the existing GET endpoints (/migrations/{id},
    /batches/{id}, /runs/{id}) — no new result shape is invented."""
    action = plan.get("action") or {}
    kind = action.get("kind")

    if kind == "migrate_ddl" and action.get("source_system") == "starburst":
        # G7's custom fast path only — never migrate.migrate_starburst_ddl
        # (the old llm-transpile path). See module docstring.
        mig = migrate.migrate_starburst_ddl_custom(
            action["object_type"], action["catalog"], action["schema"], action["name"]
        )
        return {"kind": kind, "result_type": "migration", "migration_id": mig.id}

    if kind == "migrate_ddl":
        mig = migrate.migrate_redshift_ddl(action["object_type"], action["schema"], action["name"])
        return {"kind": kind, "result_type": "migration", "migration_id": mig.id}

    if kind == "migrate_table_and_data" and action.get("source_system") == "starburst":
        mig = migrate.migrate_and_copy_starburst_table(
            action["catalog"], action["schema"], action["name"], action.get("object_type", "table")
        )
        return {"kind": kind, "result_type": "migration", "migration_id": mig.id}

    if kind == "migrate_table_and_data":
        mig = migrate.migrate_and_copy_redshift_table(
            action["schema"], action["name"], action.get("object_type", "table")
        )
        return {"kind": kind, "result_type": "migration", "migration_id": mig.id}

    if kind == "copy_table_data" and action.get("source_system") == "starburst":
        mig = migrate.copy_starburst_table_data(action["catalog"], action["schema"], action["name"])
        return {"kind": kind, "result_type": "migration", "migration_id": mig.id}

    if kind == "copy_table_data":
        mig = migrate.copy_redshift_table_data(action["schema"], action["name"])
        return {"kind": kind, "result_type": "migration", "migration_id": mig.id}

    if kind == "migrate_starburst_schema_batch":
        batch = migrate.start_starburst_schema_batch(action["catalog"], action["schema"], action["include_data"])
        return {"kind": kind, "result_type": "batch", "batch_id": batch.id}

    if kind == "migrate_schema_batch":
        items = migrate.build_redshift_schema_batch_items(action["schema"], include_data=action["include_data"])
        batch = migrate.start_batch(items)
        return {"kind": kind, "result_type": "batch", "batch_id": batch.id}

    if kind == "reconcile":
        # Identical dispatch to main.py's POST /runs/reconcile — not a
        # reimplementation, the same two calls executor.py already exposes.
        run = store.create(command="reconcile", args=[])
        run_command_async(run.id, "reconcile", [])
        return {"kind": kind, "result_type": "run", "run_id": run.id}

    if kind == "preview_source_table" and action.get("source_system") == "starburst":
        columns, rows = starburst_conn.preview_table(
            action["catalog"], action["schema"], action["table"], limit=action.get("limit", 10)
        )
        return {
            "kind": kind,
            "result_type": "query",
            "columns": columns,
            "rows": [list(r) for r in rows],
            "row_count": len(rows),
        }

    if kind == "preview_source_table":
        columns, rows = redshift_conn.preview_table(
            action["schema"], action["table"], limit=action.get("limit", 10)
        )
        return {
            "kind": kind,
            "result_type": "query",
            "columns": columns,
            "rows": [list(r) for r in rows],
            "row_count": len(rows),
        }

    if kind == "databricks_query" and action.get("mode") == "raw_select":
        # Re-validated here, not just trusted from the plan body — a client
        # could re-POST a hand-edited plan. Same real databricks_target.py
        # this whole project already uses, no second SQL execution path.
        if not _is_safe_select_fragment(action.get("sql", "")):
            raise ValueError("refused: plan sql is not a single plain SELECT")
        rows = databricks_target.execute(action["sql"])
        return {
            "kind": kind,
            "result_type": "query",
            "columns": None,
            "rows": [list(r) for r in rows],
            "row_count": len(rows),
        }

    if kind == "databricks_query":
        columns, rows = databricks_target.preview_table(
            action["catalog"], action["schema"], action["table"], limit=action.get("limit", 100)
        )
        return {
            "kind": kind,
            "result_type": "query",
            "columns": columns,
            "rows": [list(r) for r in rows],
            "row_count": len(rows),
        }

    if kind == "databricks_mcp_tool":
        result = databricks_mcp_client.call_tool_sync(
            action["catalog"], action["schema"], action["tool_name"], action.get("arguments") or {}
        )
        return {"kind": kind, "result_type": "mcp_tool_call", "tool_name": action["tool_name"], "result": result}

    raise ValueError(f"unknown or missing plan action kind: {kind!r}")

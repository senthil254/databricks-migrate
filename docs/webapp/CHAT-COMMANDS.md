# Chat Commands — real, tested example phrases

Every phrase below was actually POSTed to a live `POST /chat/plan` (and, for
two of them, followed through to `POST /chat/execute` and a real terminal
`Migration`/`Run`/`Batch` record) against the running backend on 2026-08-01.
None of this is aspirational — it is traced against the real regexes in
`backend/app/chat.py` as of the G8 Starburst extension, not invented syntax.

`chat.py` does deliberate, honest pattern matching (see its module
docstring) — a fixed small verb vocabulary matched against the REAL live
object inventory (Redshift via `redshift_conn`, Starburst via
`starburst_conn`). If a phrase doesn't uniquely resolve to exactly one real
object, `/chat/plan` returns `{"understood": false, "reason": "..."}`
rather than guessing. Don't invent flags/verbs beyond what's below —
anything else falls through to the final `_MIGRATE_RE`/`_DATA_COPY_RE`/etc.
checks and, if none match, the catch-all refusal.

## The two-step flow

1. `POST /chat/plan {"instruction": "<phrase>"}` — returns a *proposal*,
   never executes anything. Response shape: `{"understood": true, "plan_id":
   ..., "action": {...}, "endpoint": "...", "explanation": "..."}` or
   `{"understood": false, "reason": "..."}`.
2. `POST /chat/execute {"plan_id": "<id>"}` (or the full plan body) —
   dispatches the real work through the exact same adapter functions the
   normal REST endpoints call. For DDL/data-copy actions this call **does
   not return until the migration reaches a terminal state** (it's a
   synchronous call into `migrate.py`'s functions) — the response is just
   `{"kind": ..., "result_type": "migration", "migration_id": "mig_..."}`;
   fetch `GET /migrations/{id}` to see the real result. For schema-batch
   and reconcile actions, the underlying work is dispatched asynchronously
   (background thread / `run_command_async`) — `POST /chat/execute`
   returns once the job is **started**, not once it **finishes**; poll
   `GET /batches/{id}` or `GET /runs/{id}` for the real terminal state.
   Don't read "chat/execute returned" as "the migration succeeded."

## CRITICAL performance/ambiguity caveat — Starburst needs explicit qualifiers

Starburst is a real three-level namespace (catalog.schema.table), unlike
Redshift's two levels. **Every Starburst example below deliberately
includes an explicit `catalog X` and/or `schema Y` qualifier.** An
unqualified Starburst instruction (e.g. just "migrate table nation") makes
`chat.py` crawl every real catalog/schema live via
`starburst_conn.list_catalogs/list_schemas/list_tables` looking for a
unique match — against this environment's real catalogs (`tpch`, `tpch`
scale factors alone has `sf1`/`sf100`/`sf1000`/`sf10000`/`sf100000` all
containing tables with the same names, plus `federated_mysql`,
`federated_postgres`, `federated_s3`, `galaxy`, `mcp2ohio`, `sample`,
`starburst`, `system`) this is slow (a live crawl across every
catalog/schema) and frequently comes back `understood: false` (ambiguous —
the same table name legitimately exists in multiple schemas, e.g. `nation`
exists in `tpch.sf1`, `tpch.sf100`, `tpch.sf1000`, etc). Always give a
`catalog X schema Y` qualifier for Starburst phrases to keep it fast and
unambiguous. Whole-schema Starburst batches (`_SCHEMA_BATCH_RE` matched
with the "starburst"/"trino" keyword present) **require** an explicit
`catalog X` — `chat.py` refuses outright (`understood: false`) without one,
since it can't guess which catalog's schema you mean.

---

## 1. Single-table DDL migration

### Redshift

```
migrate table venue_sales_summary
```

- Matches `_MIGRATE_RE` (`migrate|transpile|convert`), no `starburst`/`trino`
  keyword present, so resolved against the real Redshift inventory. Default
  schema is `public` (`DEFAULT_SCHEMA`) since no `schema X` was given —
  `venue_sales_summary` is unique across `public`'s real tables so this
  resolves unambiguously.
- **Real plan returned:**
  `{"understood": true, "action": {"kind": "migrate_ddl", "source_system":
  "redshift", "object_type": "table", "schema": "public", "name":
  "venue_sales_summary"}, "endpoint": "POST
  /migrate/redshift/ddl/table/public/venue_sales_summary"}`
- **Live-tested through `/chat/execute`:** produced `mig_328`, real terminal
  state `"status": "completed"`, `"engine": "lakebridge-transpile"`, real
  `source_ddl`/`output_ddl` populated (see evidence below).

### Starburst

```
migrate table nation in starburst catalog tpch schema sf1
```

- The `starburst` keyword triggers `is_starburst`; `_MIGRATE_RE` matches
  `migrate`; the qualified `catalog tpch` / `schema sf1` pins the crawl to
  exactly that catalog+schema so it resolves fast and unambiguously to the
  real `tpch.sf1.nation` table (this table name is genuinely duplicated
  across other `tpch.sf*` schemas in this environment — the qualifiers are
  load-bearing, not decorative).
- **Real plan returned:**
  `{"understood": true, "action": {"kind": "migrate_ddl", "source_system":
  "starburst", "object_type": "table", "catalog": "tpch", "schema": "sf1",
  "name": "nation"}, "endpoint": "POST
  /migrate/starburst/ddl-custom/table/tpch/sf1/nation"}`
- Note the endpoint is `ddl-custom`, not `ddl` — `chat.py` always dispatches
  resolved Starburst DDL to G7's fast deterministic
  `migrate_starburst_ddl_custom` path, never the old `llm-transpile` path.
- **Live-tested through `/chat/execute`:** completed in ~3.4s, produced
  `mig_329`, `"engine": "starburst-custom-ddl"` (never
  `llm-transpile-experimental`), real `source_ddl`/`output_ddl` (see
  evidence below).

## 2. Single-view DDL migration (Redshift only — verified real view exists)

```
migrate view copy_job_detail in schema pg_auto_copy
```

- `_extract_object_type_hint` picks up the word "view"; `_SCHEMA_NAME_RE`
  extracts `pg_auto_copy` (the real view's actual schema — Redshift's
  `public` schema in this environment has no views, only tables, so this
  phrase must use `pg_auto_copy` to match a real object). Matched a real
  hint (`view`) against a real resolved type (`view`) — no mismatch refusal.
- **Real plan returned (traced, not executed — this view's underlying
  migration is known from prior sessions to fail with a real Redshift
  permission error on this account, documented separately; the point here
  is that `/chat/plan` correctly resolves and proposes it):**
  `{"understood": true, "action": {"kind": "migrate_ddl", "source_system":
  "redshift", "object_type": "view", "schema": "pg_auto_copy", "name":
  "copy_job_detail"}, "endpoint": "POST
  /migrate/redshift/ddl/view/pg_auto_copy/copy_job_detail"}`

Starburst view example is intentionally omitted here — this environment's
real Starburst catalogs weren't confirmed to have a matching view during
this pass; don't fabricate one. If you need one, list real objects first
via `GET /explore/starburst/catalogs/{catalog}/schemas/{schema}/tables` and
confirm `"type": "view"` before writing the phrase.

## 3. Data copy (single table)

### Redshift

```
copy data from public table venue
```

Matches `_DATA_COPY_RE` (`copy...data`), no starburst keyword, resolves
against the real `public` schema inventory. Real endpoint:
`POST /migrate/redshift/data/public/venue`.

### Starburst

```
copy data from starburst catalog tpch schema sf1 table nation
```

- **Real plan returned (traced, not executed to avoid an unnecessary real
  data copy job in this pass — the DDL example above already exercises the
  same resolution path):**
  `{"understood": true, "action": {"kind": "copy_table_data",
  "source_system": "starburst", "catalog": "tpch", "schema": "sf1", "name":
  "nation"}, "endpoint": "POST /migrate/starburst/data/tpch/sf1/nation"}`
- Same qualifier rule applies — omitting `catalog tpch schema sf1` risks a
  slow full crawl and a likely `understood: false` ambiguous result since
  `nation` exists in multiple `tpch.sf*` schemas.

## 4. Whole-schema batch migration

### Redshift

```
batch migrate the entire schema public
```

Matches `_SCHEMA_BATCH_RE`'s `(batch[- ]?migrate|migrate)...(whole|entire)...schema`
alternative. `include_data` stays `false` (the word "data" isn't present —
add "with data" / "and data" to also copy rows). Real plan resolved against
the real `public` schema's 11 objects (8 tables + 3 routines):

```json
{"understood": true, "action": {"kind": "migrate_schema_batch",
 "source_system": "redshift", "schema": "public", "include_data": false,
 "item_count": 11},
 "endpoint": "POST /migrate/redshift/schema/public/batch?include_data=false"}
```

### Starburst

```
batch migrate starburst schema sf1 catalog tpch
```

- Matches the plain `_SCHEMA_BATCH_RE` (`batch[- ]?migrate...schema`)
  alternative plus the starburst keyword. The explicit `catalog tpch` is
  **mandatory** for Starburst batches — without it `chat.py` returns
  `understood: false` ("a starburst whole-schema batch needs an explicit
  catalog ... can't guess it").
- Real plan resolved against the real `tpch.sf1` schema's 8 tables:

```json
{"understood": true, "action": {"kind": "migrate_starburst_schema_batch",
 "source_system": "starburst", "catalog": "tpch", "schema": "sf1",
 "include_data": false, "item_count": 8},
 "endpoint": "chat-only: batch-migrates 8 real starburst objects in tpch.sf1
 via migrate_starburst_ddl_custom (+ copy_starburst_table_data for tables
 if include_data)"}
```

- Note: this dispatches through `chat.py`'s own
  `_start_starburst_schema_batch`/`_run_starburst_schema_batch` — a
  self-contained mirror of `migrate.run_batch`'s orchestration built only
  from G7's custom deterministic functions, deliberately NOT reusing
  `migrate.start_batch` (which would silently route Starburst items through
  the old `llm-transpile` path — see `chat.py`'s module docstring for why).

## 5. Reconcile / verify

```
reconcile
```

(`validate` and `verify` also match `_RECONCILE_RE`.) System-agnostic —
matched before any Redshift/Starburst resolution logic runs, since a
reconcile run isn't scoped to one object.

**Real plan returned:**
`{"understood": true, "action": {"kind": "reconcile"}, "endpoint": "POST
/runs/reconcile"}`

Executing this dispatches the exact same `store.create(command="reconcile")`
+ `run_command_async` pair `POST /runs/reconcile` itself uses — remember
G8's own note: this call returns once the job is **dispatched**, not once
it **finishes**. Poll `GET /runs/{run_id}` for the real terminal status.

---

## Live-tested evidence (2026-08-01, this session)

Two full plan -> execute -> terminal-state round trips against the live
backend on port 8811:

**Redshift — `migrate table venue_sales_summary`:**
```
POST /chat/plan   -> plan_0a514911845c, endpoint POST /migrate/redshift/ddl/table/public/venue_sales_summary
POST /chat/execute -> {"kind": "migrate_ddl", "result_type": "migration", "migration_id": "mig_328"}
GET  /migrations/mig_328 -> status: "completed", engine: "lakebridge-transpile",
     source_ddl/output_ddl both real and populated, target_catalog/schema/table
     correctly null (this is a DDL-only migration, not a data copy).
```

**Starburst — `migrate table nation in starburst catalog tpch schema sf1`:**
```
POST /chat/plan   -> plan_e32cfde7f7f7, endpoint POST /migrate/starburst/ddl-custom/table/tpch/sf1/nation
POST /chat/execute -> {"kind": "migrate_ddl", "result_type": "migration", "migration_id": "mig_329"}
                      (returned in ~3.4s, confirming the fast deterministic path, not a
                      multi-minute llm-transpile job)
GET  /migrations/mig_329 -> status: "completed", engine: "starburst-custom-ddl"
     (never llm-transpile-experimental), source_ddl/output_ddl both real:
       source_ddl: "CREATE TABLE tpch.sf1.nation (\n   nationkey bigint NOT NULL,\n   name varchar(25) NOT NULL,\n   regionkey bigint NOT NULL,\n   comment varchar(152) NOT NULL\n)"
       output_ddl: "CREATE TABLE `nation` (\n  `nationkey` BIGINT,\n  `name` STRING,\n  `regionkey` BIGINT,\n  `comment` STRING\n)"
```

All other phrases in this document (view migration, data copy, batch
migrations, reconcile) were traced via a real `POST /chat/plan` call and
confirmed `understood: true` with the exact `action`/`endpoint` shown, but
were not carried through `/chat/execute` in this pass (to avoid redundant
real jobs beyond what's needed to prove the parsing/dispatch logic works
for both systems) — the two full round trips above already exercise the
same execution machinery (`migrate.migrate_redshift_ddl` and
`migrate.migrate_starburst_ddl_custom`) these other phrases would also
call.

## Databricks data-access fallback (G9)

If a message doesn't match any of the structured verbs above but mentions
"databricks" or looks like a data question ("what's in...", "show me...",
"how many rows..."), `chat.py` tries to resolve a real catalog.schema.table
reference and answer it directly against the live Databricks warehouse —
this is a real query fallback (`databricks_target.preview_table`/
`execute()`), not a literal MCP protocol client; no MCP server exists in
this codebase.

Real example, traced end-to-end:
```
POST /chat/plan {"instruction": "what's in lakebridge_demo.g3_migrations.redshift_public_venue in databricks"}
  -> understood: true, action.kind: "databricks_query", mode: "preview"
POST /chat/execute -> real columns (venueid, venuename, venuecity, venuestate, venueseats)
                       and 100 real rows from the live warehouse
```

An unresolvable object ("what's in databricks.nonexistent_catalog.fake_table")
returns `understood: false` — it never fabricates a match. A raw SQL
fragment that isn't a plain `SELECT` (e.g. containing `; drop table` or an
`insert`/`update`/`delete`/`alter` keyword) is rejected before anything is
executed, matching this project's "never run unsanitised SQL" rule.

## Third fallback: real Databricks Managed MCP (G10)

If a Databricks-flavored question doesn't resolve to a real table via the G9
fallback either, chat now tries a genuine third fallback: it calls
Databricks' own Managed MCP server (Unity Catalog Functions type,
`https://<workspace-hostname>/api/2.0/mcp/functions/{catalog}/{schema}`,
real Streamable HTTP MCP protocol, same auth profile as everything else in
this backend) and looks for a matching registered UC function tool.

Real example, traced end-to-end against the live workspace:
```
POST /chat/plan {"instruction": "what functions are available for lakebridge_demo g3_migrations in databricks"}
  -> understood: false
     reason: "no MCP tools are currently registered in lakebridge_demo.g3_migrations
              (checked the real Databricks Managed MCP endpoint — it responded,
              but there are no Unity Catalog functions there yet)"
```

This is the honest current state: the fallback is fully real and live, but
`lakebridge_demo.g3_migrations` has zero UC functions registered, so it
always refuses today rather than fabricate a result. To make it return real
data, register a Unity Catalog function in that exact catalog/schema
(`CREATE FUNCTION lakebridge_demo.g3_migrations.<name>(...) RETURNS ... AS $$ ... $$`
via the Databricks SQL warehouse) — `list_tools_sync` will then surface it,
and an unambiguous, zero-required-argument name match will build a real
executable plan for it.

**Known latency caveat, not yet addressed in the UI:** this fallback's real
round trip (MCP handshake + auth + the underlying `_find_matching_databricks_table`
crawl it falls through from) took 78–120 seconds in independent verification.
The chat UI already shows an "Executing…" state, but no explicit
timeout/loading messaging exists yet for this specific path — worth a UX
pass in a future phase, tracked here rather than silently glossed over.

## G12 update: MCP fallback disabled, new fast source-table preview intent

**The Databricks Managed MCP fallback above is currently disabled** —
`DATABRICKS_MCP_FALLBACK_ENABLED = False` in `backend/app/chat.py`. It was
too slow (78-120s+) and occasionally unreliable for interactive chat use.
The code is untouched and fully intact; flipping that one constant back to
`True` re-enables it with no other changes needed. Any Databricks-flavored
chat message now gets `{"understood": false, "reason": "the databricks mcp
fallback is temporarily disabled"}` instead of attempting the MCP round
trip — but note this refusal itself is not instant: it's still reached only
after the pre-existing G9 `_find_matching_databricks_table` catalog crawl
runs, which can itself take well over a minute for an unqualified message
(a pre-existing G9 characteristic, not something G12 introduced or fixed).

**What chat can now do that it couldn't before**: preview real rows
directly from a SOURCE Starburst or Redshift table — no migration, no copy,
just show the data — which is what "query a starburst demo catalog demo
table, show the data" actually needed. Real, tested examples:

```
"preview the employee table in starburst catalog federated_postgres schema burstbank"
  -> understood: true, resolves via _find_matching_starburst_object
  -> execute: real 10-row preview, columns + rows, ~2s

"show me the venue table in redshift"
  -> understood: true, resolves via _find_matching_object
  -> execute: real 10-row preview, columns + rows, ~2-5s
```

Existing `copy`/`migrate` phrasing is unaffected — those still route to
their original intents, confirmed via regression tests.

**Real frontend bug fixed alongside this**: `ChatPanel.tsx` had never
rendered `result_type: "query"` or `"mcp_tool_call"` responses at all —
its polling logic mistook them for an async `"run"` and called
`api.getRun(undefined)`. This meant G9's own Databricks-preview-via-chat
and G10/G11's MCP tool-call results never actually displayed anything
useful in the UI, independent of backend correctness. Both are now
rendered as a real columns/rows table, reusing the same preview-panel
styling as the Explorer and Databricks tabs.

**Real bug found and fixed during independent verification**:
`connectors/databricks_browse.py`'s `list_catalogs`/`list_schemas`/
`list_tables` connected to Databricks outside their own `try/except`, so a
real connection failure (e.g. the SQL warehouse's daily free-tier query
quota being exhausted, which happened live during this phase's own
verification) surfaced as a raw HTTP 500 instead of the module's intended
graceful `{"understood": false, ...}` refusal. Fixed to wrap the connect
call consistently with the rest of the file; verified via mocked
connection-failure tests (a live warehouse call wasn't available to test
this against, since the quota was actually exhausted at the time).

**Environment note**: the Databricks SQL warehouse's free-tier daily query
quota was exhausted during this phase's independent verification, which
blocked re-confirming exact live timings for Databricks-flavored chat
messages beyond what was already measured. The Starburst/Redshift preview
feature above does not depend on the Databricks warehouse at all and was
fully verified live.

## G13: confirming the Databricks NL query feature — status and the cluster question

**Yes, this feature already exists** — the G9 `databricks_query` chat intent
(triggered by "databricks"/data-question phrasing like "what's in...",
"show me...", "how many rows...") lets you ask chat about real Databricks
table data in plain English. It is completely independent of the
`DATABRICKS_MCP_FALLBACK_ENABLED` toggle from G12 — that only affects a
later, separate fallback.

**Does it need a paid cluster? No.** This workspace is confirmed Free/Express
tier, serverless SQL warehouse only (`Serverless Starter Warehouse`,
2X-Small) — there is no cluster-sizing question here at all. The real
constraint is the free tier's **daily query quota**, which independent
testing confirmed is currently exhausted:
```
BAD_REQUEST: Sorry, cannot run the resource because you have hit your
free daily limit. Please come back again tomorrow.
```
This was reproduced independently, twice, with different phrasing and
different tables, and via a direct connector call outside of chat entirely
— it is a genuine account-level daily quota, not a code bug, not a cluster
capacity issue, and not something more compute would fix.

**Real bug found and fixed while confirming this**: chat.py was masking
this exact real error behind a misleading "the databricks mcp fallback is
temporarily disabled" message — conflating "genuinely found no matching
table" with "a real infrastructure/quota failure occurred." Fixed so a real
connection/quota error now surfaces its own real (redacted) text instead of
the unrelated MCP-disabled message. Verified live against the real,
still-exhausted quota error itself.

**Bottom line**: the feature is real, correctly built, and will work as
soon as the daily quota resets (or the workspace moves off the free tier) —
no code or infrastructure change is needed beyond that. Retry a real
instruction like `"what's in lakebridge_demo.g3_migrations.redshift_public_venue
in databricks"` once the quota window has passed.

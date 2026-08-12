# Lakebridge Web UI — Plan

## What this is

A web UI over Databricks Lakebridge (currently CLI-only). Scoped down from an
original mega-spec that asked for 11 agent roles, a chat layer, and full
enterprise UI on day one. This plan builds the same end state in six
independently-verifiable phases instead, each run as its own `/loop` goal.

## Verified environment (2026-08-01)

- Databricks CLI v1.9.0, profile `lakebridge-eval` authenticated
- Real Lakebridge subcommands: `analyze`, `transpile`, `describe-transpile`,
  `install-transpile`, `configure-reconcile`, `reconcile`,
  `aggregates-reconcile`, `configure-database-profiler`,
  `execute-database-profiler`, `test-profiler-connection`, `llm-transpile`
- Sample fixtures: `samples/snowflake/*.sql` (4 files, already used in a
  prior successful transpile run — see `docs/TECHNICAL.md`)
- Known constraints (from prior session, `docs/*.md`): workspace is
  serverless-only (no job clusters), Default Storage breaks the catalogs
  REST API, no native Excel reader, Morpheus transpiler has a `:user`
  JSON-path bug, Analyzer binary is x86_64-only (needs Rosetta 2 on Apple
  Silicon)
- Node 24.14, Python 3.9.6 (system) / 3.12 via `uv`, `uv` 0.11.29

## Stack decisions (Phase G1, locked here so later phases don't re-litigate)

- **Backend: Python + FastAPI.** Already Python-centric here; shelling out to
  the `databricks` CLI is simplest from Python; avoids a second runtime for
  the backend.
- **Execution: `subprocess` with argument arrays, never `shell=True`.**
  Allowlist of the 10 real subcommands above. No others.
- **Frontend: deferred to G3.** G1–G2 are API-only, verified by tests and
  direct HTTP calls — no framework decision needed yet, and no UI to be
  "polished" before the thing it wraps actually works.
- **Persistence: SQLite file** for run/event history. No external DB for an
  MVP.
- **First real commands wrapped:** `describe-transpile` (read-only, safe) and
  `transpile` against local `samples/snowflake/*.sql` (no cloud side
  effects — writes to a local output dir only).

## Phases (each is one `/loop` goal)

| # | Goal | Depends on | Verified by |
|---|---|---|---|
| G1 | Backend adapter core: safe process execution, `describe-transpile` + `transpile` wrapped, structured run/event model, unit + integration tests | git init (done) | `pytest` green, manual curl against running server |
| G2 | Adapter completeness: `analyze` + `reconcile` wired in, SQLite persistence, full API surface for the MVP flow | G1 | `pytest` green, API contract doc matches actual responses |
| ~~G3~~ | ~~Web UI MVP: trigger buttons + polling list~~ | — | **Superseded 2026-08-01 — didn't meet the real need (see below). Code kept, not deleted; extended by G3.1+ rather than restarted from zero.** |
| G4 | Run history, validation results view | G3.3+ | Browser walk-through against a real reconcile run |
| G5 | Security + accessibility hardening, independent checker pass | G1–G4 | Checker report with concrete pass/fail per item, no self-certification |
| G6 | Natural-language chat layer — intent → reviewable plan → confirm → execute via the *same* adapter | G1–G5 verified | Browser walk-through: a chat instruction produces a plan, requires confirmation, executes, matches audit log |

### G3 rebuild — real two-source-system explore-and-migrate demo

The original G3 (trigger buttons over local sample files) didn't match the
actual requirement: explore real Starburst and real Redshift objects, then
demonstrate migrating each object type to Databricks via drag-and-drop.
Full detail and all real findings in `MEMORY.md`'s 2026-08-01 "G3 rejected,
rebuilt" entry — summary here, don't duplicate the reasoning there.

**Hard capability facts, verified against the real CLI and both real
systems, not assumed:**
- Redshift has a real deterministic Lakebridge transpiler. Starburst does
  not — only the experimental, non-deterministic `llm-transpile`. Both are
  in scope; Starburst migrations must be UI-labeled experimental.
- Lakebridge has **no data-movement capability at all** — `transpile` only
  converts local SQL/code files, `reconcile` only compares. Table *data*
  migration needs a separate mechanism built on direct DB connections.
- Starburst Galaxy UDFs must be created in `galaxy.functions` specifically
  — discovered from a real `PERMISSION_DENIED` error message, not docs.
- Starburst has no user-definable stored procedures (architectural, not a
  missing-object gap) — realistic Starburst scope is tables/views/
  schemas/catalogs + scalar UDFs only.

**Real credentials:** `backend/.env` (gitignored, `chmod 600`). Connects to
a real Redshift cluster (`<cluster-identifier>`, db `dev`) and a real
Starburst Galaxy catalog (`mcp2ohio`). **User should rotate these
credentials** — they were pasted into chat before being moved to the local
file, so they're in this session's transcript.

| # | Goal | Depends on | Verified by |
|---|---|---|---|
| G3.1 | Real connector backend — list databases/catalogs/schemas/tables/columns/routines for both systems via API. No migration, no UI. | G1, G2 | Real API calls against both live systems, actual object counts shown |
| G3.2 | Real migration execution per object type — DDL/code via Lakebridge (Redshift) and `llm-transpile` (Starburst, labeled experimental); separate real data-copy path for table rows | G3.1 | At least one real table, the real view-equivalent, the real procedure, and both real functions migrated end to end, output inspected |
| G3.3 | Explorer tree UI + drag-and-drop, wired to G3.2 | G3.2 | Browser walk-through: explore both systems' real trees, drag a real object, watch it migrate |
| G3.4 | Batch flows — migrate a whole schema/database in one action | G3.3 | Browser walk-through of a real multi-object batch migration |

## Stop conditions per phase

A phase is done when its tests pass **and** I have manually exercised the
result (curl for API phases, browser for UI phases) and can show the
transcript — not when code merely compiles or "looks right."

## Explicitly not doing yet

- No auth/multi-user model until a phase actually needs it
- No cloud migration runs beyond the local `samples/snowflake` fixtures until
  G2 is verified safe
- No chat layer before G1–G5 are real and working (per original spec's own
  ordering constraint)

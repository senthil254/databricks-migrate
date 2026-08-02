# Lakebridge Migration Console

A web UI over [Databricks Lakebridge](https://databrickslabs.github.io/lakebridge/), which ships as a
CLI only. It turns "migrate this table from Redshift to Databricks" into a point-and-click — or
plain-English — operation, while keeping every action auditable.

Nothing in the UI is mocked. Every object listed is read live from the real source system, and every
migration creates a real object in Unity Catalog.

## What it does

- **Browse** live Redshift, Starburst/Trino and Databricks inventories side by side.
- **Migrate** a table, view, function or procedure — transpiling its DDL through Lakebridge and
  creating the object in Databricks.
- **Copy data** — a real `DROP` + `CREATE` + row insert, verified with a `SELECT COUNT(*)` against
  the target. Lakebridge itself does not move data; that path is implemented here.
- **Batch** a multi-object selection or an entire schema in one dispatch.
- **Ask in English** — "migrate the customers table in schema demo_fast_test and its data" produces
  a reviewable plan. Nothing executes until you confirm it.

## Architecture

```
  Browser (React + Vite)
        │  HTTP (same-origin /api in tunnels, else :8811)
        ▼
  FastAPI adapter  ── subprocess (argv array, never a shell) ──▶  databricks CLI + Lakebridge
        │                                                          (Morpheus / Bladebridge)
        ├── redshift-connector ───▶ Amazon Redshift
        ├── trino ───────────────▶ Starburst / Trino
        └── databricks-sql-connector + databricks-sdk ──▶ Databricks SQL Warehouse / Unity Catalog
```

The browser never invokes the CLI. Everything routes through the adapter, which accepts only an
allowlist of real Lakebridge subcommands and builds every command as an argument array — so a value
containing shell metacharacters stays a single argument instead of becoming a second command.

## Prerequisites

- Python 3.12, Node 20+
- A Databricks workspace with a SQL Warehouse and Unity Catalog
- Java 21 (the Morpheus transpiler is a JVM process)
- The Databricks CLI with the Lakebridge extension:

```bash
databricks labs install lakebridge
databricks labs lakebridge install-transpile
```

Lakebridge installs to `~/.databricks/labs/lakebridge` (~1 GB, including its own virtualenv). It is a
tool installation, not part of this repository — install it with the commands above.

## Quickstart

```bash
# 1. Backend
uv venv --python 3.12 backend/.venv
uv pip install --python backend/.venv/bin/python -r requirements.txt
cp backend/.env.example backend/.env      # then fill in your own values
cd backend && .venv/bin/python -m uvicorn app.main:app --port 8811

# 2. Frontend (separate shell)
npm --prefix frontend install
npm --prefix frontend run dev -- --port 5173
```

Open <http://localhost:5173>.

The backend port is **8811** and the frontend **5173**; the CORS allowlist and the frontend's default
API base both assume those. See [docs/CODESPACES.md](docs/CODESPACES.md) for running behind a
forwarded port, where you want `VITE_API_BASE=/api` and only one port exposed.

## Configuration

All configuration lives in `backend/.env`, which is git-ignored. Copy `backend/.env.example` and fill
it in.

| Variable | Purpose |
|---|---|
| `DATABRICKS_PROFILE` | CLI profile name. **Empty** means "no config file — authenticate from the environment", which is what containers and CI need. |
| `DATABRICKS_HOST` / `DATABRICKS_TOKEN` | Used when no profile is set. A service principal (`DATABRICKS_CLIENT_ID` / `_SECRET`) is preferable in production. |
| `DATABRICKS_WAREHOUSE_HOSTNAME` / `_HTTP_PATH` | The SQL Warehouse to run against. |
| `DATABRICKS_TARGET_CATALOG` / `_SCHEMA` | Where migrated objects are created. |
| `ALLOWED_ORIGINS` | Comma-separated CORS allowlist. `*` is refused deliberately — this API performs real writes and has no auth model. |
| `REDSHIFT_*`, `STARBURST_*` | Source system credentials. |
| `LLM_ENABLED`, `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL` | Optional natural-language fallback (Anthropic, OpenAI or DeepSeek). Off by default. |

**Never commit `backend/.env`.** It holds live credentials.

## Tests

```bash
cd backend
.venv/bin/python -m pytest -q -m "not slow"   # fast suite, no live warehouse
.venv/bin/python -m pytest -q                 # includes live integration tests
```

Tests marked `slow` hit real Redshift, Starburst and Databricks, and need a populated `.env`.

## Known limitations

Stated plainly rather than discovered later:

- **Views are transpiled but not executed.** A view body references source tables by their original
  names, which do not exist in the target, so creating it fails with `TABLE_OR_VIEW_NOT_FOUND`. The
  converted SQL is returned annotated with why. Views therefore also never register as
  "already migrated".
- **`CHAR(n)` is mis-handled by the Morpheus transpiler** (`UNSUPPORTED_CHAR_OR_VARCHAR_AS_STRING`).
  Prefer `VARCHAR`. This is an upstream defect, not one in this project.
- **Very large schema batches are slow.** A batch expands each table into a DDL item *and* a data
  item, so a schema of large tables can run for tens of minutes. Use a small schema for demos.
- **Starburst UDFs cannot be migrated** — the DDL translators do not cover function bodies, and the
  API rejects the attempt rather than pretending.
- **No authentication.** This is a single-operator tool. Do not expose it on a public URL: anyone
  reaching it can create objects and copy data.

## Layout

```
backend/     FastAPI adapter, connectors, migration engine, tests
frontend/    React + Vite UI
scripts/     One-shot provisioning helpers (idempotent)
samples/     Local SQL fixtures for transpile testing
docs/        Design notes, technology inventory, operational findings
```

See [docs/TECH-STACK.md](docs/TECH-STACK.md) for the full technology inventory.

# Paid-workspace working copy — CUTOVER COMPLETE

Copy of `databrick-proj-migrate`, taken 2026-08-02, pointing at a **different** Databricks
workspace without disturbing the original.

- Original workspace: `<old-workspace>.cloud.databricks.com` (free tier, daily query cap — the
  reason this fork exists)
- This copy targets:  `<workspace>.cloud.databricks.com` (paid)

**The original folder is untouched and still works.** Go back to it any time the quota resets.

**Status: the cutover is done and verified live (2026-08-02).** Everything below is a record of
what was done, not a to-do list. The one thing you may need to redo is the OAuth login, which
expires.

---

## 0. Auth (redo this if anything says "authentication")

```bash
databricks auth login --host https://<workspace>.cloud.databricks.com --profile lakebridge-paid
databricks current-user me -p lakebridge-paid       # verify
```

OAuth U2M — the token lives in the OS keyring, not in this repo. No personal access token is
created or stored anywhere.

## 1. Config — done, in `backend/.env`

```
DATABRICKS_WAREHOUSE_HOSTNAME=<workspace>.cloud.databricks.com
DATABRICKS_WAREHOUSE_HTTP_PATH=/sql/1.0/warehouses/<warehouse-id>
DATABRICKS_PROFILE=lakebridge-paid
DATABRICKS_TARGET_CATALOG=lakebridge_demo
DATABRICKS_TARGET_SCHEMA=g3_migrations
```

Warehouse `<warehouse-id>` = "Serverless Starter Warehouse". Find the id under
Compute → SQL warehouses → the warehouse → Connection details. The warehouses **list** URL does not
contain it.

## 2. Code — done

The five sites that hardcoded `lakebridge-eval` now read `executor.databricks_profile()`
(`executor.py` ×2, `migrate.py`, `databricks_mcp_client.py`), and `LLM_TRANSPILE_CATALOG` follows
`DATABRICKS_TARGET_CATALOG`. **Defaults are unchanged**, so the original folder behaves identically.

Also fixed while moving: `migrate.py` no longer builds a workspace path from a hardcoded personal
email; it resolves the authenticated user at runtime.

## 3. Python environment

The rsync excluded `.venv` and there is no requirements file. Rebuild by cloning the original's:

```bash
uv pip freeze --python ../databrick-proj-migrate/backend/.venv/bin/python > /tmp/reqs.txt
uv venv --python 3.12 backend/.venv
uv pip install --python backend/.venv/bin/python -r /tmp/reqs.txt
```

**Do not add `pyarrow`.** It makes the backend test suite die with a segmentation fault (exit 139).

## 4. Workspace objects

```bash
backend/.venv/bin/python scripts/provision_paid_workspace.py     # idempotent
```

Creates the catalog, three schemas, the `landing` volume, seed tables with rows, both UC functions
(including `mcp_fallback_ping`, which a test needs), and writes a real CSV and a real parquet into
the volume via the Files API before loading them back with `COPY INTO`.

## 5. Lakebridge

`transpile` runs from the local transpiler install and does **not** need workspace state — but it
must be told which transpiler to use, or it will silently prompt and die. That flag is already in
`migrate.py`; see MEMORY.md's cutover section if you hit `EOFError: EOF when reading a line`.

`configure-reconcile` (the reconcile job) has **not** been re-run in this workspace — the job id is
workspace state. Do that only if you need reconcile; see `docs/RECONCILE.md` (serverless: the spec
must use `environments`, not `job_clusters`).

## 6. Running it

```bash
backend/.venv/bin/python -m uvicorn app.main:app --port 8811    # from backend/, port is NOT optional
npm --prefix frontend run dev -- --port 5173                    # CORS allows 5173 only
```

The frontend hardcodes `http://127.0.0.1:8811`, and the backend's CORS allowlist is 5173 only. Any
other port shows a misleading "ADAPTER UNREACHABLE".

**Before trusting anything in the browser, check no stale `uvicorn`/`vite` from the ORIGINAL folder
is still bound to those ports** — that happened during this cutover and the first browser pass was
testing the wrong code:

```bash
lsof -a -p "$(lsof -ti:5173 | head -1)" -d cwd -Fn
```

# Redshift demo source — destroy and recreate

The Redshift cluster bills while it runs, and a *paused* cluster still charges for storage. These
files make the cluster **disposable**: destroy it entirely, recreate one shortly before a demo, run
one command, and the source estate the app reads is back exactly as it was.

Everything here is **generated from the live cluster**, never hand-written — see
`scripts/dump_redshift_demo.py`.

## What is captured

| Schema | Tables | Rows | Routines |
|---|---|---|---|
| `demo_fast_test` | customers, orders, payments, products, regions | 10, 10, 8, 6, 5 | 5 functions + `sp_top_customers` |
| `demo_schema_test` | departments, employees | 5, 5 | — |

**39 rows across 7 tables, 6 routines, 29 SQL statements.**

Not captured, deliberately: `public` (the TICKIT sample set — large, and AWS can recreate it) and
`pg_auto_copy`. Only the two demo schemas the app actually demos against are managed here.

| File | Contents |
|---|---|
| `01_schemas.sql` | `CREATE SCHEMA IF NOT EXISTS` |
| `02_tables.sql` | `DROP TABLE IF EXISTS` + real `CREATE TABLE` from `SHOW TABLE` |
| `03_data.sql` | `INSERT` statements built from real rows |
| `04_functions.sql` | Functions and the stored procedure |

## Runbook

### 1. Before destroying — refresh the dump (optional)

Only needed if the demo data changed since these files were generated.

```bash
backend/.venv/bin/python scripts/dump_redshift_demo.py
```

### 2. Destroy the cluster

Do this in the AWS console or CLI. Skip the final snapshot — these files *are* the backup.

### 3. Recreate before the demo

Create a new Redshift cluster, then put its details into `backend/.env`:

```
REDSHIFT_HOST=<new-cluster-endpoint>
REDSHIFT_PORT=5439
REDSHIFT_DATABASE=dev
REDSHIFT_USER=<user>
REDSHIFT_PASSWORD=<password>
```

The endpoint hostname **will change** when you recreate — that is the one manual step, and the app
will keep failing with `Server refuses SSL` until `.env` matches reality.

### 4. Restore

```bash
backend/.venv/bin/python scripts/restore_redshift_demo.py
```

This replays all four files in order and then verifies object and row counts, so a partial restore
fails loudly rather than leaving the demo half-populated. Roughly a minute, mostly connection setup.

Other modes:

```bash
backend/.venv/bin/python scripts/restore_redshift_demo.py --dry-run
```

```bash
backend/.venv/bin/python scripts/restore_redshift_demo.py --verify-only
```

### 5. Restart the app

```bash
lsof -ti:8811,5173 | xargs kill
```

The backend reads `.env` at import, so it must be restarted after the host changes.

## Running the SQL without Python

The files are ordinary SQL and work in any client — Redshift Query Editor v2, DBeaver, `psql`:

```bash
for f in 01_schemas 02_tables 03_data 04_functions; do psql -h $REDSHIFT_HOST -p 5439 -U $REDSHIFT_USER -d dev -v ON_ERROR_STOP=1 -f scripts/redshift-demo/$f.sql; done
```

Run them **in numbered order**. If you paste them into a GUI editor, paste one file at a time — some
editors split on `;` naively and will tear `sp_top_customers` in half, because its `$$ … $$` body
contains semicolons. `restore_redshift_demo.py` handles that correctly.

## Two things worth knowing

**Functions need a volatility clause.** Redshift rejects `CREATE FUNCTION` without
`IMMUTABLE | STABLE | VOLATILE` (`42P13`). The app's own DDL reconstruction omits it — harmless when
feeding the transpiler, fatal when restoring — so the dump reads the real volatility from
`pg_proc.provolatile` and injects it. This was found by replaying the dump into throwaway schemas;
a syntax check would not have caught it.

**`sp_top_customers` creates a table.** Calling it produces `demo_fast_test.top_customers`. That
table is an *output*, not part of the fixture, so it is not dumped — expect it to be absent on a
fresh restore until the procedure is called.

## Verified

Replayed end to end into throwaway schemas on a live cluster: **29 statements, 0 errors**, all 7
tables at the expected row counts, all 6 routines created, all 5 functions and the procedure
executing and returning correct results. The throwaway schemas were then dropped.

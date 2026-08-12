# Running the Lakebridge Migration Console

Two ports, two commands, one environment variable that decides whether the destructive testing
control is present.

- **Backend (FastAPI adapter)** — port **8811**
- **Frontend (Vite dev server)** — port **5173**

Those numbers are not arbitrary: the backend's CORS allowlist and the frontend's default API base
are both written against them. Changing one means changing the other.

---

## 1. Prerequisites

| Requirement | Why | Check |
|---|---|---|
| Python **3.12** | backend runtime | `python3 --version` |
| Node **20+** | Vite 8 / React 19 | `node --version` |
| **Java 21** | the Morpheus transpiler is a `java -jar` process | `java --version` |
| Databricks CLI | `databricks labs lakebridge` runs through it | `databricks --version` |
| Lakebridge labs project | the actual transpiler | `databricks labs lakebridge --help` |

Java is genuinely required, not optional — a Redshift DDL migration shells out to
`java -jar databricks-morph-plugin.jar`. On macOS, `openjdk@21` is a keg-only Homebrew formula, so
it is not on `PATH` by default; the backend prepends it itself (see `_subprocess_env()` in
`backend/app/executor.py`), but `java --version` failing at a shell means it is not installed at all.

Install Lakebridge once:

```bash
databricks labs install lakebridge
```

```bash
databricks labs lakebridge install-transpile
```

---

## 2. Configure credentials

```bash
cp backend/.env.example backend/.env
```

```bash
chmod 600 backend/.env
```

Fill in Databricks, Redshift and Starburst values. `backend/.env` is git-ignored and must stay that
way — it holds live credentials for three systems.

**Databricks auth — pick one:**

- **Named CLI profile** (normal on a laptop): set `DATABRICKS_PROFILE=<name>` and run
  `databricks auth login --host https://<workspace>.cloud.databricks.com --profile <name>`.
- **Environment auth** (containers, Codespaces, CI): set `DATABRICKS_PROFILE=` — *empty on purpose,
  it means "there is no `~/.databrickscfg`"* — plus `DATABRICKS_HOST` and `DATABRICKS_TOKEN`.

One trap worth knowing: `databricks labs` injects `DATABRICKS_AUTH_TYPE=databricks-cli` into its
child process, which makes Lakebridge ignore a valid `DATABRICKS_TOKEN` and insist on the CLI's
stored OAuth session. When that session expires, migrations fail while browsing keeps working. The
backend pins `auth_type=pat` in the environment-auth case to prevent exactly this.

---

## 3. Install dependencies

```bash
python3 -m venv backend/.venv && backend/.venv/bin/pip install -r requirements.txt
```

```bash
npm --prefix frontend install
```

> **Never add `pyarrow` to `backend/.venv`.** It segfaults the test suite (exit 139). The
> `databricks-sql-connector` warning about it on startup is expected and harmless.

---

## 4. Run — demo mode (testing tools HIDDEN)

This is the mode to present in.

**Terminal 1 — backend:**

```bash
cd backend && .venv/bin/python -m uvicorn app.main:app --port 8811
```

**Terminal 2 — frontend:**

```bash
npm --prefix frontend run dev -- --port 5173
```

Open <http://localhost:5173>.

The rail shows: Migrations, Data explorer, AI Command, Logs. There is **no "testing" item** — not
merely hidden by CSS, but absent from the DOM entirely.

---

## 5. Run — testing mode (testing tools SHOWN)

Identical, except the frontend starts with `VITE_TESTING_TOOLS=1`:

```bash
VITE_TESTING_TOOLS=1 npm --prefix frontend run dev -- --port 5173
```

The backend command is unchanged — the flag is frontend-only.

A **"testing"** item now appears at the bottom of the rail. It resets the migration target schema
(`lakebridge_demo.g3_migrations`) back to its demo baseline, dropping everything except one Redshift
table, one Starburst table, and the MCP probe function, so the next migration is visibly new.

Two deliberate safety properties:

1. **It is a restart-level switch, not an in-app toggle.** Enabling it requires deliberately
   restarting the dev server with the variable set — it cannot happen by accident mid-demo.
2. **Clicking it deletes nothing.** It fetches the schema contents and shows exactly which objects
   would be dropped and which kept. Only the confirm button in that dialog destroys anything.

It drops real Databricks objects. Nothing in Redshift or Starburst is ever written to.

### Quick reference

| | Command (frontend) | "testing" rail item |
|---|---|---|
| **Demo** | `npm --prefix frontend run dev` | absent from the DOM |
| **Testing** | `VITE_TESTING_TOOLS=1 npm --prefix frontend run dev` | present |

To switch modes, **restart the Vite dev server**. `import.meta.env` is inlined at startup, so
exporting the variable in another shell has no effect on a server that is already running.

---

## 6. Running behind a forwarded port (dev tunnel / Codespaces)

Forward **only 5173**. The frontend detects that it is not on localhost and routes API calls through
Vite's same-origin `/api` proxy to the backend, so the browser only ever contacts one host.

This avoids two failures that look nothing like themselves:

- **Mixed content** — an HTTPS page cannot call `http://127.0.0.1:8811` at all, and `127.0.0.1` on a
  tunnel resolves to the *viewer's* machine anyway.
- **The tunnel interstitial** — a browser request to a forwarded port gets an HTML anti-phishing
  warning page until someone clicks through it. `curl` never sees this, so the API looks perfectly
  healthy from a terminal while the app hangs on "loading" in the browser.

No environment variable is needed; the switch is automatic. Setting `VITE_API_BASE` explicitly still
overrides it if you are pointing at a separately hosted adapter.

---

## 7. Verify it is actually working

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8811/runs
```

Then in the browser, confirm the top-right pill reads **ADAPTER LIVE**. That pill reflects the live
`/runs` poll — it is not a decorative badge, so "connecting" or "adapter unreachable" means the
backend genuinely is not answering.

Expand the data explorer and confirm Redshift, Starburst and Databricks all list objects. If
Redshift alone fails with `Server refuses SSL`, that is a misleading driver message for a **paused
cluster** — resume it and retry.

---

## 8. Tests

```bash
cd backend && .venv/bin/python -m pytest -q -m "not slow"
```

The fast suite skips tests that invoke the real Lakebridge CLI and real cloud resources. Drop
`-m "not slow"` to run everything, which takes roughly half an hour and needs live credentials.

---

## 9. Stopping

```bash
lsof -ti:8811,5173 | xargs kill
```

Check for stale servers before trusting any browser result — an old process on 5173 will happily
serve a previous build, including one started in the other mode.

---

## 10. If the Redshift cluster was destroyed

The Redshift cluster is **disposable on purpose** — it bills while running and still charges storage
while paused, so it is destroyed between demos. The two demo schemas live in version control as SQL.

Full runbook: `scripts/redshift-demo/README.md`. The short version:

**1. Create a new Redshift cluster**, then point `backend/.env` at it:

```
REDSHIFT_HOST=<new-cluster-endpoint>
REDSHIFT_PORT=5439
REDSHIFT_DATABASE=dev
REDSHIFT_USER=<user>
REDSHIFT_PASSWORD=<password>
```

The endpoint hostname **changes every time you recreate the cluster**. This is the one step that
cannot be automated, and forgetting it is the most likely thing to go wrong.

**2. Restore the demo source data:**

```bash
backend/.venv/bin/python scripts/restore_redshift_demo.py
```

Replays 29 statements — 7 tables (39 rows), 5 functions and 1 stored procedure across
`demo_fast_test` and `demo_schema_test` — then verifies object and row counts, so a partial restore
fails loudly instead of leaving the demo half-populated. About a minute.

**3. Restart the backend.** It reads `.env` at import, so a running server keeps using the old host.

### Diagnosing `Server refuses SSL`

That message is the Redshift driver's generic error and does **not** mean what it says. The two real
causes:

| Cause | Tell |
|---|---|
| Cluster is **paused** | raw socket returns `FATAL 57P03: You can't connect to your cluster while it is paused` |
| `REDSHIFT_HOST` is **stale** after a recreate | DNS fails, or the endpoint answers as a different cluster |

Note the failure is Redshift-only: Starburst and Databricks browsing keep working, so the app looks
partly healthy rather than plainly broken.

### Regenerating the fixture

Only if the demo data itself changed, and only while the cluster is up:

```bash
backend/.venv/bin/python scripts/dump_redshift_demo.py
```

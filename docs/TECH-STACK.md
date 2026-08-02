# Technology inventory

Everything this project is built from, by layer. Versions are the ones it is actually developed and
tested against — pinned in `requirements.txt` and `frontend/package.json`.

## Languages

| Language | Where | Version |
|---|---|---|
| Python | Backend adapter, connectors, migration engine, provisioning scripts | 3.12 |
| TypeScript | Frontend, in strict mode | ~6.0 |
| SQL | Transpiled DDL, source/target queries | Redshift, Trino and Databricks SQL dialects |

## Frontend

| Component | Choice | Version | Why |
|---|---|---|---|
| UI library | React | 19.2 | — |
| Build tool / dev server | Vite | 8.2 | Fast HMR; its dev-server proxy also gives a same-origin `/api` for forwarded ports |
| Language tooling | TypeScript | ~6.0 | Built with `tsc -b` (project references). `tsc --noEmit` is a no-op in this repo and verifies nothing |
| Linter | oxlint | 1.75 | — |
| Styling | Hand-written CSS with custom properties | — | Token-driven theming (light/dark), no framework |

No CSS framework, component library, or state-management library. State is React context plus local
state; the app is small enough that adding one would cost more than it saves.

## Backend

| Component | Choice | Version | Why |
|---|---|---|---|
| Web framework | FastAPI | 0.141 | Typed request models and a generated OpenAPI schema |
| ASGI server | uvicorn | 0.52 | — |
| Validation | pydantic | 2.13 | Request/response models |
| Config | python-dotenv | 1.2 | Loaded in `app/__init__.py` so module-level config never reads an unloaded environment |
| HTTP client | httpx | 0.28 | Also used for the optional LLM call — no extra SDK dependency |
| Persistence | SQLite (stdlib `sqlite3`) | — | Run/migration/batch history. Every query is `?`-parameterised |
| Tests | pytest | 9.1 | `slow` marker separates live-system integration tests |

## Data connectivity

| System | Library | Version |
|---|---|---|
| Databricks SQL Warehouse | `databricks-sql-connector` | 4.4 |
| Databricks workspace / Unity Catalog | `databricks-sdk` | 0.123 |
| Amazon Redshift | `redshift-connector` | 2.1 |
| Starburst / Trino | `trino` | 0.338 |
| Databricks Managed MCP | `mcp` | 2.0 |

**`pyarrow` is deliberately absent.** `databricks-sql-connector` warns that it is missing and that
cloud-fetch is disabled; that is expected. Installing it changes the connector's fetch path and makes
the test suite terminate with a segmentation fault (exit 139).

## External platform and tools

| Tool | Role |
|---|---|
| Databricks Lakebridge (`databricks labs lakebridge`) | The actual transpiler. Invoked as a subprocess; never called from the browser |
| Morpheus | Lakebridge's deterministic JVM transpiler — needs **Java 21**. Used for Redshift |
| Bladebridge | Lakebridge's LLM-assisted transpiler. Present, not the default path |
| Databricks CLI | Authentication and Lakebridge invocation |
| Unity Catalog | Catalogs, schemas, volumes, functions in the target workspace |
| uv | Python environment and dependency installation |
| npm | Frontend dependencies |
| Dev Containers | Reproducible environment for Codespaces (`.devcontainer/`) |

## Design constraints worth knowing

These are enforced in code, not conventions:

- **No shell.** Every CLI invocation is an argument array via `subprocess`, restricted to an
  allowlist of ten real Lakebridge subcommands. A value containing `;` or `--flag` stays one
  argument.
- **Identifier guards.** Anything interpolated into SQL that cannot be parameterised (table names in
  `SHOW`/`FROM`) passes an alphanumeric-only `_ident()` check first.
- **Output redaction.** Command output is filtered for tokens, keys, passwords and connection
  strings before it reaches a log or an HTTP response.
- **The LLM cannot widen capability.** It selects one action from a closed set, enforced in code
  rather than by prompt; every object it names is re-resolved against live inventory. It never emits
  SQL or DDL.
- **CORS names origins explicitly.** `*` raises at startup, because this API writes real data and has
  no authentication.

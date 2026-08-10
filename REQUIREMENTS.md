# Technical requirements and stack

What this application is built with, and what has to be present for it to run. Versions below are
the ones actually pinned and installed, not aspirational ones.

---

## At a glance

| Layer | Language | Framework / runtime |
|---|---|---|
| Frontend | TypeScript 6 | React 19, Vite 8 |
| Backend | Python 3.12 | FastAPI, Uvicorn |
| State store | SQL | SQLite (stdlib `sqlite3`) |
| Transpiler engine | Java 21 | `databricks-morph-plugin.jar` |
| Migration CLI | Go (wrapper) + Python (project) | Databricks CLI → Lakebridge labs |
| Sources | — | Redshift, Starburst / Trino |
| Target | — | Databricks SQL Warehouse, Unity Catalog |

Roughly 5,600 lines of backend Python and 8,600 lines of frontend TypeScript/CSS, 48 HTTP
endpoints, and 150 test functions across 12 test modules.

---

## Frontend

**TypeScript 6 · React 19 · Vite 8**

| Package | Version | Role |
|---|---|---|
| `react` / `react-dom` | 19.2 | UI |
| `typescript` | 6.0 | type system, `tsc -b` in the build |
| `vite` | 8.2 | dev server, HMR, production bundler |
| `@vitejs/plugin-react` | 6.0 | React fast refresh |
| `oxlint` | 1.75 | linting |

**There are exactly two runtime dependencies: `react` and `react-dom`.** No UI kit, no component
library, no CSS framework, no state-management library, no icon package, no charting library.

That is a deliberate constraint, and it is worth saying out loud in a demo:

- **Design system** — hand-authored CSS custom properties with a four-block theming contract
  (light base → `prefers-color-scheme: dark` → `data-theme="dark"` → `data-theme="light"`), so an
  explicit user choice beats the OS setting. No hardcoded colours anywhere outside the token block.
- **Icons** — ~22 hand-rolled inline SVG glyphs in `Icon.tsx`.
- **State** — React hooks and two small context providers. No Redux, no Zustand, no React Query.
- **Interactions built from scratch** — HTML5 drag-and-drop for migrations, a right-click context
  menu with viewport clamping, a pointer-event pane resizer with keyboard operation and
  `localStorage` persistence, collapsible cards, live-polling progress bars.

Skills this actually exercises: TypeScript generics and discriminated unions, React hook design
(including the rules-of-hooks constraint that shapes how per-row menus are built), CSS grid/flex
layout, accessibility (ARIA roles, `aria-expanded`, keyboard operability, `prefers-reduced-motion`),
and browser-platform APIs — pointer events, drag-and-drop, `useLayoutEffect` measurement.

---

## Backend

**Python 3.12 · FastAPI · Uvicorn**

| Package | Version | Role |
|---|---|---|
| `fastapi` | 0.141 | HTTP API, 48 endpoints |
| `starlette` | 1.3 | ASGI layer under FastAPI |
| `uvicorn` | 0.52 | ASGI server |
| `pydantic` | 2.13 | request/response validation |
| `python-dotenv` | 1.2 | `.env` loading |
| `httpx` | 0.28 | outbound HTTP |
| `pytest` | 9.1 | 150 tests |

### Data access

| Package | Version | Talks to |
|---|---|---|
| `redshift-connector` | 2.1 | Amazon Redshift (source) |
| `trino` | 0.338 | Starburst Galaxy / Trino (source) |
| `databricks-sql-connector` | 4.4 | Databricks SQL Warehouse (target) |
| `databricks-sdk` | 0.123 | workspace API, auth, jobs, Unity Catalog |
| `boto3` | 1.43 | AWS |
| `openpyxl` | 3.1 | `.xlsx` conversion — Databricks SQL has no native Excel reader |

101 pinned packages in total (`requirements.txt`).

### Database

**SQLite**, via Python's standard-library `sqlite3` — no ORM, no SQLAlchemy.

Four tables: `runs`, `events`, `migrations`, `batches`. It is the run/event/audit store: every CLI
invocation, its streamed stdout/stderr, every migration outcome and every batch lives here, which is
what makes the Logs section and the resumable progress polling possible.

Every query is `?`-parameterised — no string-built SQL anywhere.

---

## Java — where and why

**Java 21 is a hard runtime requirement**, even though not one line of Java was written for this
project.

Lakebridge's **Morpheus** transpiler — the deterministic Redshift → Databricks SQL converter — ships
as a JAR and is launched as a subprocess. Its own config declares it literally:

```yaml
remorph:
  name: Morpheus
  dialects: [mssql, redshift, snowflake, synapse]
  command_line:
    - java
    - '-jar'
    - databricks-morph-plugin.jar
```

So every deterministic DDL migration in this app is: **Python → Go CLI → Python labs project → JVM
process → transpiled SQL**.

Two practical consequences the code deals with explicitly:

1. On macOS `openjdk@21` is keg-only, so it is not on `PATH` for a subprocess launched from a server
   process. The backend builds an explicit environment with `JAVA_HOME` and the JDK's `bin` prepended
   rather than assuming the caller's shell.
2. `/usr/bin/java` frequently exists on macOS as a stub that errors with "Unable to locate a Java
   Runtime". Existence on `PATH` does not mean a working JVM, so a known-good JDK is preferred
   unconditionally.

---

## The CLI layer — two languages

This is a common point of confusion, so stated precisely:

| Component | Language | Evidence |
|---|---|---|
| `databricks` CLI | **Go** | a compiled native binary; its strings reference `github.com/databricks/cli` and Go build flags |
| `databricks labs lakebridge` | **Python 3.12** | the labs project installs its own venv under `~/.databricks/labs/lakebridge/state/venv` |
| Morpheus transpiler | **Java** | `java -jar databricks-morph-plugin.jar` |

So "the Lakebridge CLI" is not one thing. It is a **Go binary that spawns a Python project that
spawns a JVM.** That layering is not trivia — it is the direct cause of two real bugs this project
hit: the Go wrapper overriding the auth type it passes to the Python child, and the JVM not being
findable on `PATH`.

Lakebridge itself is an open-source Databricks tool, CLI-only. This application is a web UI over it.

---

## Security engineering

- **No `shell=True`, ever.** Every subprocess call uses an argument array with an explicit allowlist
  of the 10 real Lakebridge subcommands. A malicious request value stays a single `argv` element
  even if it contains shell metacharacters, because no shell is ever invoked.
- **Output redaction** before anything reaches a log view — tokens, passwords, connection strings,
  AWS access-key IDs, PEM private-key blocks. The keyword patterns use alnum-only boundary
  assertions rather than `\b`, because `\b` does not fire inside `snake_case` identifiers, which
  once let `aws_secret_access_key=…` through unredacted.
- **Parameterised SQL** everywhere.
- **CORS allowlist**, never `*` — this API performs real writes and has no auth model.
- **Destructive controls are feature-flagged out of the DOM**, not merely hidden with CSS.

---

## Cloud platforms

| Platform | Role |
|---|---|
| **Databricks** | migration target — SQL Warehouse, Unity Catalog, Jobs, MCP server |
| **Amazon Redshift** | source system |
| **Starburst Galaxy / Trino** | source system |
| **AWS** | Redshift hosting, S3-backed federated catalogs |

Databricks specifics that shaped the design: the workspace is **serverless-only**, so any job spec
must use `environments` rather than `job_clusters`; OAuth (U2M) and personal access tokens behave
differently under `databricks labs`; and Unity Catalog's three-level `catalog.schema.object`
namespace drives the whole target-side model.

---

## Development environment

| Tool | Use |
|---|---|
| Vite dev server + HMR | frontend iteration |
| Uvicorn | backend, port 8811 |
| pytest | 150 tests, `slow` marker separating real-cloud integration tests |
| `.devcontainer` | Codespaces / container support |
| VS Code dev tunnels | sharing a running instance over HTTPS |
| Git / GitHub | version control |

---

## Summary for a demo

> This is a **full-stack TypeScript and Python application**. The frontend is **React 19 with
> TypeScript on Vite**, written with no UI framework — the design system, icon set, drag-and-drop,
> context menus and resizable panes are all hand-built. The backend is **Python 3.12 with FastAPI**,
> exposing 48 endpoints over **SQLite**, and integrating four systems: Redshift, Starburst/Trino,
> Databricks SQL, and the Databricks SDK.
>
> Underneath, it orchestrates the Databricks Lakebridge CLI — which is itself a **Go binary that
> runs a Python project that runs a Java transpiler** — so **Java 21 is a hard runtime dependency**
> even though no Java was written here.
>
> The engineering emphasis is on **safe subprocess execution** (argument arrays and an allowlist,
> never a shell), **secret redaction**, **parameterised SQL**, and a standing rule that the UI never
> shows anything it has not genuinely retrieved.

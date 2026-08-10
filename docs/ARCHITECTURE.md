# Architecture diagrams

Every diagram below was derived by reading the code, not from the design intent. Names, endpoints,
table columns, status strings and polling intervals are the real ones — if a diagram disagrees with
the code, the code has changed and the diagram is a bug.

Rendered natively by GitHub. `docs/architecture.html` is a standalone viewer for the same content.

**Contents**

1. [Process map — system context](#1-process-map--system-context)
2. [Component diagram (UML)](#2-component-diagram-uml)
3. [The three-language CLI chain](#3-the-three-language-cli-chain)
4. [Flowchart — migration engine decision tree](#4-flowchart--migration-engine-decision-tree)
5. [Data flow diagram — level 0](#5-data-flow-diagram--level-0)
6. [Data flow diagram — level 1](#6-data-flow-diagram--level-1-migrate)
7. [Sequence — drag-and-drop migration](#7-sequence--drag-and-drop-migration)
8. [Sequence — whole-schema batch](#8-sequence--whole-schema-batch)
9. [Sequence — AI Command](#9-sequence--ai-command-planconfirmexecute)
10. [Sequence — reconcile](#10-sequence--reconcile-dispatch-vs-completion)
11. [ER diagram](#11-er-diagram--sqlite)
12. [Class diagram (UML)](#12-class-diagram-uml)
13. [State diagrams](#13-state-diagrams)
14. [Block diagram — runtime topology](#14-block-diagram--runtime-topology)
15. [Polling map](#15-polling-map)

---

## 1. Process map — system context

Four external systems. Two are read-only sources, one is the write target, one is the tool chain.

```mermaid
flowchart LR
    user([Operator])

    subgraph app["Lakebridge Migration Console"]
        ui["React UI<br/>:5173"]
        api["FastAPI adapter<br/>:8811"]
        db[("SQLite<br/>runs.db")]
        ui -->|"HTTP · 48 endpoints"| api
        api --- db
    end

    subgraph sources["Sources — READ ONLY"]
        rs[("Amazon Redshift")]
        sb[("Starburst / Trino")]
    end

    subgraph target["Target — READ + WRITE"]
        dbx[("Databricks<br/>SQL Warehouse + Unity Catalog")]
    end

    subgraph tools["Tool chain"]
        cli["Databricks CLI → Lakebridge → Morpheus JVM"]
    end

    user -->|"drag · click · natural language"| ui
    api -->|"metadata · DDL · rows"| rs
    api -->|"metadata · DDL · rows"| sb
    api -->|"CREATE / INSERT / SELECT"| dbx
    api -->|"argv array, never a shell"| cli
    cli -->|"transpiled SQL · job runs"| dbx

    classDef ro fill:#fff3e0,stroke:#e65100,color:#000
    classDef rw fill:#e0f7fa,stroke:#006064,color:#000
    class rs,sb ro
    class dbx rw
```

**Boundary contract.** Nothing is ever written to Redshift or Starburst. Every write lands in
`lakebridge_demo.g3_migrations` on Databricks. Every string crossing back out of a connector passes
through `redact()` first.

---

## 2. Component diagram (UML)

```mermaid
flowchart TB
    subgraph FE["Frontend — TypeScript / React 19"]
        direction TB
        App["App.tsx<br/>5 always-mounted sections"]
        subgraph ctx["Context providers"]
            MA["MigrationActionsProvider<br/>jobs · batches · selection · targetVersion"]
            PV["PreviewProvider"]
        end
        subgraph trees["Data explorer"]
            RT["RedshiftTree"]
            ST["StarburstTree"]
            DT["DatabricksTree<br/>(read-only)"]
        end
        subgraph cards["Result surfaces"]
            MC["MigrationCard"]
            BC["BatchCard"]
            CP["ChatPanel"]
        end
        apis["api.ts · explorerApi.ts<br/>batchApi.ts · chatApi.ts · historyApi.ts"]
        App --> ctx --> trees
        App --> cards
        trees --> apis
        cards --> apis
    end

    subgraph BE["Backend — Python 3.12 / FastAPI"]
        direction TB
        main["main.py<br/>48 routes"]
        chat["chat.py<br/>4 interpretation methods"]
        llm["llm_planner.py"]
        migrate["migrate.py<br/>engine selection"]
        exec["executor.py<br/>argv allowlist · subprocess"]
        tgt["databricks_target.py<br/>shared conn · type map"]
        xlate["starburst_ddl_translator.py"]
        conn["connectors/<br/>redshift · starburst · databricks_browse"]
        redact["redact.py"]
        models["models.py<br/>3 stores"]

        main --> chat
        main --> migrate
        main --> conn
        main --> exec
        chat --> llm
        chat --> migrate
        migrate --> exec
        migrate --> tgt
        migrate --> xlate
        migrate --> conn
        exec -.->|lazy| tgt
        conn --> redact
        migrate --> models
        exec --> models
    end

    store[("SQLite")]
    ext["Databricks CLI (Go)"]

    apis -->|HTTP| main
    models --- store
    exec -->|subprocess| ext
```

`redact.py` and `models.py` are leaves. `executor` and `databricks_target` sit above them, `migrate`
above `executor`, `chat` above `migrate`, `main` on top. **No cycles** — `migrate` imports
`JOB_RUN_URL_RE` and `poll_job_run` *from* `executor`, never the reverse, and `executor` imports
`databricks_target` lazily inside one function so a non-reconcile command never loads the SQL driver.

---

## 3. The three-language CLI chain

The single most misunderstood part of the system, and the direct cause of two real production bugs.

```mermaid
flowchart LR
    py["migrate.py<br/><b>Python 3.12</b>"]
    go["databricks CLI<br/><b>Go</b>"]
    labs["labs lakebridge<br/><b>Python 3.12</b><br/>own venv"]
    jvm["databricks-morph-plugin.jar<br/><b>Java 21</b>"]
    out["Transpiled Databricks SQL"]

    py -->|"argv array<br/>_subprocess_env()"| go
    go -->|"spawns, injecting<br/>DATABRICKS_AUTH_TYPE"| labs
    labs -->|"java -jar"| jvm
    jvm --> out

    bug1["BUG 1 — the Go wrapper injects<br/>auth_type=databricks-cli, so a valid<br/>DATABRICKS_TOKEN is ignored.<br/>Fix: pin auth_type=pat"]
    bug2["BUG 2 — openjdk@21 is keg-only,<br/>so the JVM is not on PATH.<br/>Fix: set JAVA_HOME explicitly"]

    go -.-> bug1
    jvm -.-> bug2

    classDef bug fill:#ffebee,stroke:#b71c1c,color:#000
    class bug1,bug2 bug
```

---

## 4. Flowchart — migration engine decision tree

How `(source_system, object_type)` selects one of four engines.

```mermaid
flowchart TD
    start([Migration requested]) --> force{"force=true?"}
    force -->|no| exists{"Target object<br/>already exists?"}
    force -->|yes| sys
    exists -->|yes| short[/"Short-circuit:<br/>COMPLETED,<br/>'-- ALREADY MIGRATED'"/]
    exists -->|no| sys{"source_system?"}

    sys -->|redshift| rtype{"object_type?"}
    sys -->|starburst| stype{"object_type?"}

    rtype -->|"table · view"| rddl["SHOW TABLE →<br/>lakebridge transpile<br/>+ Morpheus JVM"]
    rtype -->|"procedure"| rproc["SHOW PROCEDURE → transpile"]
    rtype -->|"function"| rfunc["pg_proc reconstruct → transpile"]
    rtype -->|"table-data"| rdata["SELECT rows →<br/>DROP+CREATE+INSERT"]

    stype -->|"table · view<br/>(default path)"| scustom["starburst_ddl_translator<br/>pure Python"]
    stype -->|"table · view<br/>(experimental flag)"| sllm["lakebridge llm-transpile<br/>→ remote job"]
    stype -->|"table-data"| sdata["read_table_rows →<br/>DROP+CREATE+INSERT"]

    rddl --> apply{"object_type<br/>== view?"}
    rproc --> apply
    rfunc --> apply
    scustom --> apply

    apply -->|yes| viewskip[/"NOT executed —<br/>view body references<br/>original table names"/]
    apply -->|no| create["rewrite_ddl_target →<br/>CREATE OR REPLACE in<br/>lakebridge_demo.g3_migrations"]

    sllm --> poll["Poll job to terminal state<br/>(exit 0 = dispatched, not done)"]
    poll --> nowrite[/"Nothing applied to target —<br/>SQL written to workspace folder"/]

    rdata --> verify["SELECT COUNT(*) verify"]
    sdata --> verify

    create --> done([COMPLETED])
    verify --> done
    viewskip --> done
    nowrite --> done
    short --> done

    classDef eng fill:#e8f5e9,stroke:#1b5e20,color:#000
    classDef warn fill:#fff8e1,stroke:#f57f17,color:#000
    class rddl,rproc,rfunc,scustom,rdata,sdata eng
    class viewskip,nowrite,short warn
```

| Engine (`migrations.engine`) | Source | Mechanism |
|---|---|---|
| `lakebridge-transpile` | Redshift | CLI `transpile` + Morpheus JVM — deterministic |
| `starburst-custom-ddl` | Starburst | pure-Python translator — deterministic, seconds |
| `llm-transpile-experimental` | Starburst | CLI `llm-transpile` → remote job — non-deterministic, 5+ min |
| `data-copy` | either | connector `SELECT` → `databricks_target` — not Lakebridge at all |

**Two deliberate non-writes**, both visible above: a transpiled **view** is stored but never executed
(its body references source-side names that do not exist in the flat `{system}_{schema}_{name}`
target convention), and the **LLM path** never applies anything to the target.

---

## 5. Data flow diagram — level 0

```mermaid
flowchart LR
    op([Operator])
    p0["Lakebridge Migration Console"]
    rs[("Redshift")]
    sb[("Starburst")]
    dbx[("Databricks")]
    d1[("runs.db")]

    op -->|"instruction · drag · click"| p0
    p0 -->|"status · DDL · rows · logs"| op
    rs -->|"metadata · DDL · rows"| p0
    sb -->|"metadata · DDL · rows"| p0
    p0 -->|"CREATE · INSERT"| dbx
    dbx -->|"catalogs · preview rows"| p0
    p0 -->|"runs · events · migrations · batches"| d1
    d1 -->|"history · progress"| p0
```

## 6. Data flow diagram — level 1 (migrate)

```mermaid
flowchart TB
    op([Operator])

    p1["1.0 Browse<br/>/explore/*"]
    p2["2.0 Extract source DDL"]
    p3["3.0 Transpile / translate"]
    p4["4.0 Apply to target"]
    p5["5.0 Copy rows"]
    p6["6.0 Record + redact"]

    rs[("Redshift")]
    sb[("Starburst")]
    dbx[("Databricks")]
    cli["Lakebridge CLI + JVM"]
    d1[("migrations")]
    d2[("events")]

    op --> p1
    p1 <--> rs
    p1 <--> sb
    p1 <--> dbx
    p1 -->|"chosen object"| p2
    p2 -->|"SHOW TABLE / SHOW CREATE TABLE"| rs
    p2 --> sb
    p2 -->|"source_ddl"| p3
    p3 -->|"argv"| cli
    cli -->|"transpiled SQL"| p3
    p3 -->|"output_ddl"| p4
    p4 -->|"CREATE OR REPLACE"| dbx
    p2 -.->|"table-data only"| p5
    p5 -->|"SELECT"| rs
    p5 --> sb
    p5 -->|"chunked INSERT (bound params)"| dbx
    p4 --> p6
    p5 --> p6
    p6 --> d1
    p6 --> d2
    p6 -->|"status · row_count"| op

    classDef trust fill:#fce4ec,stroke:#880e4f,color:#000
    class p6 trust
```

**Process 6.0 is the trust boundary.** No text reaches `events.message` or `migrations.error`
without passing `redact()`; CLI output passes `strip_ansi()` first.

---

## 7. Sequence — drag-and-drop migration

```mermaid
sequenceDiagram
    autonumber
    actor U as Operator
    participant Row as DraggableRow
    participant Zone as TargetDropZone
    participant Ctx as MigrationActions
    participant API as FastAPI
    participant Mig as migrate.py
    participant Src as Redshift/Starburst
    participant CLI as Lakebridge + JVM
    participant DBX as Databricks

    U->>Row: dragstart
    Row->>Row: setData(DRAG_MIME, encodeDrag(obj))
    U->>Zone: drop
    Zone->>Ctx: handleDrop(obj)

    alt table or view
        Ctx->>API: POST /migrate/{sys}/table-and-data/...
    else routine
        Ctx->>API: POST /migrate/{sys}/ddl/...
    end

    Note over Ctx: POST does not resolve until terminal —<br/>so polling starts immediately
    Ctx->>Ctx: startJob() → pollForPickup every 2000 ms

    API->>Mig: migrate_and_copy_*
    Mig->>DBX: object_exists() (sampled BEFORE ddl step)
    Mig->>Src: SHOW TABLE / SHOW CREATE TABLE
    Src-->>Mig: source_ddl
    Mig->>CLI: transpile (argv array)
    CLI-->>Mig: output_ddl
    Mig->>DBX: CREATE OR REPLACE
    Mig->>Src: SELECT rows
    Mig->>DBX: chunked INSERT (bound params)
    Mig->>DBX: SELECT COUNT(*) verify
    Mig-->>API: Migration(status=completed, row_count)

    loop until terminal
        Ctx->>API: GET /migrations
        API-->>Ctx: [...]
    end

    API-->>Ctx: migration
    Ctx->>Ctx: stopPolling + bumpTargetVersion()
    Ctx-->>U: MigrationCard COMPLETED
    Note over Ctx: targetVersion bump makes the open<br/>Databricks tree node refetch
```

## 8. Sequence — whole-schema batch

```mermaid
sequenceDiagram
    autonumber
    actor U as Operator
    participant Tree as SchemaNode
    participant Ctx as MigrationActions
    participant Dlg as ConfirmDialog
    participant API as FastAPI
    participant Mig as migrate.py
    participant Th as Worker thread
    participant Store as batch_store

    U->>Tree: click "batch migrate schema"<br/>or right-click → Batch migrate schema
    Tree->>Ctx: requestSchemaBatch(schema, catalog?)
    Ctx->>Dlg: open (includeData checkbox)
    U->>Dlg: Start batch now
    Dlg->>Ctx: confirmSchemaBatch()

    alt catalog present
        Ctx->>API: POST /migrate/starburst/catalog/{c}/schema/{s}/batch
    else
        Ctx->>API: POST /migrate/redshift/schema/{s}/batch
    end

    API->>Mig: build items / start_batch
    Mig->>Store: create(total_items)
    Mig->>Th: daemon thread
    API-->>Ctx: BatchSummary(status=pending)
    Note over API,Ctx: returns immediately — unlike single migrations

    loop per item, sequential, never aborts
        Th->>Th: _run_single_batch_item
        Th->>Store: add_migration(id)
    end
    Th->>Store: COMPLETED or COMPLETED_WITH_ERRORS

    loop every 2500 ms
        Ctx->>API: GET /batches/{id}
        API-->>Ctx: counts + per-item migrations
    end
    Ctx-->>U: BatchCard progress → terminal
```

A batch **never aborts on a failed item** — a per-item exception synthesises a FAILED Migration and
the loop continues. The terminal status is `completed_with_errors` rather than `completed`, which is
why a failure can never be presented as a plain success.

## 9. Sequence — AI Command (plan→confirm→execute)

```mermaid
sequenceDiagram
    autonumber
    actor U as Operator
    participant CP as ChatPanel
    participant API as FastAPI
    participant Chat as chat.py
    participant Inv as Live inventory
    participant LLM as llm_planner
    participant Mig as migrate.py

    U->>CP: "migrate the regions table and its data"
    CP->>API: POST /chat/plan
    API->>Chat: parse_instruction()

    Note over Chat: 4 methods, in order
    Chat->>Inv: resolve names against real systems
    alt 1 — deterministic verb regex
        Chat-->>API: plan
    else 2 — Databricks data question
        Chat-->>API: plan (safe SELECT gate)
    else 3 — MCP fallback (disabled)
        Chat-->>API: refusal
    else 4 — LLM fallback
        Chat->>LLM: interpret(instruction, inventory)
        LLM-->>Chat: candidate action
        Note over Chat: GUARDRAIL — kind allowlist,<br/>field whitelist, identifier regex,<br/>then re-resolve against live systems
        Chat-->>API: plan or refusal
    end

    API-->>CP: {understood, plan_id, action, endpoint, explanation}
    CP-->>U: plan card — nothing has executed
    U->>CP: Review & confirm → Execute
    CP->>API: POST /chat/execute {plan_id}
    API->>Chat: resolve_plan → execute_plan
    Chat->>Mig: dispatch on action.kind
    Note over Chat,Mig: starburst DDL always uses the<br/>deterministic path, never the LLM one
    Mig-->>API: migration_id / batch_id / run_id
    API-->>CP: result handle

    loop every 1500 ms until terminal
        CP->>API: GET /migrations/{id} | /batches/{id} | /runs/{id}
    end
    CP-->>U: MigrationCard / BatchCard / run pill
```

**The plan step never executes anything.** Refusal is the default: ambiguity, type-hint conflicts and
unresolvable names all return `understood: false` rather than a guess.

## 10. Sequence — reconcile (dispatch vs completion)

The one flow where CLI exit code 0 does **not** mean "finished".

```mermaid
sequenceDiagram
    autonumber
    participant API as FastAPI
    participant Ex as executor.py
    participant CLI as Lakebridge CLI
    participant Job as Databricks Job
    participant Meta as reconcile_meta tables
    participant Store as run_store

    API->>Ex: run_command_async(run_id, "reconcile")
    Ex->>Store: status = running
    Ex->>CLI: subprocess (input="no\n")
    CLI->>Job: trigger job run
    CLI-->>Ex: exit 0 + "/jobs/{id}/runs/{run}"
    Note over Ex: exit 0 means DISPATCHED, not done.<br/>Run stays "running".
    Ex->>Ex: JOB_RUN_URL_RE scrape

    loop every 10 s, up to 480 s
        Ex->>Job: databricks jobs get-run
        Job-->>Ex: life_cycle_state
    end

    Ex->>Meta: SELECT from reconcile_meta.main<br/>(matched by dispatch time — no shared id)
    Ex->>Meta: SELECT from reconcile_meta.metrics
    Meta-->>Ex: reconciliation_passed + metrics
    Ex->>Store: set_result(...)
    Ex->>Store: completed / failed
```

`reconciliation_passed` is deliberately **separate** from the Run's completed/failed: a genuine data
mismatch is a *successful run with a negative verdict*, not a technical failure.

---

## 11. ER diagram — SQLite

```mermaid
erDiagram
    RUNS ||--o{ EVENTS : "run_id (only declared FK)"
    BATCHES ||..o{ MIGRATIONS : "migration_ids_json (implicit)"

    RUNS {
        TEXT id PK "run_1, run_2 ..."
        TEXT command "CLI subcommand"
        TEXT args_json "JSON array"
        TEXT status "queued|running|completed|failed"
        TEXT started_at
        TEXT ended_at
        INTEGER exit_code
        TEXT result_json "reconcile payload only"
    }

    EVENTS {
        INTEGER id PK "AUTOINCREMENT"
        TEXT run_id FK "REFERENCES runs(id)"
        TEXT timestamp
        TEXT type "stdout|stderr|status"
        TEXT message "always redacted"
    }

    MIGRATIONS {
        TEXT id PK "mig_1, mig_2 ..."
        TEXT source_system "redshift|starburst"
        TEXT object_type "table|view|function|procedure|table-data"
        TEXT object_name "qualified"
        TEXT engine "4 MigrationEngine values"
        TEXT status "reuses RunStatus"
        TEXT source_ddl
        TEXT output_ddl
        TEXT error "always redacted"
        INTEGER row_count
        TEXT started_at
        TEXT ended_at
        TEXT target_catalog "added by ALTER"
        TEXT target_schema "added by ALTER"
        TEXT target_table "added by ALTER"
    }

    BATCHES {
        TEXT id PK "batch_1, batch_2 ..."
        TEXT status "pending|running|completed|completed_with_errors"
        INTEGER total_items
        TEXT migration_ids_json "JSON array of migrations.id"
        TEXT created_at
        TEXT started_at
        TEXT ended_at
    }
```

Three facts a naive reading would get wrong:

- **`runs` and `migrations` are unrelated.** No column links them. A `Run` is one CLI invocation; a
  `Migration` is an extract → transpile → apply. They share only the `RunStatus` enum.
- **`batches` → `migrations` is not a foreign key.** There is no `batch_id` column on `migrations`;
  the link is a JSON array on the parent, appended one id at a time.
- **`migrations.target_*` exist only via `ALTER TABLE`.** They were never added back into the
  `CREATE TABLE` text, so a fresh database still gets them from the idempotent retrofit path.

`events.run_id` is the only declared FK, and SQLite does not enforce it — `PRAGMA foreign_keys=ON`
is never issued.

---

## 12. Class diagram (UML)

### Backend

```mermaid
classDiagram
    class Run {
        +str id
        +str command
        +list~str~ args
        +RunStatus status
        +str started_at
        +str ended_at
        +int exit_code
        +list~Event~ events
        +dict result
    }
    class Event {
        +int id
        +str run_id
        +str timestamp
        +EventType type
        +str message
    }
    class Migration {
        +str id
        +str source_system
        +str object_type
        +str object_name
        +MigrationEngine engine
        +RunStatus status
        +str source_ddl
        +str output_ddl
        +str error
        +int row_count
        +str target_catalog
        +str target_schema
        +str target_table
    }
    class Batch {
        +str id
        +BatchStatus status
        +int total_items
        +list~str~ migration_ids
    }

    class RunStore {
        -Lock _lock
        +create(command, args) Run
        +get(run_id) Run
        +list() list~Run~
        +set_status(run_id, status, exit_code)
        +set_result(run_id, result)
        +add_event(run_id, type, message) Event
    }
    class MigrationStore {
        +create(source_system, object_type, object_name, engine) Migration
        +update(mig_id, ...) void
        +get(mig_id) Migration
        +list() list~Migration~
    }
    class BatchStore {
        +create(total_items) Batch
        +add_migration(batch_id, migration_id)
        +set_status(batch_id, status)
        +get(batch_id) Batch
    }

    class RunStatus {
        <<enumeration>>
        queued
        running
        completed
        failed
    }
    class EventType {
        <<enumeration>>
        stdout
        stderr
        status
    }
    class BatchStatus {
        <<enumeration>>
        pending
        running
        completed
        completed_with_errors
    }
    class MigrationEngine {
        <<enumeration>>
        lakebridge-transpile
        llm-transpile-experimental
        data-copy
        starburst-custom-ddl
    }

    RunStore "1" --> "*" Run
    Run "1" *-- "*" Event
    MigrationStore "1" --> "*" Migration
    BatchStore "1" --> "*" Batch
    Batch ..> Migration : ids only
    Run --> RunStatus
    Event --> EventType
    Migration --> RunStatus
    Migration --> MigrationEngine
    Batch --> BatchStatus
```

### Frontend types

```mermaid
classDiagram
    class DragObject {
        +system: redshift|starburst
        +objectType: table|view|procedure|function|udf
        +catalog?: string
        +schema: string
        +name: string
    }
    class Job {
        +key: string
        +system: string
        +objectType: string
        +name: string
        +action: ddl|ddl-custom|data|create-and-copy
        +triggeredAt: string
        +migration: Migration|null
        +clientError: string|null
        +settled: boolean
    }
    class MigrationActionsValue {
        <<interface>>
        +targetVersion: number
        +jobs: Job[]
        +batches: TrackedBatch[]
        +selectMode: boolean
        +handleDrop(obj) void
        +runDdlMigration(obj) void
        +runDdlMigrationCustom(obj) void
        +runCreateAndCopy(obj) void
        +requestDataCopy(system, schema, table, catalog?) void
        +requestSchemaBatch(schema, catalog?) void
        +submitSelectedBatch() void
    }
    class PreviewTarget {
        <<union>>
        +kind: table|routine
        +system: redshift|starburst|databricks
    }
    class TrackedBatch {
        +key: string
        +label: string
        +batch: BatchSummary
    }

    MigrationActionsValue --> Job
    MigrationActionsValue --> TrackedBatch
    MigrationActionsValue ..> DragObject
```

---

## 13. State diagrams

```mermaid
stateDiagram-v2
    direction LR
    [*] --> queued : store.create()
    queued --> running : set_status(RUNNING)
    running --> completed : exit code 0
    running --> failed : non-zero / timeout / disallowed
    completed --> [*]
    failed --> [*]

    note right of running
        reconcile stays here through
        the whole job poll — exit 0
        only means "dispatched"
    end note
```

```mermaid
stateDiagram-v2
    direction LR
    [*] --> pending : batch_store.create()
    pending --> running : first item starts
    running --> completed : every item COMPLETED
    running --> completed_with_errors : any item FAILED
    completed --> [*]
    completed_with_errors --> [*]

    note right of completed_with_errors
        Exists so a partially failed batch
        can never render as a plain success
    end note
```

---

## 14. Block diagram — runtime topology

```mermaid
block-beta
    columns 3

    browser["Browser<br/>localhost:5173"]:3
    space:3
    vite["Vite dev server :5173<br/>same-origin /api proxy"]:3
    space:3
    fastapi["FastAPI / Uvicorn :8811"]:3
    space:3
    sqlite[("SQLite<br/>runs.db")]
    cli["Databricks CLI (Go)<br/>→ Lakebridge (Python)<br/>→ Morpheus (JVM)"]
    conns["Connectors"]
    space:3
    redshift[("Redshift<br/>:5439")]
    starburst[("Starburst<br/>:443")]
    databricks[("Databricks<br/>SQL Warehouse")]

    browser --> vite
    vite --> fastapi
    fastapi --> sqlite
    fastapi --> cli
    fastapi --> conns
    conns --> redshift
    conns --> starburst
    conns --> databricks
    cli --> databricks
```

Through a dev tunnel or Codespace, **only 5173 is forwarded**. The frontend detects a non-localhost
origin and routes through Vite's same-origin `/api` proxy, which avoids both mixed-content blocking
and the tunnel's anti-phishing interstitial.

---

## 15. Polling map

Every timer in the frontend, with what stops it.

```mermaid
flowchart LR
    subgraph timers["Frontend polling"]
        a["App — 3000 ms<br/>GET /runs<br/>drives ADAPTER LIVE"]
        b["pollForPickup — 2000 ms<br/>GET /migrations"]
        c["pollBatch — 2500 ms<br/>GET /batches/{id}"]
        d["ChatPanel — 1500 ms<br/>migrations | batches | runs"]
        e["RunDetail — 1500 ms<br/>GET /runs/{id} + /events"]
        f["ReconcileView — 2500 ms<br/>GET /runs/{id}/reconcile"]
        g["HistoryList — 4000 ms<br/>GET /history"]
    end

    a -->|"unmount only"| stop([stop])
    b -->|"migration terminal<br/>or POST settles"| stop
    c -->|"completed / completed_with_errors"| stop
    d -->|"result terminal"| stop
    e -->|"run terminal"| stop
    f -->|"result non-null"| stop
    g -->|"unmount only"| stop
```

`pollForPickup` exists because the migrate `POST` does **not** resolve until the migration reaches a
terminal state — without polling, the UI would show nothing at all for the entire run.

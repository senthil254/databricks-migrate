"""Run / event data model, backed by SQLite so state survives a server restart.

Public interface (RunStore) is unchanged from the G1 in-memory version —
main.py and executor.py don't need to know the backing store changed.
"""
from __future__ import annotations

import pathlib
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

DEFAULT_DB_PATH = pathlib.Path(__file__).resolve().parents[1] / "_data" / "runs.db"


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EventType(str, Enum):
    STDOUT = "stdout"
    STDERR = "stderr"
    STATUS = "status"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Event:
    id: int
    run_id: str
    timestamp: str
    type: EventType
    message: str


@dataclass
class Run:
    id: str
    command: str
    args: list[str]
    status: RunStatus = RunStatus.QUEUED
    started_at: str | None = None
    ended_at: str | None = None
    exit_code: int | None = None
    events: list[Event] = field(default_factory=list)
    # G4: real discovered result payload (e.g. reconcile's row/column
    # comparison detail, pulled from the real reconcile_meta.* tables — see
    # executor.py's reconcile-completion handling). None for every other
    # command and for a reconcile run that hasn't reached a real terminal
    # job state yet.
    result: dict | None = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    command TEXT NOT NULL,
    args_json TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    exit_code INTEGER,
    result_json TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id),
    timestamp TEXT NOT NULL,
    type TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_run_id ON events(run_id);
CREATE TABLE IF NOT EXISTS migrations (
    id TEXT PRIMARY KEY,
    source_system TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_name TEXT NOT NULL,
    engine TEXT NOT NULL,
    status TEXT NOT NULL,
    source_ddl TEXT,
    output_ddl TEXT,
    error TEXT,
    row_count INTEGER,
    started_at TEXT,
    ended_at TEXT
);
CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    total_items INTEGER NOT NULL,
    migration_ids_json TEXT NOT NULL,
    created_at TEXT,
    started_at TEXT,
    ended_at TEXT
);
"""


class RunStore:
    """SQLite-backed store for runs and their events. Thread-safe."""

    def __init__(self, db_path: pathlib.Path | str = DEFAULT_DB_PATH) -> None:
        self._db_path = pathlib.Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # check_same_thread=False: runs execute on background threads (executor.py)
        # while requests are served on the FastAPI thread; the module-level lock
        # around every call below serialises actual access.
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._run_counter_lock = threading.Lock()
        self._ensure_result_column()

    def _ensure_result_column(self) -> None:
        """G4: `runs` predates `result_json` — CREATE TABLE IF NOT EXISTS
        above doesn't retrofit existing on-disk DB files, so add the column
        explicitly for any DB created before this change. Idempotent."""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(runs)").fetchall()}
        if "result_json" not in cols:
            self._conn.execute("ALTER TABLE runs ADD COLUMN result_json TEXT")
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _next_run_id(self) -> str:
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM runs")
            n = cur.fetchone()[0]
            return f"run_{n + 1}"

    def create(self, command: str, args: list[str]) -> Run:
        import json as _json

        run_id = self._next_run_id()
        with self._lock:
            self._conn.execute(
                "INSERT INTO runs (id, command, args_json, status) VALUES (?, ?, ?, ?)",
                (run_id, command, _json.dumps(args), RunStatus.QUEUED.value),
            )
            self._conn.commit()
        return Run(id=run_id, command=command, args=args, status=RunStatus.QUEUED)

    def get(self, run_id: str) -> Run | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, command, args_json, status, started_at, ended_at, exit_code, result_json "
                "FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            events = self._events_for(run_id)
        return self._row_to_run(row, events)

    def list(self) -> list[Run]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, command, args_json, status, started_at, ended_at, exit_code, result_json "
                "FROM runs ORDER BY id"
            ).fetchall()
            return [self._row_to_run(r, self._events_for(r[0])) for r in rows]

    def set_result(self, run_id: str, result: dict) -> None:
        """G4: stores the real discovered result payload for a run (currently
        only used for `reconcile`'s row/column comparison detail). Kept
        separate from set_status so a caller can attach the detail once it's
        actually available, independent of the status transition itself."""
        import json as _json

        with self._lock:
            self._conn.execute(
                "UPDATE runs SET result_json = ? WHERE id = ?",
                (_json.dumps(result), run_id),
            )
            self._conn.commit()

    def set_status(self, run_id: str, status: RunStatus, exit_code: int | None = None) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT started_at FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
            started_at = row[0] if row else None
            if status == RunStatus.RUNNING and started_at is None:
                started_at = _now()
            ended_at = _now() if status in (RunStatus.COMPLETED, RunStatus.FAILED) else None
            self._conn.execute(
                "UPDATE runs SET status = ?, started_at = COALESCE(started_at, ?), "
                "ended_at = COALESCE(?, ended_at), exit_code = COALESCE(?, exit_code) "
                "WHERE id = ?",
                (status.value, started_at, ended_at, exit_code, run_id),
            )
            self._conn.commit()

    def add_event(self, run_id: str, event_type: EventType, message: str) -> Event:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO events (run_id, timestamp, type, message) VALUES (?, ?, ?, ?)",
                (run_id, _now(), event_type.value, message),
            )
            self._conn.commit()
            event_id = cur.lastrowid
        return Event(id=event_id, run_id=run_id, timestamp=_now(), type=event_type, message=message)

    def _events_for(self, run_id: str) -> list[Event]:
        rows = self._conn.execute(
            "SELECT id, timestamp, type, message FROM events WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        return [
            Event(id=r[0], run_id=run_id, timestamp=r[1], type=EventType(r[2]), message=r[3])
            for r in rows
        ]

    @staticmethod
    def _row_to_run(row, events: list[Event]) -> Run:  # noqa: ANN001
        import json as _json

        run_id, command, args_json, status, started_at, ended_at, exit_code, result_json = row
        return Run(
            id=run_id,
            command=command,
            args=_json.loads(args_json),
            status=RunStatus(status),
            started_at=started_at,
            ended_at=ended_at,
            exit_code=exit_code,
            events=events,
            result=_json.loads(result_json) if result_json else None,
        )


class MigrationEngine(str, Enum):
    LAKEBRIDGE_TRANSPILE = "lakebridge-transpile"  # deterministic, Redshift
    LLM_TRANSPILE_EXPERIMENTAL = "llm-transpile-experimental"  # non-deterministic, Starburst
    DATA_COPY = "data-copy"  # not Lakebridge at all — see MEMORY.md G3.2 entry
    STARBURST_CUSTOM_DDL = "starburst-custom-ddl"  # G7 — deterministic, no Lakebridge/LLM


@dataclass
class Migration:
    id: str
    source_system: str  # "redshift" | "starburst"
    object_type: str  # "table" | "view" | "function" | "procedure"
    object_name: str
    engine: MigrationEngine
    status: RunStatus = RunStatus.QUEUED
    source_ddl: str | None = None
    output_ddl: str | None = None
    error: str | None = None
    row_count: int | None = None
    started_at: str | None = None
    ended_at: str | None = None
    # G8: explicit real target location, populated by migrate.py at
    # creation time from the values it already computes (TARGET_CATALOG/
    # TARGET_SCHEMA constants + the table name it builds) instead of left
    # implicit/reconstructed by callers. None where no real target table
    # exists (e.g. a DDL-only migration that produced no live table).
    target_catalog: str | None = None
    target_schema: str | None = None
    target_table: str | None = None


class MigrationStore:
    """SQLite-backed store for migration attempts. Deliberately separate
    from RunStore's Run/Event model — a migration isn't a single CLI
    invocation, it's DDL extraction + (transpile or llm-transpile) +
    optionally a real data copy, and callers need to know which `engine`
    produced a result, per PLAN.md's G3.2 requirement that Starburst's
    experimental path never look identical to Redshift's deterministic one.
    """

    def __init__(self, db_path: pathlib.Path | str = DEFAULT_DB_PATH) -> None:
        self._db_path = pathlib.Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._counter_lock = threading.Lock()
        self._ensure_target_columns()

    def _ensure_target_columns(self) -> None:
        """G8: `migrations` predates target_catalog/target_schema/target_table
        — CREATE TABLE IF NOT EXISTS above doesn't retrofit existing on-disk
        DB files (see RunStore._ensure_result_column for the same pattern
        used when result_json was added). Additive, idempotent, default NULL
        so existing rows are unaffected."""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(migrations)").fetchall()}
        for col in ("target_catalog", "target_schema", "target_table"):
            if col not in cols:
                self._conn.execute(f"ALTER TABLE migrations ADD COLUMN {col} TEXT")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _next_id(self) -> str:
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM migrations")
            n = cur.fetchone()[0]
            return f"mig_{n + 1}"

    def create(self, source_system: str, object_type: str, object_name: str, engine: MigrationEngine) -> Migration:
        mig_id = self._next_id()
        with self._lock:
            self._conn.execute(
                "INSERT INTO migrations (id, source_system, object_type, object_name, engine, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (mig_id, source_system, object_type, object_name, engine.value, RunStatus.QUEUED.value),
            )
            self._conn.commit()
        return Migration(
            id=mig_id, source_system=source_system, object_type=object_type,
            object_name=object_name, engine=engine,
        )

    def update(
        self, mig_id: str, *, status: RunStatus | None = None, source_ddl: str | None = None,
        output_ddl: str | None = None, error: str | None = None, row_count: int | None = None,
        started: bool = False, ended: bool = False,
        target_catalog: str | None = None, target_schema: str | None = None, target_table: str | None = None,
    ) -> None:
        with self._lock:
            fields, values = [], []
            if status is not None:
                fields.append("status = ?"); values.append(status.value)
            if source_ddl is not None:
                fields.append("source_ddl = ?"); values.append(source_ddl)
            if output_ddl is not None:
                fields.append("output_ddl = ?"); values.append(output_ddl)
            if error is not None:
                fields.append("error = ?"); values.append(error)
            if row_count is not None:
                fields.append("row_count = ?"); values.append(row_count)
            if target_catalog is not None:
                fields.append("target_catalog = ?"); values.append(target_catalog)
            if target_schema is not None:
                fields.append("target_schema = ?"); values.append(target_schema)
            if target_table is not None:
                fields.append("target_table = ?"); values.append(target_table)
            if started:
                fields.append("started_at = ?"); values.append(_now())
            if ended:
                fields.append("ended_at = ?"); values.append(_now())
            values.append(mig_id)
            self._conn.execute(f"UPDATE migrations SET {', '.join(fields)} WHERE id = ?", values)
            self._conn.commit()

    def get(self, mig_id: str) -> Migration | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, source_system, object_type, object_name, engine, status, "
                "source_ddl, output_ddl, error, row_count, started_at, ended_at, "
                "target_catalog, target_schema, target_table "
                "FROM migrations WHERE id = ?",
                (mig_id,),
            ).fetchone()
        return self._row_to_migration(row) if row else None

    def list(self) -> list[Migration]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, source_system, object_type, object_name, engine, status, "
                "source_ddl, output_ddl, error, row_count, started_at, ended_at, "
                "target_catalog, target_schema, target_table "
                "FROM migrations ORDER BY id"
            ).fetchall()
        return [self._row_to_migration(r) for r in rows]

    @staticmethod
    def _row_to_migration(row) -> Migration:  # noqa: ANN001
        (mig_id, source_system, object_type, object_name, engine, status,
         source_ddl, output_ddl, error, row_count, started_at, ended_at,
         target_catalog, target_schema, target_table) = row
        return Migration(
            id=mig_id, source_system=source_system, object_type=object_type,
            object_name=object_name, engine=MigrationEngine(engine), status=RunStatus(status),
            source_ddl=source_ddl, output_ddl=output_ddl, error=error, row_count=row_count,
            started_at=started_at, ended_at=ended_at,
            target_catalog=target_catalog, target_schema=target_schema, target_table=target_table,
        )


migration_store = MigrationStore()


class BatchStatus(str, Enum):
    """A batch's own status is derived from its member Migrations, never
    reported independently of them — see G3.4: a batch must not say
    "completed" if any real member migration failed, only
    COMPLETED_WITH_ERRORS does that honestly (mirrors the "never hide a
    real failure" rule already established for CHAR(1)/VARCHAR(20) in
    test_migrate.py)."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"


@dataclass
class Batch:
    id: str
    status: BatchStatus
    total_items: int
    migration_ids: list[str] = field(default_factory=list)
    created_at: str | None = None
    started_at: str | None = None
    ended_at: str | None = None


class BatchStore:
    """SQLite-backed store for migration batches. Deliberately just an
    ordered list of Migration ids plus an overall status — the real
    per-item detail (source_ddl/output_ddl/error/engine/...) always lives
    in MigrationStore, never duplicated here, so a batch's members are
    always the same live records single-object endpoints already produce."""

    def __init__(self, db_path: pathlib.Path | str = DEFAULT_DB_PATH) -> None:
        self._db_path = pathlib.Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _next_id(self) -> str:
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM batches")
            n = cur.fetchone()[0]
            return f"batch_{n + 1}"

    def create(self, total_items: int) -> Batch:
        import json as _json

        batch_id = self._next_id()
        created_at = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO batches (id, status, total_items, migration_ids_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (batch_id, BatchStatus.PENDING.value, total_items, _json.dumps([]), created_at),
            )
            self._conn.commit()
        return Batch(id=batch_id, status=BatchStatus.PENDING, total_items=total_items, created_at=created_at)

    def add_migration(self, batch_id: str, migration_id: str) -> None:
        import json as _json

        with self._lock:
            row = self._conn.execute(
                "SELECT migration_ids_json FROM batches WHERE id = ?", (batch_id,)
            ).fetchone()
            if row is None:
                return
            ids = _json.loads(row[0])
            ids.append(migration_id)
            self._conn.execute(
                "UPDATE batches SET migration_ids_json = ? WHERE id = ?",
                (_json.dumps(ids), batch_id),
            )
            self._conn.commit()

    def set_status(self, batch_id: str, status: BatchStatus, *, started: bool = False, ended: bool = False) -> None:
        with self._lock:
            fields, values = ["status = ?"], [status.value]
            if started:
                fields.append("started_at = ?"); values.append(_now())
            if ended:
                fields.append("ended_at = ?"); values.append(_now())
            values.append(batch_id)
            self._conn.execute(f"UPDATE batches SET {', '.join(fields)} WHERE id = ?", values)
            self._conn.commit()

    def get(self, batch_id: str) -> Batch | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, status, total_items, migration_ids_json, created_at, started_at, ended_at "
                "FROM batches WHERE id = ?",
                (batch_id,),
            ).fetchone()
        return self._row_to_batch(row) if row else None

    def list(self) -> list[Batch]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, status, total_items, migration_ids_json, created_at, started_at, ended_at "
                "FROM batches ORDER BY id"
            ).fetchall()
        return [self._row_to_batch(r) for r in rows]

    @staticmethod
    def _row_to_batch(row) -> Batch:  # noqa: ANN001
        import json as _json

        batch_id, status, total_items, migration_ids_json, created_at, started_at, ended_at = row
        return Batch(
            id=batch_id, status=BatchStatus(status), total_items=total_items,
            migration_ids=_json.loads(migration_ids_json),
            created_at=created_at, started_at=started_at, ended_at=ended_at,
        )


batch_store = BatchStore()


store = RunStore()

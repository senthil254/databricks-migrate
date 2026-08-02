import sqlite3
import tempfile
from pathlib import Path

from app.models import EventType, MigrationEngine, MigrationStore, RunStatus, RunStore


def test_create_get_list():
    with tempfile.TemporaryDirectory() as d:
        s = RunStore(Path(d) / "t.db")
        run = s.create("describe-transpile", [])
        assert run.status == RunStatus.QUEUED
        fetched = s.get(run.id)
        assert fetched is not None
        assert fetched.id == run.id
        assert s.list() == [fetched] or len(s.list()) == 1


def test_get_missing_returns_none():
    with tempfile.TemporaryDirectory() as d:
        s = RunStore(Path(d) / "t.db")
        assert s.get("nope") is None


def test_set_status_transitions_and_timestamps():
    with tempfile.TemporaryDirectory() as d:
        s = RunStore(Path(d) / "t.db")
        run = s.create("analyze", ["--source-tech", "Snowflake"])
        assert s.get(run.id).started_at is None

        s.set_status(run.id, RunStatus.RUNNING)
        running = s.get(run.id)
        assert running.status == RunStatus.RUNNING
        assert running.started_at is not None
        assert running.ended_at is None

        s.set_status(run.id, RunStatus.COMPLETED, exit_code=0)
        done = s.get(run.id)
        assert done.status == RunStatus.COMPLETED
        assert done.ended_at is not None
        assert done.exit_code == 0
        # started_at must not be clobbered by the second transition
        assert done.started_at == running.started_at


def test_add_event_and_ordering():
    with tempfile.TemporaryDirectory() as d:
        s = RunStore(Path(d) / "t.db")
        run = s.create("transpile", [])
        s.add_event(run.id, EventType.STDOUT, "line one")
        s.add_event(run.id, EventType.STDOUT, "line two")
        events = s.get(run.id).events
        assert [e.message for e in events] == ["line one", "line two"]


def test_persistence_survives_store_restart():
    """The whole point of G2's SQLite migration: data must outlive the process."""
    with tempfile.TemporaryDirectory() as d:
        db_path = Path(d) / "persist.db"

        s1 = RunStore(db_path)
        run = s1.create("describe-transpile", [])
        s1.set_status(run.id, RunStatus.RUNNING)
        s1.add_event(run.id, EventType.STDOUT, "hello from before restart")
        s1.set_status(run.id, RunStatus.COMPLETED, exit_code=0)
        s1.close()

        # Simulate a server restart: brand new RunStore instance, same file.
        s2 = RunStore(db_path)
        restored = s2.get(run.id)
        assert restored is not None
        assert restored.status == RunStatus.COMPLETED
        assert restored.exit_code == 0
        assert len(restored.events) == 1
        assert restored.events[0].message == "hello from before restart"


def test_run_ids_do_not_collide_across_restart():
    with tempfile.TemporaryDirectory() as d:
        db_path = Path(d) / "ids.db"
        s1 = RunStore(db_path)
        s1.create("analyze", [])
        s1.create("transpile", [])
        s1.close()

        s2 = RunStore(db_path)
        run3 = s2.create("reconcile", [])
        assert run3.id == "run_3"
        assert len(s2.list()) == 3


# ---------------------------------------------------------------- G8: Migration target fields


def test_migration_target_fields_round_trip_fresh_db():
    """Fresh DB exercises the CREATE TABLE path (target_* columns already
    in _SCHEMA) rather than the ALTER TABLE migration path."""
    with tempfile.TemporaryDirectory() as d:
        s = MigrationStore(Path(d) / "fresh.db")
        mig = s.create("redshift", "table-data", "public.category", MigrationEngine.DATA_COPY)
        assert mig.target_catalog is None
        assert mig.target_schema is None
        assert mig.target_table is None

        s.update(
            mig.id, status=RunStatus.COMPLETED,
            target_catalog="lakebridge_demo", target_schema="g3_migrations",
            target_table="redshift_public_category", ended=True,
        )
        fetched = s.get(mig.id)
        assert fetched.target_catalog == "lakebridge_demo"
        assert fetched.target_schema == "g3_migrations"
        assert fetched.target_table == "redshift_public_category"

        listed = s.list()
        assert len(listed) == 1
        assert listed[0].target_table == "redshift_public_category"


def test_migration_target_columns_added_via_alter_on_existing_db():
    """Simulates a pre-G8 on-disk DB (migrations table with no target_*
    columns) and confirms MigrationStore's additive ALTER TABLE migration
    runs cleanly and existing rows survive with NULL target fields."""
    with tempfile.TemporaryDirectory() as d:
        db_path = Path(d) / "legacy.db"

        # Build a pre-G8-shaped migrations table directly, bypassing
        # MigrationStore's own (already-updated) _SCHEMA.
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE migrations (
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
            """
        )
        conn.execute(
            "INSERT INTO migrations (id, source_system, object_type, object_name, engine, status) "
            "VALUES ('mig_1', 'redshift', 'table', 'public.venue', 'lakebridge-transpile', 'completed')"
        )
        conn.commit()
        conn.close()

        # Opening a MigrationStore against this legacy file must run the
        # additive migration, not crash, and must not touch the existing row.
        s = MigrationStore(db_path)
        pre_existing = s.get("mig_1")
        assert pre_existing is not None
        assert pre_existing.target_catalog is None
        assert pre_existing.target_schema is None
        assert pre_existing.target_table is None
        assert pre_existing.object_name == "public.venue"

        # And the store is now fully usable for new rows with real target values.
        mig = s.create("starburst", "table-data", "cat.sch.tbl", MigrationEngine.DATA_COPY)
        s.update(mig.id, target_catalog="lakebridge_demo", target_schema="g3_migrations", target_table="starburst_cat_sch_tbl")
        fetched = s.get(mig.id)
        assert fetched.target_table == "starburst_cat_sch_tbl"

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _wait_for_terminal(run_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = client.get(f"/runs/{run_id}")
        assert r.status_code == 200
        last = r.json()
        if last["status"] in ("completed", "failed"):
            return last
        time.sleep(0.5)
    raise TimeoutError(f"run {run_id} did not terminate in {timeout}s, last={last}")


def test_unknown_run_returns_404():
    r = client.get("/runs/does-not-exist")
    assert r.status_code == 404


def test_list_runs_returns_json_array():
    r = client.get("/runs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.slow
def test_describe_transpile_end_to_end():
    """Real integration test: actually invokes the Lakebridge CLI."""
    r = client.post("/runs/describe-transpile")
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    final = _wait_for_terminal(run_id)
    assert final["status"] == "completed", final
    assert final["exit_code"] == 0

    events = client.get(f"/runs/{run_id}/events").json()
    assert len(events) > 0
    joined = " ".join(e["message"] for e in events)
    # describe-transpile lists installed transpilers by name
    assert "Bladebridge" in joined or "Morpheus" in joined


@pytest.mark.slow
def test_transpile_end_to_end_against_sample_fixtures():
    r = client.post("/runs/transpile", json={"source_dialect": "snowflake"})
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    final = _wait_for_terminal(run_id, timeout=120)
    assert final["status"] == "completed", final

    events = client.get(f"/runs/{run_id}/events").json()
    joined = " ".join(e["message"] for e in events)
    assert "Processed file" in joined


@pytest.mark.slow
def test_analyze_end_to_end_against_sample_fixtures():
    r = client.post("/runs/analyze", json={"source_tech": "Snowflake"})
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    final = _wait_for_terminal(run_id, timeout=120)
    assert final["status"] == "completed", final
    assert final["exit_code"] == 0

    events = client.get(f"/runs/{run_id}/events").json()
    assert len(events) > 0


@pytest.mark.slow
def test_reconcile_end_to_end_dispatches_and_polls_real_job_to_completion():
    """G2 finding, closed for real in G4: `reconcile` takes zero CLI flags —
    it dispatches a job that was registered against workspace state by a
    prior `configure-reconcile` run (see docs/RECONCILE.md). That job (id
    254503333498153) still exists in this workspace as of 2026-08-01, so
    this test exercises the real path rather than a synthetic one.

    G2 only proved dispatch; this proves the honesty gap identified there is
    closed: the Run must stay "running" while the real job is still
    executing (not "completed" the instant the CLI returns), and only report
    "completed" once the real job reaches an actual terminal state — with
    the real row/column comparison result attached.

    If the job/workspace state is ever torn down, this test will correctly
    fail loudly (non-zero exit, error event) rather than silently pass —
    which is the honest behaviour we want, not a fabricated success.
    """
    r = client.post("/runs/reconcile")
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    # Immediately after the POST returns, the CLI has almost certainly not
    # even finished dispatching yet — the run must not already claim
    # "completed". This is the exact dispatch-vs-completion race the G2
    # entry flagged as unclosed.
    immediate = client.get(f"/runs/{run_id}").json()
    assert immediate["status"] in ("queued", "running"), immediate

    # A real remote job dispatch + poll-to-terminal; slower than local commands.
    final = _wait_for_terminal(run_id, timeout=300)
    assert final["status"] == "completed", final
    assert final["exit_code"] == 0

    # The real discovered result shape (see executor.py's
    # _fetch_reconcile_result) must be attached to the terminal run.
    assert final["result"] is not None, final
    assert final["result"]["lifecycle_state"] == "TERMINATED"
    assert final["result"]["result_state"] == "SUCCESS"
    assert "reconciliation_passed" in final["result"], final["result"]

    events = client.get(f"/runs/{run_id}/events").json()
    joined = " ".join(e["message"] for e in events)
    assert "reconcile" in joined.lower() or "job" in joined.lower()
    assert "polling for real completion" in joined

    detail = client.get(f"/runs/{run_id}/reconcile").json()
    assert detail["status"] == "completed"
    assert detail["result"]["result_state"] == "SUCCESS"


def test_reconcile_detail_endpoint_404s_for_unknown_run():
    r = client.get("/runs/does-not-exist/reconcile")
    assert r.status_code == 404


@pytest.mark.slow
def test_reconcile_detail_endpoint_rejects_non_reconcile_run():
    r = client.post("/runs/describe-transpile")
    run_id = r.json()["run_id"]
    _wait_for_terminal(run_id)
    detail = client.get(f"/runs/{run_id}/reconcile")
    assert detail.status_code == 400


@pytest.mark.slow
def test_history_includes_a_real_run_and_a_real_migration():
    """/history must span at least RunStore + MigrationStore without
    duplicating persisted data — it's a merged read, not a fourth store."""
    run_resp = client.post("/runs/describe-transpile")
    run_id = run_resp.json()["run_id"]
    _wait_for_terminal(run_id)

    history = client.get("/history").json()
    assert isinstance(history, list)
    kinds = {item["kind"] for item in history}
    assert "run" in kinds
    run_ids_in_history = {item["id"] for item in history if item["kind"] == "run"}
    assert run_id in run_ids_in_history

    migration_ids_in_history = {item["id"] for item in history if item["kind"] == "migration"}
    # At least the earlier G3.2/G3.3/G3.4 sessions created real migrations
    # that persisted to the same SQLite file — if any exist, they must show
    # up here without a second POST being required by this test.
    from app.models import migration_store as _mstore

    if _mstore.list():
        assert migration_ids_in_history, "migrations exist in MigrationStore but none appeared in /history"


def test_history_returns_empty_list_shape_even_with_no_data():
    r = client.get("/history")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---------------------------------------------------------------- G7

@pytest.mark.slow
def test_migrate_starburst_ddl_old_endpoint_still_200s_untouched():
    """Regression: the old llm-transpile endpoint must remain fully live
    and unmodified by the G7 build — this project's explicit "hide, don't
    delete" requirement (see MEMORY.md's G7 entry)."""
    r = client.post("/migrate/starburst/ddl/table/mcp2ohio/test_writes/products")
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "llm-transpile-experimental"


@pytest.mark.slow
def test_migrate_starburst_ddl_custom_endpoint_real_table():
    # force=true: asserts real translator output, so it must not short-circuit.
    r = client.post("/migrate/starburst/ddl-custom/table/mcp2ohio/test_writes/products?force=true")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["engine"] == "starburst-custom-ddl"
    assert "CREATE TABLE" in body["output_ddl"]
    assert "STRING" in body["output_ddl"] or "DOUBLE" in body["output_ddl"]


@pytest.mark.slow
def test_migrate_starburst_ddl_custom_endpoint_real_view():
    r = client.post("/migrate/starburst/ddl-custom/view/mcp2ohio/test_writes/g7_view_probe")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["engine"] == "starburst-custom-ddl"
    assert "SECURITY DEFINER" not in body["output_ddl"]


def test_migrate_starburst_ddl_custom_endpoint_rejects_unsupported_object_type():
    r = client.post("/migrate/starburst/ddl-custom/procedure/mcp2ohio/test_writes/whatever")
    assert r.status_code == 400
    detail = r.json()["detail"]
    # Assert the substance, not one exact phrasing — this test previously
    # pinned the wording and broke when the message was corrected in G18.
    assert "stored procedures" in detail.lower()
    # Regression guard for the G18 honesty fix: this message used to also claim
    # "UDF bodies aren't recoverable", which is FALSE — SHOW CREATE FUNCTION
    # returns the real body. It must never come back.
    assert "recoverable" not in detail.lower()


@pytest.mark.slow
def test_migrate_starburst_data_endpoint_real_table():
    r = client.post("/migrate/starburst/data/mcp2ohio/test_writes/products")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["engine"] == "data-copy"
    assert body["row_count"] is not None and body["row_count"] >= 0


@pytest.mark.slow
def test_migrate_starburst_data_endpoint_returns_target_fields_in_json():
    """G8: target_catalog/target_schema/target_table must reach the real HTTP
    response, not just the DB row — a prior verification pass found this data
    existed in SQLite but was silently dropped by _migration_summary()."""
    from app.databricks_target import TARGET_CATALOG, TARGET_SCHEMA

    r = client.post("/migrate/starburst/data/mcp2ohio/test_writes/products")
    assert r.status_code == 200
    body = r.json()
    assert body["target_catalog"] == TARGET_CATALOG
    assert body["target_schema"] == TARGET_SCHEMA
    assert body["target_table"]

    r2 = client.get(f"/migrations/{body['id']}")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["target_catalog"] == TARGET_CATALOG
    assert body2["target_schema"] == TARGET_SCHEMA
    assert body2["target_table"] == body["target_table"]


@pytest.mark.slow
def test_migrate_starburst_ddl_custom_creates_the_object_and_reports_its_target():
    """G19 contract change. This test previously asserted the target_* fields
    stayed None, because a DDL migration produced converted SQL text and created
    nothing. `migrate` now applies the transpiled DDL to Databricks, so those
    fields identify the object that really exists — asserting they are None
    would now assert that the migration did nothing."""
    from app.databricks_target import TARGET_CATALOG, TARGET_SCHEMA

    r = client.post("/migrate/starburst/ddl-custom/table/mcp2ohio/test_writes/products")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed", body.get("error")
    assert body["target_catalog"] == TARGET_CATALOG
    assert body["target_schema"] == TARGET_SCHEMA
    assert body["target_table"] == "starburst_mcp2ohio_test_writes_products"
    # The object is really there, not just recorded as such.
    from app.connectors import databricks_browse

    names = {t.name for t in databricks_browse.list_tables(TARGET_CATALOG, TARGET_SCHEMA)}
    assert body["target_table"] in names


# --- G8: /explore/databricks/* endpoint tests (Agent A) ---------------------

@pytest.mark.slow
def test_explore_databricks_catalogs_real():
    from app.databricks_target import TARGET_CATALOG

    r = client.get("/explore/databricks/catalogs")
    assert r.status_code == 200
    names = [c["name"] for c in r.json()]
    assert TARGET_CATALOG in names


@pytest.mark.slow
def test_explore_databricks_schemas_real():
    from app.databricks_target import TARGET_CATALOG, TARGET_SCHEMA

    r = client.get(f"/explore/databricks/catalogs/{TARGET_CATALOG}/schemas")
    assert r.status_code == 200
    assert TARGET_SCHEMA in [s["name"] for s in r.json()]


@pytest.mark.slow
def test_explore_databricks_tables_real():
    from app.databricks_target import TARGET_CATALOG, TARGET_SCHEMA

    r = client.get(f"/explore/databricks/catalogs/{TARGET_CATALOG}/schemas/{TARGET_SCHEMA}/tables")
    assert r.status_code == 200
    tables = r.json()
    assert isinstance(tables, list)
    if tables:
        assert {"catalog", "schema", "name", "type"} <= tables[0].keys()


@pytest.mark.slow
def test_explore_databricks_table_preview_real():
    from app.databricks_target import TARGET_CATALOG, TARGET_SCHEMA

    r = client.get(f"/explore/databricks/catalogs/{TARGET_CATALOG}/schemas/{TARGET_SCHEMA}/tables")
    tables = r.json()
    if not tables:
        pytest.skip("no real target tables yet to preview")
    table_name = tables[0]["name"]
    r = client.get(
        f"/explore/databricks/catalogs/{TARGET_CATALOG}/schemas/{TARGET_SCHEMA}"
        f"/tables/{table_name}/preview?limit=5"
    )
    assert r.status_code == 200
    body = r.json()
    assert "columns" in body and "rows" in body and "row_count" in body
    assert isinstance(body["columns"], list)
    assert isinstance(body["rows"], list)

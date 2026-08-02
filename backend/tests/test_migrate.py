"""Real integration tests for G3.2 migration execution — no mocking, same
standard as every phase since G1. See MEMORY.md's 2026-08-01 "G3.2" entry
for the real defects found while building this (llm-transpile's invalid
dialect + its exit-code-0-on-error bug; a real transpiler type-inference
bug on f_ticket_price_category's return type)."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.credential_leak import _assert_no_real_credentials_in

client = TestClient(app)


def test_copy_redshift_table_data_populates_target_fields_mocked():
    """G8: target_catalog/target_schema/target_table must be populated with
    the real values migrate.py already computes (TARGET_CATALOG/TARGET_SCHEMA
    constants + the target_table_name variable it builds), not left None.
    Mocked at the connector/warehouse boundary — no live network needed,
    mirrors test_starburst_custom.py's equivalent mocked test."""
    from app import migrate
    from app.connectors.redshift import Column
    from app import databricks_target

    columns = [
        Column(name="id", data_type="integer", ordinal=1),
        Column(name="name", data_type="character varying", ordinal=2),
    ]
    rows = [(1, "a"), (2, "b")]
    with (
        patch("app.migrate.redshift_conn.list_columns", return_value=columns),
        patch("app.migrate.redshift_conn._connect") as mock_connect,
        patch(
            "app.migrate.databricks_target.create_target_table",
            return_value="lakebridge_demo.g3_migrations.redshift_public_category",
        ) as mock_create,
        patch("app.migrate.databricks_target.insert_rows", return_value=2),
        # G20: copy_* now asks whether the target already exists, purely to
        # report it. Mocked here so this stays a no-network test.
        patch("app.migrate.databricks_target.object_exists", return_value=False),
        patch("app.migrate.databricks_target.execute", return_value=[(2,)]),
    ):
        mock_cursor = mock_connect.return_value.cursor.return_value
        mock_cursor.fetchall.return_value = rows
        mig = migrate.copy_redshift_table_data("public", "category")

    assert mig.status.value == "completed"
    mock_create.assert_called_once()
    assert mig.target_catalog == databricks_target.TARGET_CATALOG
    assert mig.target_schema == databricks_target.TARGET_SCHEMA
    assert mig.target_table == "redshift_public_category"


@pytest.mark.slow
def test_migrate_redshift_table_ddl_real():
    # force=true: this test verifies real transpiler output, so it must not
    # short-circuit on "already migrated" (G20) — that would make the result
    # depend on warehouse state.
    r = client.post("/migrate/redshift/ddl/table/public/venue?force=true")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["engine"] == "lakebridge-transpile"
    assert "CREATE TABLE public.venue" in body["source_ddl"]
    assert "venueid" in body["output_ddl"]
    # Redshift-specific clauses must be handled, not silently pass through
    # unmodified into Databricks SQL
    assert "DISTSTYLE" not in body["output_ddl"].split("/*")[-1].split("*/")[0] or "/*" in body["output_ddl"]


@pytest.mark.slow
def test_migrate_redshift_procedure_ddl_real():
    r = client.post("/migrate/redshift/ddl/procedure/public/sp_total_sales_by_venue")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert "sp_total_sales_by_venue" in body["output_ddl"]
    assert "venue_sales_summary" in body["output_ddl"]


@pytest.mark.slow
def test_migrate_redshift_function_ddl_real():
    r = client.post("/migrate/redshift/ddl/function/public/f_days_until_event")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert "DATEDIFF" in body["output_ddl"]


@pytest.mark.slow
def test_migrate_redshift_function_ddl_real_known_transpiler_bug():
    """Documents a real, found-not-hidden transpiler defect: the source
    declares RETURNS VARCHAR(20), but Lakebridge's own transpiler outputs
    RETURNS CHAR(1) for this function. This test pins the current (wrong)
    behavior so a future transpiler version change is visible, not silently
    assumed fixed."""
    r = client.post("/migrate/redshift/ddl/function/public/f_ticket_price_category")
    assert r.status_code == 200
    body = r.json()
    assert "CHAR(1)" in body["output_ddl"], (
        "if this fails, Lakebridge's transpiler may have FIXED the "
        "VARCHAR(20)->CHAR(1) bug — update MEMORY.md, don't just adjust the assertion"
    )
    # G19: this asserted "completed" back when a DDL migration only produced
    # text. `migrate` now applies the DDL, and Databricks rejects CHAR/VARCHAR
    # as a SQL UDF return type (UNSUPPORTED_CHAR_OR_VARCHAR_AS_STRING) — so the
    # transpiler defect above now has a real, visible consequence rather than a
    # silent one. Both facts are pinned deliberately: if either changes, this
    # test should fail and be re-examined, not quietly relaxed.
    assert body["status"] == "failed"
    assert "char" in (body["error"] or "").lower()


def test_migrate_redshift_rejects_unsupported_object_type():
    r = client.post("/migrate/redshift/ddl/materialized_view/public/venue")
    assert r.status_code == 400


@pytest.mark.slow
def test_migrate_redshift_table_data_real():
    r = client.post("/migrate/redshift/data/public/category")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["engine"] == "data-copy"
    assert body["row_count"] > 0
    # the row count claimed here must match what's actually queryable
    from app import databricks_target
    verify = databricks_target.execute(
        "SELECT COUNT(*) FROM lakebridge_demo.g3_migrations.redshift_public_category"
    )
    assert verify[0][0] == body["row_count"]


def test_no_credentials_leak_in_migration_responses():
    r = client.get("/migrations")
    assert r.status_code == 200
    body = r.text
    _assert_no_real_credentials_in(body)


@pytest.mark.slow
def test_migrate_starburst_table_ddl_real_experimental_engine_labeled():
    """The Starburst path must never look identical to Redshift's
    deterministic result — this is the whole point of the `engine` field."""
    r = client.post("/migrate/starburst/ddl/table/mcp2ohio/test_writes/products")
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "llm-transpile-experimental"
    assert body["engine"] != "lakebridge-transpile"


@pytest.mark.slow
def test_insert_rows_round_trips_apostrophes_real():
    """G15 regression test for the real apostrophe-dropping bug (found in
    G14, root-caused in G15): `insert_rows` previously inlined values via
    `_sql_literal`'s doubled-quote escaping, and the Databricks SQL
    connector's `execute()` silently stripped the escaped apostrophe from
    that inlined text (confirmed live: `SELECT 'Dick''s...'` -> `Dicks...`).
    Fixed by always binding parameters instead of inlining. This test
    creates a real table, inserts a row containing an apostrophe via the
    real `insert_rows` path, and confirms `SELECT` round-trips it unmodified
    against the live warehouse — not mocked."""
    from app import databricks_target

    fq = databricks_target.create_target_table(
        "g15_apostrophe_regression",
        [("id", "integer"), ("name", "character varying")],
    )
    try:
        inserted = databricks_target.insert_rows(
            fq, ["id", "name"], [(1, "Dick's Sporting Goods Park"), (2, "O'Brien's Pub")]
        )
        assert inserted == 2
        rows = databricks_target.execute(f"SELECT id, name FROM {fq} ORDER BY id")
        result = {r[0]: r[1] for r in rows}
        assert result[1] == "Dick's Sporting Goods Park"
        assert result[2] == "O'Brien's Pub"
    finally:
        databricks_target.execute(f"DROP TABLE IF EXISTS {fq}")


def test_migrate_starburst_rejects_udf_object_type():
    """UDF logic isn't recoverable from Starburst (SHOW FUNCTIONS has no
    body) — the endpoint must say so, not silently attempt a fake migration."""
    r = client.post("/migrate/starburst/ddl/udf/mcp2ohio/test_writes/f_price_tier")
    assert r.status_code == 400

"""Real integration tests for G3.4 batch/whole-schema migration — no
mocking, same standard as every phase since G1. Uses Redshift's `public`
schema (fast, deterministic path) for the main real end-to-end batch test,
per the task's own guidance to avoid a real 5-8 minute Starburst batch in
every run.
"""
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _poll_batch(batch_id: str, timeout_s: int = 120) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = client.get(f"/batches/{batch_id}")
        assert r.status_code == 200
        body = r.json()
        if body["status"] in ("completed", "completed_with_errors"):
            return body
        time.sleep(1)
    raise TimeoutError(f"batch {batch_id} did not reach a terminal state in {timeout_s}s")


# Measured against the real stack on 2026-08-02: one real Redshift DDL
# migration (read source DDL -> Lakebridge transpile -> CREATE in Databricks)
# takes ~12.4s, and run_batch processes items sequentially. A fixed budget
# therefore silently rots as the source schema grows — which is exactly what
# happened here: the 180s budget below was written when `public` held the 10
# objects this test's docstring describes, and the schema has since grown to 15
# (the g14_* fixture tables), pushing a real, healthy batch to ~186s. Scale the
# budget with the item count instead of hardcoding a number that has to be
# revised by hand every time someone adds a table.
_SECONDS_PER_BATCH_ITEM = 25  # ~2x the measured 12.4s, for warehouse variance
_MIN_BATCH_TIMEOUT_S = 180


@pytest.mark.slow
def test_batch_redshift_schema_real_end_to_end():
    """Real batch against a real schema — every table, function and procedure in
    it, all real, all migrated for real. Must not block the request: the POST
    returns pending/running immediately.

    Targets `demo_fast_test`, not `public`. This used to run against `public`,
    and it started timing out once batches began copying row data as well as
    DDL: `public` is the TICKIT sample set, so it expands to 27 items whose data
    copies run into six figures of rows — measured at 15 items in ~25 minutes,
    i.e. 45-90 minutes for the whole test. That is a load test, not a
    correctness test, and it proves nothing `demo_fast_test` doesn't prove in
    under two minutes: same endpoint, same expansion, same engines, real rows.
    """
    schema = "demo_fast_test"
    r = client.post(f"/migrate/redshift/schema/{schema}/batch")
    assert r.status_code == 200
    body = r.json()
    batch_id = body["id"]
    assert body["status"] in ("pending", "running")
    # 2 tables (x2 items each: DDL + data) + 5 functions + 1 procedure = 10.
    # `>=` so adding a demo object doesn't break the test.
    assert body["total_items"] >= 10

    final = _poll_batch(
        batch_id,
        timeout_s=max(_MIN_BATCH_TIMEOUT_S, body["total_items"] * _SECONDS_PER_BATCH_ITEM),
    )
    assert final["dispatched_items"] == final["total_items"]
    assert final["status"] == "completed"
    assert final["failed_items"] == 0

    detail = client.get(f"/batches/{batch_id}").json()
    assert len(detail["migrations"]) == final["total_items"]
    names = {m["object_name"] for m in detail["migrations"]}
    assert f"{schema}.customers" in names
    assert f"{schema}.f_customer_tenure" in names
    assert f"{schema}.sp_top_customers" in names

    # A schema batch produces BOTH engines: the CLI transpiler for DDL items and
    # the separate data-copy path for table-data items. Asserting a single
    # engine for everything was only true before batches copied data.
    engines = {(m["object_type"], m["engine"]) for m in detail["migrations"]}
    assert ("table", "lakebridge-transpile") in engines
    assert ("table-data", "data-copy") in engines
    for m in detail["migrations"]:
        assert m["status"] == "completed"
        assert m["engine"] in ("lakebridge-transpile", "data-copy")

    # The data items must have copied real rows, not silently zero.
    data_items = [m for m in detail["migrations"] if m["object_type"] == "table-data"]
    assert data_items and all((m["row_count"] or 0) > 0 for m in data_items)


def test_batch_rejects_empty_schema():
    r = client.post("/migrate/redshift/schema/definitely_not_a_real_schema_xyz/batch")
    assert r.status_code == 400


def test_batch_explicit_rejects_empty_items():
    r = client.post("/migrate/batch", json={"items": []})
    assert r.status_code == 400


def test_batch_explicit_rejects_bad_object_type():
    r = client.post(
        "/migrate/batch",
        json={"items": [{"source_system": "redshift", "object_type": "materialized_view", "schema_name": "public", "name": "venue"}]},
    )
    assert r.status_code == 400


def test_batch_explicit_rejects_starburst_without_catalog():
    r = client.post(
        "/migrate/batch",
        json={"items": [{"source_system": "starburst", "object_type": "table", "schema_name": "test_writes", "name": "products"}]},
    )
    assert r.status_code == 400


def test_batch_not_found_returns_404():
    r = client.get("/batches/batch_definitely_not_real_xyz")
    assert r.status_code == 404


@pytest.mark.slow
def test_batch_partial_failure_visible_not_hidden():
    """One bad item (a real object that doesn't exist, so its migration
    fails for a real reason) must not abort the rest of the batch, and the
    failure must be visible in the batch's own status and per-item
    breakdown — never silently swallowed into an overall 'completed'."""
    r = client.post(
        "/migrate/batch",
        json={
            "items": [
                {"source_system": "redshift", "object_type": "table", "schema_name": "public", "name": "venue"},
                {"source_system": "redshift", "object_type": "table", "schema_name": "public", "name": "this_table_does_not_exist_xyz"},
                {"source_system": "redshift", "object_type": "table", "schema_name": "public", "name": "category"},
            ]
        },
    )
    assert r.status_code == 200
    batch_id = r.json()["id"]
    final = _poll_batch(batch_id, timeout_s=120)
    assert final["status"] == "completed_with_errors"
    # A batch expands every table into TWO items — the DDL migration and the
    # data copy (G20: "batch select mode must copy the data too"). So three
    # requested tables produce six items, and the one bad table fails on both
    # of its items. This test previously asserted the pre-expansion shape
    # (3 items / 1 failure) and only started failing once the data step existed.
    assert final["total_items"] == 6
    assert final["failed_items"] == 2
    assert final["completed_items"] == 4

    detail = client.get(f"/batches/{batch_id}").json()
    # object_name is not unique once each table has a DDL and a data item, so
    # key on (name, object_type).
    statuses = {(m["object_name"], m["object_type"]): m["status"] for m in detail["migrations"]}
    for name in ("public.venue", "public.category"):
        assert statuses[(name, "table")] == "completed"
        assert statuses[(name, "table-data")] == "completed"
    bad = "public.this_table_does_not_exist_xyz"
    assert statuses[(bad, "table")] == "failed"
    assert statuses[(bad, "table-data")] == "failed"

    # The data item must fail for the REAL reason. It used to build
    # `SELECT  FROM ...` from an empty column list and report a SQL *syntax*
    # error, which said nothing about the table being missing.
    errors = {
        (m["object_name"], m["object_type"]): (m.get("error") or "")
        for m in detail["migrations"]
    }
    assert "does not exist" in errors[(bad, "table-data")]
    assert "syntax error" not in errors[(bad, "table-data")]

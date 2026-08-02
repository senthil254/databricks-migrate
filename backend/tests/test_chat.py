"""G6 — real integration tests for the chat plan/execute layer. Same
standard as every phase since G1: no mocking, real live Redshift inventory,
real dispatched migration.

G12 exception: the section at the bottom of this file uses monkeypatch to
simulate a real Databricks connection failure (the warehouse's daily query
quota being exhausted, confirmed real in this environment) without needing
a live warehouse call — see test_databricks_browse.py's matching section
for the same rationale.
"""
import pytest
from fastapi.testclient import TestClient

from app import databricks_target
from app.main import app

client = TestClient(app)


def test_chat_plan_empty_instruction_is_refused():
    r = client.post("/chat/plan", json={"instruction": "   "})
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is False
    assert "reason" in body


def test_chat_plan_garbage_unrelated_instruction_is_refused():
    r = client.post("/chat/plan", json={"instruction": "what is the weather like today in Paris?"})
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is False
    assert "reason" in body


@pytest.mark.slow
def test_chat_plan_nonexistent_table_is_refused_not_fabricated():
    r = client.post("/chat/plan", json={"instruction": "migrate the nonexistent_table_xyz table"})
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is False
    assert "reason" in body
    # never fabricate a plan referencing something that doesn't exist
    assert "action" not in body


@pytest.mark.slow
def test_chat_plan_and_execute_real_migrate_ddl_matches_normal_endpoint_shape():
    """Real end-to-end: plan a real DDL migration of a real known table,
    then execute it, then confirm the resulting Migration record is
    indistinguishable from one created via the normal /migrate/* endpoint,
    and shows up in /history like any other real migration."""
    # G20: `migrate` short-circuits when the object is already in the target,
    # which would leave source_ddl/output_ddl empty and make the assertions
    # below depend on warehouse state. Chat has no force flag (by design — a
    # user shouldn't have to say "do it again"), so drop the target first to
    # guarantee this exercises a real migration.
    databricks_target.execute(
        f"DROP TABLE IF EXISTS {databricks_target.TARGET_CATALOG}."
        f"{databricks_target.TARGET_SCHEMA}.redshift_public_venue"
    )

    plan_resp = client.post("/chat/plan", json={"instruction": "migrate the venue table"})
    assert plan_resp.status_code == 200
    plan_body = plan_resp.json()
    assert plan_body["understood"] is True
    assert plan_body["action"] == {
        "kind": "migrate_ddl",
        "source_system": "redshift",
        "object_type": "table",
        "schema": "public",
        "name": "venue",
    }
    assert plan_body["endpoint"] == "POST /migrate/redshift/ddl/table/public/venue"

    exec_resp = client.post("/chat/execute", json={"plan_id": plan_body["plan_id"]})
    assert exec_resp.status_code == 200
    exec_body = exec_resp.json()
    assert exec_body["result_type"] == "migration"
    mig_id = exec_body["migration_id"]

    mig = client.get(f"/migrations/{mig_id}").json()
    assert mig["status"] == "completed"
    assert mig["source_system"] == "redshift"
    assert mig["object_type"] == "table"
    assert mig["engine"] == "lakebridge-transpile"
    assert "CREATE TABLE public.venue" in mig["source_ddl"]
    assert "venueid" in mig["output_ddl"]

    # Same shape as the normal /migrate/redshift/ddl/table/public/venue
    # endpoint would return directly.
    direct = client.post("/migrate/redshift/ddl/table/public/venue?force=true").json()
    assert set(direct.keys()) == set(mig.keys())

    history = client.get("/history").json()
    assert any(item["kind"] == "migration" and item["id"] == mig_id for item in history)


@pytest.mark.slow
def test_chat_execute_by_full_plan_body_not_just_id():
    plan = client.post("/chat/plan", json={"instruction": "migrate the category table"}).json()
    assert plan["understood"] is True
    exec_resp = client.post("/chat/execute", json={"plan": plan})
    assert exec_resp.status_code == 200
    body = exec_resp.json()
    assert body["result_type"] == "migration"


def test_chat_execute_unknown_plan_id_is_404():
    r = client.post("/chat/execute", json={"plan_id": "plan_does_not_exist"})
    assert r.status_code == 404


def test_chat_plan_ambiguous_object_type_is_refused():
    """venue is a real table, not a view — asking to migrate it as a view
    must not silently migrate the table anyway."""
    r = client.post("/chat/plan", json={"instruction": "migrate the venue view"})
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is False


# ---------------------------------------------------------------- G8 Starburst chat
# Real objects used below (live in the starburst env, discovered directly
# via the connector, not invented):
#   federated_postgres.burstbank: customer, customer_profile, employee
#   sample.burstbank:             account, ..., customer, customer_profile,
#                                  employee, ...
# -> "employee"/"customer" appear as real tables in BOTH federated_postgres
#    .burstbank and sample.burstbank, giving a genuine cross-catalog
#    ambiguous case; qualifying with "catalog federated_postgres" resolves
#    it unambiguously.
#   federated_s3.burstbank: auto_loan_payment, credit_card_payment,
#                            mortgage_payment (3 real base tables, no views)
#    -> small enough for a real whole-schema batch plan.


@pytest.mark.slow
def test_chat_plan_starburst_ambiguous_across_catalogs_is_refused():
    r = client.post("/chat/plan", json={"instruction": "migrate the customer table in starburst"})
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is False
    assert "reason" in body
    assert "action" not in body


@pytest.mark.slow
def test_chat_plan_and_execute_real_starburst_migrate_ddl_uses_custom_path_not_llm():
    """Qualifying with an explicit catalog/schema resolves the cross-catalog
    ambiguity and must route to G7's migrate_starburst_ddl_custom — never
    migrate_starburst_ddl (the old llm-transpile path)."""
    plan_resp = client.post(
        "/chat/plan",
        json={"instruction": "migrate the employee table in starburst catalog federated_postgres schema burstbank"},
    )
    assert plan_resp.status_code == 200
    plan_body = plan_resp.json()
    assert plan_body["understood"] is True
    assert plan_body["action"] == {
        "kind": "migrate_ddl",
        "source_system": "starburst",
        "object_type": "table",
        "catalog": "federated_postgres",
        "schema": "burstbank",
        "name": "employee",
    }
    assert plan_body["endpoint"] == "POST /migrate/starburst/ddl-custom/table/federated_postgres/burstbank/employee"

    exec_resp = client.post("/chat/execute", json={"plan_id": plan_body["plan_id"]})
    assert exec_resp.status_code == 200
    exec_body = exec_resp.json()
    assert exec_body["result_type"] == "migration"
    mig_id = exec_body["migration_id"]

    mig = client.get(f"/migrations/{mig_id}").json()
    assert mig["source_system"] == "starburst"
    assert mig["engine"] == "starburst-custom-ddl"
    assert mig["engine"] != "llm-transpile-experimental"


@pytest.mark.slow
def test_chat_plan_and_execute_real_starburst_data_copy():
    plan_resp = client.post(
        "/chat/plan",
        json={"instruction": "copy the data for employee table in starburst catalog federated_postgres schema burstbank"},
    )
    assert plan_resp.status_code == 200
    plan_body = plan_resp.json()
    assert plan_body["understood"] is True
    assert plan_body["action"] == {
        "kind": "copy_table_data",
        "source_system": "starburst",
        "catalog": "federated_postgres",
        "schema": "burstbank",
        "name": "employee",
    }

    exec_resp = client.post("/chat/execute", json={"plan_id": plan_body["plan_id"]})
    assert exec_resp.status_code == 200
    exec_body = exec_resp.json()
    assert exec_body["result_type"] == "migration"
    mig_id = exec_body["migration_id"]

    mig = client.get(f"/migrations/{mig_id}").json()
    assert mig["source_system"] == "starburst"
    assert mig["engine"] == "data-copy"


@pytest.mark.slow
def test_chat_plan_starburst_whole_schema_batch():
    r = client.post(
        "/chat/plan",
        json={"instruction": "batch-migrate schema burstbank in starburst catalog federated_s3"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is True
    assert body["action"]["kind"] == "migrate_starburst_schema_batch"
    assert body["action"]["source_system"] == "starburst"
    assert body["action"]["catalog"] == "federated_s3"
    assert body["action"]["schema"] == "burstbank"
    assert body["action"]["item_count"] == 3


def test_chat_plan_starburst_batch_without_catalog_is_refused():
    """Three-level namespace means a schema alone is never enough to
    disambiguate a whole-catalog batch — must refuse, not guess a catalog."""
    r = client.post(
        "/chat/plan",
        json={"instruction": "batch-migrate the whole schema burstbank in starburst"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is False
    assert "catalog" in body["reason"]


# ---------------------------------------------------------------- G9 — relocation
# `_run_starburst_schema_batch`/`_start_starburst_schema_batch` moved from
# chat.py into `migrate.run_starburst_schema_batch`/`start_starburst_schema_batch`.
# The two tests below prove: (1) the chat batch-migrate-schema path still
# works end to end via the relocated functions (2) the new direct REST
# route `POST /migrate/starburst/catalog/{catalog}/schema/{schema}/batch`
# hits the exact same code and every dispatched migration used G7's fast
# deterministic engine (starburst-custom-ddl), never the old LLM path.


def _wait_for_batch(batch_id: str, timeout: float = 60.0) -> dict:
    import time

    deadline = time.time() + timeout
    body = client.get(f"/batches/{batch_id}").json()
    while body["status"] in ("pending", "running") and time.time() < deadline:
        time.sleep(0.5)
        body = client.get(f"/batches/{batch_id}").json()
    return body


@pytest.mark.slow
def test_chat_plan_and_execute_real_starburst_whole_schema_batch_uses_relocated_functions():
    """Executes the chat-driven batch plan end to end (federated_s3.burstbank,
    3 real tables) — proves migrate.run_starburst_schema_batch/
    start_starburst_schema_batch (relocated from chat.py) still work
    identically via the chat path, and that every item used G7's fast
    deterministic engine, never the old llm-transpile path."""
    plan_resp = client.post(
        "/chat/plan",
        json={"instruction": "batch-migrate schema burstbank in starburst catalog federated_s3"},
    )
    assert plan_resp.status_code == 200
    plan_body = plan_resp.json()
    assert plan_body["understood"] is True
    assert plan_body["action"]["kind"] == "migrate_starburst_schema_batch"

    exec_resp = client.post("/chat/execute", json={"plan_id": plan_body["plan_id"]})
    assert exec_resp.status_code == 200
    exec_body = exec_resp.json()
    assert exec_body["result_type"] == "batch"
    batch_id = exec_body["batch_id"]

    final = _wait_for_batch(batch_id)
    assert final["status"] in ("completed", "completed_with_errors")
    assert final["total_items"] == 3
    assert final["dispatched_items"] == 3

    detail = client.get(f"/batches/{batch_id}?include_migrations=true").json()
    migrations = detail["migrations"]
    assert len(migrations) == 3
    for mig in migrations:
        assert mig["source_system"] == "starburst"
        assert mig["engine"] == "starburst-custom-ddl"
        assert mig["engine"] != "llm-transpile-experimental"


@pytest.mark.slow
def test_starburst_schema_batch_rest_route_uses_fast_engine_not_llm():
    """Direct REST route (not chat): POST /migrate/starburst/catalog/
    {catalog}/schema/{schema}/batch on federated_s3.burstbank (3 real base
    tables). Confirms a real batch is created and every dispatched item
    used G7's fast deterministic engine tag, not the old LLM path."""
    # include_data=false pins this test to the DDL items only. G19 changed the
    # route's default to true (the user wants table rows carried over by
    # default), which would otherwise add one data-copy migration per table and
    # make the counts below wrong. What this test exists to prove — that the
    # DDL items use the fast deterministic engine, never the LLM path — is
    # unchanged.
    r = client.post("/migrate/starburst/catalog/federated_s3/schema/burstbank/batch?include_data=false")
    assert r.status_code == 200
    body = r.json()
    batch_id = body["id"]
    assert body["total_items"] == 3

    final = _wait_for_batch(batch_id)
    assert final["status"] in ("completed", "completed_with_errors")
    assert final["dispatched_items"] == 3

    detail = client.get(f"/batches/{batch_id}?include_migrations=true").json()
    migrations = detail["migrations"]
    assert len(migrations) == 3
    for mig in migrations:
        assert mig["source_system"] == "starburst"
        assert mig["engine"] == "starburst-custom-ddl"
        assert mig["engine"] != "llm-transpile-experimental"


# ---------------------------------------------------------------- G9 Databricks data-question fallback
# This test used to hardcode `redshift_public_venue`. That table is migration
# OUTPUT living in a demo schema which is periodically pruned and repopulated —
# and on 2026-08-02 it was dropped during a requested cleanup, so this test
# failed with `understood is False` for a reason that had nothing to do with the
# chat planner. A test that asserts "the planner resolves a real Databricks
# table" should discover a real table at runtime rather than pin a name whose
# lifetime it does not control.


@pytest.mark.slow
def test_chat_plan_and_execute_real_databricks_data_question_returns_real_rows():
    from app.connectors import databricks_browse
    from app.databricks_target import TARGET_CATALOG, TARGET_SCHEMA

    tables = [t.name for t in databricks_browse.list_tables(TARGET_CATALOG, TARGET_SCHEMA)]
    if not tables:
        pytest.skip(f"{TARGET_CATALOG}.{TARGET_SCHEMA} is empty — nothing real to query")
    table = sorted(tables)[0]

    plan_resp = client.post(
        "/chat/plan",
        json={"instruction": f"what's in {TARGET_CATALOG}.{TARGET_SCHEMA}.{table} in databricks"},
    )
    assert plan_resp.status_code == 200
    plan_body = plan_resp.json()
    assert plan_body["understood"] is True
    assert plan_body["action"]["kind"] == "databricks_query"
    assert plan_body["action"]["mode"] == "preview"
    assert plan_body["action"]["catalog"] == TARGET_CATALOG
    assert plan_body["action"]["schema"] == TARGET_SCHEMA
    assert plan_body["action"]["table"] == table

    exec_resp = client.post("/chat/execute", json={"plan_id": plan_body["plan_id"]})
    assert exec_resp.status_code == 200
    exec_body = exec_resp.json()
    assert exec_body["result_type"] == "query"
    assert isinstance(exec_body["columns"], list) and exec_body["columns"]
    assert isinstance(exec_body["rows"], list)
    assert exec_body["row_count"] == len(exec_body["rows"])
    if exec_body["rows"]:
        assert len(exec_body["rows"][0]) == len(exec_body["columns"])


@pytest.mark.slow
def test_chat_plan_databricks_ambiguous_or_unresolvable_question_is_refused_not_fabricated():
    r = client.post(
        "/chat/plan",
        json={"instruction": "show me the totally_made_up_table_xyz_123 table in databricks"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is False
    assert "reason" in body
    assert "action" not in body


def test_chat_plan_databricks_raw_select_injection_shaped_is_rejected_not_executed():
    r = client.post(
        "/chat/plan",
        json={"instruction": "databricks select * from foo; delete from foo"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is False
    assert "reason" in body
    assert "action" not in body

    r2 = client.post(
        "/chat/plan",
        json={"instruction": "databricks select * from foo; drop table foo"},
    )
    body2 = r2.json()
    assert body2["understood"] is False


# ---------------------------------------------------------------- G12 preview_source_table


@pytest.mark.slow
def test_chat_plan_and_execute_real_starburst_preview_returns_real_rows():
    """Real end-to-end: 'preview' a real starburst source table (no
    migration, no copy) and confirm real rows come back through the same
    result_type: "query" shape G9's databricks preview already uses."""
    plan_resp = client.post(
        "/chat/plan",
        json={
            "instruction": "preview the employee table in starburst catalog federated_postgres schema burstbank"
        },
    )
    assert plan_resp.status_code == 200
    plan_body = plan_resp.json()
    assert plan_body["understood"] is True
    assert plan_body["action"] == {
        "kind": "preview_source_table",
        "source_system": "starburst",
        "catalog": "federated_postgres",
        "schema": "burstbank",
        "table": "employee",
        "limit": 10,
    }

    exec_resp = client.post("/chat/execute", json={"plan_id": plan_body["plan_id"]})
    assert exec_resp.status_code == 200
    exec_body = exec_resp.json()
    assert exec_body["result_type"] == "query"
    assert isinstance(exec_body["columns"], list) and exec_body["columns"]
    assert isinstance(exec_body["rows"], list)
    assert exec_body["row_count"] == len(exec_body["rows"])
    if exec_body["rows"]:
        assert len(exec_body["rows"][0]) == len(exec_body["columns"])


@pytest.mark.slow
def test_chat_plan_and_execute_real_redshift_preview_returns_real_rows():
    plan_resp = client.post("/chat/plan", json={"instruction": "show me the data in venue table"})
    assert plan_resp.status_code == 200
    plan_body = plan_resp.json()
    assert plan_body["understood"] is True
    assert plan_body["action"] == {
        "kind": "preview_source_table",
        "source_system": "redshift",
        "schema": "public",
        "table": "venue",
        "limit": 10,
    }

    exec_resp = client.post("/chat/execute", json={"plan_id": plan_body["plan_id"]})
    assert exec_resp.status_code == 200
    exec_body = exec_resp.json()
    assert exec_body["result_type"] == "query"
    assert isinstance(exec_body["columns"], list) and exec_body["columns"]
    assert isinstance(exec_body["rows"], list)
    assert exec_body["row_count"] == len(exec_body["rows"])


@pytest.mark.slow
def test_chat_plan_preview_ambiguous_starburst_table_is_refused():
    """'customer'/'employee' both exist in two real starburst
    catalog.schema locations (see comment above) — unqualified preview must
    refuse, not guess."""
    r = client.post("/chat/plan", json={"instruction": "preview the customer table in starburst"})
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is False
    assert "action" not in body


def test_chat_plan_preview_unresolvable_redshift_table_is_refused():
    r = client.post("/chat/plan", json={"instruction": "show me the rows in totally_made_up_table_xyz_123"})
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is False
    assert "action" not in body


def test_chat_plan_copy_data_instruction_still_routes_to_copy_not_preview():
    """Regression: 'copy the data for table X in redshift' must still route
    to copy_table_data, not the new preview branch."""
    r = client.post(
        "/chat/plan",
        json={"instruction": "copy the data for venue table in redshift schema public"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is True
    assert body["action"]["kind"] == "copy_table_data"
    assert body["action"]["source_system"] == "redshift"
    assert body["action"]["name"] == "venue"


def test_chat_plan_migrate_instruction_still_routes_to_migrate_ddl_not_preview():
    """Regression: a plain 'migrate' instruction (no preview/show/query/
    display verb) must still route to migrate_ddl."""
    r = client.post("/chat/plan", json={"instruction": "migrate the venue table"})
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is True
    assert body["action"]["kind"] == "migrate_ddl"


def test_chat_plan_redshift_behavior_unchanged_by_starburst_addition():
    """Regression: plain redshift instructions (no 'starburst'/'trino'
    keyword) must resolve exactly as before G8."""
    r = client.post("/chat/plan", json={"instruction": "migrate the venue table"})
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is True
    assert body["action"] == {
        "kind": "migrate_ddl",
        "source_system": "redshift",
        "object_type": "table",
        "schema": "public",
        "name": "venue",
    }
    assert body["endpoint"] == "POST /migrate/redshift/ddl/table/public/venue"


# ---------------------------------------------------------------- G12 fix regression
# `_find_matching_databricks_table` already catches `DatabricksBrowseError`
# and turns it into a graceful ("error", "...") -> {"understood": False, ...}
# response. That contract only holds if `databricks_browse.list_catalogs()`
# actually raises `BrowseError` on a real connection failure instead of
# letting a raw `TargetError` escape (the bug fixed in this pass). Simulated
# here via monkeypatch since the real warehouse's daily query quota is
# exhausted in this environment.


def test_chat_plan_databricks_question_is_refused_gracefully_on_connection_failure(monkeypatch):
    def _boom():
        raise databricks_target.TargetError("daily query quota exceeded for warehouse")

    monkeypatch.setattr(databricks_target, "_connect", _boom)

    r = client.post(
        "/chat/plan",
        json={"instruction": "show me the venue table in databricks"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is False
    assert "reason" in body


def test_chat_plan_databricks_real_connection_error_surfaces_real_error_not_generic_mcp_message(monkeypatch):
    """Regression for the bug where ("error", payload) from
    `_find_matching_databricks_table` was silently collapsed into the same
    branch as genuine ("none", None) unresolvable-table results, discarding
    the real (already-redacted) error text and instead always reporting
    'the databricks mcp fallback is temporarily disabled' — even when the
    real problem was a live connection/quota failure unrelated to MCP."""

    def _boom():
        raise databricks_target.TargetError("BAD_REQUEST: hit your free daily limit for warehouse queries")

    monkeypatch.setattr(databricks_target, "_connect", _boom)

    r = client.post(
        "/chat/plan",
        json={"instruction": "show me the venue table in databricks"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is False
    assert "reason" in body
    assert "hit your free daily limit" in body["reason"]
    assert "mcp fallback is temporarily disabled" not in body["reason"]

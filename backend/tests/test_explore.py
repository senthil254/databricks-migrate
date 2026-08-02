"""Real integration tests against the live Redshift and Starburst systems
configured in backend/.env. No mocking — see MEMORY.md's 2026-08-01 entry
for the real object inventory these assertions are grounded in."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.credential_leak import _assert_no_real_credentials_in

client = TestClient(app)

REAL_REDSHIFT_TABLES = {"users", "venue", "category", "date", "event", "listing", "sales"}
REAL_REDSHIFT_FUNCTIONS = {"f_days_until_event", "f_ticket_price_category"}
REAL_REDSHIFT_PROCEDURES = {"sp_total_sales_by_venue"}
REAL_STARBURST_TABLE_SAMPLE = {"sales_fact", "customer_sales", "products", "employees"}


@pytest.mark.slow
def test_redshift_databases_real():
    r = client.get("/explore/redshift/databases")
    assert r.status_code == 200
    names = {d["name"] for d in r.json()}
    assert "dev" in names


@pytest.mark.slow
def test_redshift_schemas_real():
    r = client.get("/explore/redshift/schemas")
    assert r.status_code == 200
    names = {s["name"] for s in r.json()}
    assert "public" in names


@pytest.mark.slow
def test_redshift_tables_real():
    r = client.get("/explore/redshift/schemas/public/tables")
    assert r.status_code == 200
    got = {t["name"] for t in r.json()}
    assert REAL_REDSHIFT_TABLES.issubset(got), f"missing: {REAL_REDSHIFT_TABLES - got}"
    sales = next(t for t in r.json() if t["name"] == "sales")
    assert sales["type"] == "table"


@pytest.mark.slow
def test_redshift_columns_real():
    r = client.get("/explore/redshift/schemas/public/tables/sales/columns")
    assert r.status_code == 200
    cols = {c["name"] for c in r.json()}
    assert "pricepaid" in cols


@pytest.mark.slow
def test_redshift_routines_real_shows_created_function_and_procedure():
    r = client.get("/explore/redshift/schemas/public/routines")
    assert r.status_code == 200
    by_name = {rt["name"]: rt["type"] for rt in r.json()}
    for fn in REAL_REDSHIFT_FUNCTIONS:
        assert by_name.get(fn) == "FUNCTION", f"{fn} missing or wrong type: {by_name}"
    for proc in REAL_REDSHIFT_PROCEDURES:
        assert by_name.get(proc) == "PROCEDURE", f"{proc} missing or wrong type: {by_name}"


@pytest.mark.slow
def test_starburst_catalogs_real():
    r = client.get("/explore/starburst/catalogs")
    assert r.status_code == 200
    names = {c["name"] for c in r.json()}
    assert "mcp2ohio" in names
    assert "galaxy" in names


@pytest.mark.slow
def test_starburst_schemas_real():
    r = client.get("/explore/starburst/catalogs/mcp2ohio/schemas")
    assert r.status_code == 200
    names = {s["name"] for s in r.json()}
    assert "test_writes" in names


@pytest.mark.slow
def test_starburst_tables_real():
    r = client.get("/explore/starburst/catalogs/mcp2ohio/schemas/test_writes/tables")
    assert r.status_code == 200
    got = {t["name"] for t in r.json()}
    assert REAL_STARBURST_TABLE_SAMPLE.issubset(got), f"missing: {REAL_STARBURST_TABLE_SAMPLE - got}"
    assert len(got) >= 28


@pytest.mark.slow
def test_starburst_columns_real():
    r = client.get("/explore/starburst/catalogs/mcp2ohio/schemas/test_writes/tables/sales_fact/columns")
    assert r.status_code == 200
    cols = {c["name"] for c in r.json()}
    assert "region" in cols


@pytest.mark.slow
def test_starburst_udfs_real_shows_created_udf():
    r = client.get("/explore/starburst/udfs")
    assert r.status_code == 200
    names = {u["name"] for u in r.json()}
    assert "f_price_tier" in names


@pytest.mark.slow
def test_redshift_preview_real():
    r = client.get("/explore/redshift/schemas/public/tables/sales/preview")
    assert r.status_code == 200
    body = r.json()
    assert body["row_count"] <= 10
    assert "pricepaid" in body["columns"]
    assert len(body["rows"]) == body["row_count"]


@pytest.mark.slow
def test_redshift_preview_respects_limit_param():
    r = client.get("/explore/redshift/schemas/public/tables/sales/preview?limit=2")
    assert r.status_code == 200
    assert r.json()["row_count"] <= 2


def test_redshift_preview_rejects_bad_identifier_in_path():
    """_ident() guards schema/table interpolated into the FROM clause —
    Redshift's LIMIT is bound but the table/schema is not."""
    r = client.get("/explore/redshift/schemas/public/tables/x; DROP TABLE y--/preview")
    assert r.status_code in (404, 502)


@pytest.mark.slow
def test_starburst_preview_real():
    r = client.get("/explore/starburst/catalogs/mcp2ohio/schemas/test_writes/tables/sales_fact/preview")
    assert r.status_code == 200
    body = r.json()
    assert body["row_count"] <= 10
    assert "region" in body["columns"]
    assert len(body["rows"]) == body["row_count"]


@pytest.mark.slow
def test_starburst_preview_respects_limit_param():
    r = client.get("/explore/starburst/catalogs/mcp2ohio/schemas/test_writes/tables/sales_fact/preview?limit=2")
    assert r.status_code == 200
    assert r.json()["row_count"] <= 2


def test_starburst_preview_rejects_bad_identifier_in_path():
    """_ident() guards catalog/schema/table interpolated into the FROM
    clause — Trino's driver doesn't reliably bind LIMIT either, but limit
    is validated as an int, not attacker-controlled text."""
    r = client.get(
        "/explore/starburst/catalogs/mcp2ohio/schemas/test_writes/tables/x; DROP TABLE y--/preview"
    )
    assert r.status_code in (404, 502)


def test_starburst_rejects_bad_identifier_in_path():
    """_ident() guards against non-alnum names reaching a SHOW ... FROM
    statement — Trino doesn't support parameter binding there."""
    r = client.get("/explore/starburst/catalogs/mcp2ohio; DROP TABLE x/schemas")
    assert r.status_code in (404, 502)  # never 200 with attacker-controlled SQL run


def test_no_credentials_leak_in_any_explore_response():
    """Even a real connector failure must not surface the password/host in
    its error body. Point at a schema that doesn't exist to force an error
    path without touching real credentials handling."""
    r = client.get("/explore/redshift/schemas/definitely_not_a_real_schema/tables")
    body = r.text
    _assert_no_real_credentials_in(body)


# --- G17 Stage 1: Databricks (Unity Catalog) columns + functions. Live
# against the real warehouse, zero mocking, same as every other test here.

DBX_CATALOG = "lakebridge_demo"
DBX_SCHEMA = "g3_migrations"
DBX_TABLE = "redshift_demo_fast_test_customers"


def test_databricks_columns_real_shape():
    r = client.get(
        f"/explore/databricks/catalogs/{DBX_CATALOG}/schemas/{DBX_SCHEMA}/tables/{DBX_TABLE}/columns"
    )
    assert r.status_code == 200
    cols = r.json()
    assert cols, "real migrated table must have real columns"
    # Same keys the Redshift columns route returns — the frontend's shared
    # ColumnsList pattern depends on `name` + `data_type`.
    assert set(cols[0]) == {"name", "data_type", "ordinal"}
    assert {c["name"] for c in cols} >= {"id", "name"}


def test_databricks_functions_and_source_real():
    r = client.get(f"/explore/databricks/catalogs/{DBX_CATALOG}/schemas/{DBX_SCHEMA}/functions")
    assert r.status_code == 200
    fns = r.json()
    if not fns:
        pytest.skip("no UC functions in this schema right now")
    assert {"schema", "name", "type"} <= set(fns[0])
    name = fns[0]["name"]
    s = client.get(
        f"/explore/databricks/catalogs/{DBX_CATALOG}/schemas/{DBX_SCHEMA}/functions/{name}/source"
    )
    assert s.status_code == 200
    body = s.json()
    assert {"schema", "name", "type", "source"} <= set(body)
    assert isinstance(body["source"], str) and body["source"]  # never null: SourcePanel hangs on null


def test_databricks_function_source_404_for_unknown_function():
    r = client.get(
        f"/explore/databricks/catalogs/{DBX_CATALOG}/schemas/{DBX_SCHEMA}/functions/no_such_fn_xyz/source"
    )
    assert r.status_code == 404


def test_databricks_explore_rejects_bad_catalog_identifier():
    r = client.get(
        "/explore/databricks/catalogs/lakebridge_demo; DROP TABLE x/schemas/g3_migrations/functions"
    )
    assert r.status_code in (404, 502)
    assert "invalid identifier" in r.text or r.status_code == 404

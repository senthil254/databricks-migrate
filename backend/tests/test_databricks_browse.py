"""G8 — real Databricks (target) browse + preview tests.

Real-connection style (`@pytest.mark.slow`), matching test_migrate.py's
standard — no mocking of the live warehouse call itself. The identifier-
injection rejection test needs no live connection at all: `_ident()` raises
before any network call is made, mirroring test_security.py's
`test_copy_redshift_table_data_rejects_injection_shaped_identifiers`.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import databricks_target
from app.connectors import databricks_browse
from app.connectors.databricks_browse import BrowseError, list_catalogs, list_schemas, list_tables
from app.databricks_target import TARGET_CATALOG, TARGET_SCHEMA, TargetError, preview_table
from app.main import app

client = TestClient(app)


@pytest.mark.slow
def test_list_catalogs_real():
    catalogs = list_catalogs()
    assert isinstance(catalogs, list)
    assert TARGET_CATALOG in catalogs


@pytest.mark.slow
def test_list_schemas_real():
    schemas = list_schemas(TARGET_CATALOG)
    assert isinstance(schemas, list)
    assert TARGET_SCHEMA in schemas


@pytest.mark.slow
def test_list_tables_real():
    tables = list_tables(TARGET_CATALOG, TARGET_SCHEMA)
    assert isinstance(tables, list)
    for t in tables:
        assert t.catalog == TARGET_CATALOG
        assert t.schema == TARGET_SCHEMA
        assert t.type == "table"


@pytest.mark.slow
def test_preview_table_real():
    tables = list_tables(TARGET_CATALOG, TARGET_SCHEMA)
    if not tables:
        pytest.skip("no real tables in target schema yet to preview")
    columns, rows = preview_table(TARGET_CATALOG, TARGET_SCHEMA, tables[0].name, limit=5)
    assert isinstance(columns, list) and columns
    assert isinstance(rows, list)
    if rows:
        assert len(rows[0]) == len(columns)


@pytest.mark.slow
def test_endpoints_real():
    r = client.get("/explore/databricks/catalogs")
    assert r.status_code == 200
    names = [c["name"] for c in r.json()]
    assert TARGET_CATALOG in names

    r = client.get(f"/explore/databricks/catalogs/{TARGET_CATALOG}/schemas")
    assert r.status_code == 200
    assert TARGET_SCHEMA in [s["name"] for s in r.json()]

    r = client.get(f"/explore/databricks/catalogs/{TARGET_CATALOG}/schemas/{TARGET_SCHEMA}/tables")
    assert r.status_code == 200
    tables = r.json()
    assert isinstance(tables, list)
    if tables:
        table_name = tables[0]["name"]
        r = client.get(
            f"/explore/databricks/catalogs/{TARGET_CATALOG}/schemas/{TARGET_SCHEMA}"
            f"/tables/{table_name}/preview?limit=5"
        )
        assert r.status_code == 200
        body = r.json()
        assert "columns" in body and "rows" in body and "row_count" in body


@pytest.mark.parametrize(
    "bad_identifier",
    [
        "a; DROP TABLE foo",
        "a`; DROP TABLE foo; --",
        "a/**/OR/**/1=1",
        "'; DELETE FROM x; --",
    ],
)
def test_preview_table_rejects_injection_shaped_identifiers(bad_identifier):
    """No live connection needed — `_ident()` raises before any network call."""
    with pytest.raises(TargetError):
        preview_table(bad_identifier, TARGET_SCHEMA, "some_table")
    with pytest.raises(TargetError):
        preview_table(TARGET_CATALOG, bad_identifier, "some_table")
    with pytest.raises(TargetError):
        preview_table(TARGET_CATALOG, TARGET_SCHEMA, bad_identifier)


def test_list_schemas_rejects_injection_shaped_catalog():
    """databricks_browse.list_schemas uses the same _ident() guard — no
    live connection needed since the guard raises first."""
    with pytest.raises(BrowseError):
        list_schemas("a; DROP TABLE foo")


def test_list_tables_rejects_injection_shaped_identifiers():
    with pytest.raises(BrowseError):
        list_tables("a; DROP TABLE foo", TARGET_SCHEMA)
    with pytest.raises(BrowseError):
        list_tables(TARGET_CATALOG, "a; DROP TABLE foo")


def test_preview_endpoint_rejects_injection_shaped_identifier_via_api():
    r = client.get(
        "/explore/databricks/catalogs/lakebridge_demo;%20DROP%20TABLE%20x/schemas/foo/tables/bar/preview"
    )
    assert r.status_code == 502


# ---------------------------------------------------------------- G12 fix regression
# `list_catalogs()` used to call `databricks_target._connect()` OUTSIDE its own
# try/except, so a real connection failure (a `TargetError`, e.g. the
# warehouse's daily query quota being exhausted) propagated raw instead of
# being caught and re-wrapped as `BrowseError`. No live connection is needed
# to prove the fix: `_connect()` is monkeypatched to raise `TargetError`
# directly, exactly what a real quota-exhaustion failure looks like.


def test_list_catalogs_wraps_connect_failure_as_browse_error(monkeypatch):
    def _boom():
        raise TargetError("daily query quota exceeded for warehouse abc123 token=SECRETVALUE")

    monkeypatch.setattr(databricks_target, "_connect", _boom)
    with pytest.raises(BrowseError) as exc_info:
        list_catalogs()
    assert "SECRETVALUE" not in str(exc_info.value)


def test_list_schemas_wraps_connect_failure_as_browse_error(monkeypatch):
    def _boom():
        raise TargetError("daily query quota exceeded token=SECRETVALUE")

    monkeypatch.setattr(databricks_target, "_connect", _boom)
    with pytest.raises(BrowseError) as exc_info:
        list_schemas(TARGET_CATALOG)
    assert "SECRETVALUE" not in str(exc_info.value)


def test_list_tables_wraps_connect_failure_as_browse_error(monkeypatch):
    def _boom():
        raise TargetError("daily query quota exceeded token=SECRETVALUE")

    monkeypatch.setattr(databricks_target, "_connect", _boom)
    with pytest.raises(BrowseError) as exc_info:
        list_tables(TARGET_CATALOG, TARGET_SCHEMA)
    assert "SECRETVALUE" not in str(exc_info.value)


def test_catalogs_endpoint_returns_graceful_error_not_500_on_connect_failure(monkeypatch):
    """The REST endpoint should surface a controlled error (502-style,
    handled by main.py's route), not an unhandled 500 from a raw
    TargetError leaking out of list_catalogs()."""

    def _boom():
        raise TargetError("daily query quota exceeded")

    monkeypatch.setattr(databricks_target, "_connect", _boom)
    r = client.get("/explore/databricks/catalogs")
    assert r.status_code != 500

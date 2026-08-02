"""G7 — custom, deterministic Starburst pipeline tests.

Unlike test_migrate.py's real-integration style, these are deliberately
mocked at the connector boundary (per the approved plan) so the
"zero calls into any llm-transpile/subprocess code path" assertions and
the injection regression can run with no live connection, matching this
project's existing `test_security.py` pattern for the equivalent Redshift
regression.

Real-shaped fixtures below (varchar/decimal(p,s)/timestamp(6)/SECURITY
DEFINER) are taken directly from the live `mcp2ohio` probe documented in
starburst_type_map.py's module docstring — not invented.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.connectors.starburst import Column
from app.databricks_target import create_target_table
from app.starburst_type_map import databricks_type_for_trino


# ---------------------------------------------------------------- type map

@pytest.mark.parametrize(
    "trino_type,expected",
    [
        ("varchar", "STRING"),
        ("varchar(50)", "STRING"),  # defensive — real live shape drops the length, but handle it anyway
        ("char", "STRING"),
        ("integer", "INT"),
        ("int", "INT"),
        ("bigint", "BIGINT"),
        ("smallint", "SMALLINT"),
        ("tinyint", "TINYINT"),
        ("double", "DOUBLE"),
        ("real", "FLOAT"),
        ("boolean", "BOOLEAN"),
        ("date", "DATE"),
        ("timestamp", "TIMESTAMP"),
        ("timestamp(6)", "TIMESTAMP"),  # real live shape
        ("timestamp with time zone", "TIMESTAMP"),
        ("timestamp(6) with time zone", "TIMESTAMP"),  # real live shape
    ],
)
def test_databricks_type_for_trino_known_types(trino_type, expected):
    assert databricks_type_for_trino(trino_type) == expected


def test_databricks_type_for_trino_decimal_preserves_precision_and_scale():
    # information_schema.columns real live shape (no space)
    assert databricks_type_for_trino("decimal(10,2)") == "DECIMAL(10,2)"
    # SHOW CREATE TABLE real live shape (space after comma)
    assert databricks_type_for_trino("decimal(10, 2)") == "DECIMAL(10,2)"
    assert databricks_type_for_trino("decimal(38,18)") == "DECIMAL(38,18)"


def test_databricks_type_for_trino_bare_decimal_fallback():
    assert databricks_type_for_trino("decimal") == "DECIMAL(38,18)"


@pytest.mark.parametrize("complex_type", ["array(varchar)", "row(a integer, b varchar)", "map(varchar, integer)"])
def test_databricks_type_for_trino_complex_types_fall_back_to_string(complex_type):
    """Honest fallback, not a fabricated guess — matches the module
    docstring's documented behavior."""
    assert databricks_type_for_trino(complex_type) == "STRING"


# ---------------------------------------------------------------- ddl translator

def test_translate_table_ddl_maps_real_shaped_columns():
    from app.starburst_ddl_translator import translate_table_ddl

    columns = [
        Column(name="id", data_type="integer"),
        Column(name="name", data_type="varchar"),
        Column(name="amount", data_type="decimal(10,2)"),
        Column(name="created_at", data_type="timestamp(6)"),
    ]
    with patch("app.starburst_ddl_translator.starburst_conn.list_columns", return_value=columns) as mock_cols:
        ddl, mapped = translate_table_ddl("mcp2ohio", "test_writes", "g7_type_probe")

    mock_cols.assert_called_once_with("mcp2ohio", "test_writes", "g7_type_probe")
    assert mapped == [
        ("id", "INT"),
        ("name", "STRING"),
        ("amount", "DECIMAL(10,2)"),
        ("created_at", "TIMESTAMP"),
    ]
    assert "CREATE TABLE `g7_type_probe`" in ddl
    assert "`amount` DECIMAL(10,2)" in ddl
    assert "`created_at` TIMESTAMP" in ddl


def test_translate_view_ddl_strips_security_definer_real_shaped_input():
    from app.starburst_ddl_translator import translate_view_ddl

    # real live SHOW CREATE VIEW shape (see MEMORY.md's G7 entry)
    real_shaped_ddl = (
        "CREATE VIEW mcp2ohio.test_writes.g7_view_probe SECURITY DEFINER AS\n"
        "SELECT\n"
        "  product_name\n"
        ", price\n"
        "FROM\n"
        "  mcp2ohio.test_writes.products\n"
        "WHERE (price > 10)"
    )
    with patch("app.starburst_ddl_translator.starburst_conn.get_view_ddl", return_value=real_shaped_ddl) as mock_ddl:
        result = translate_view_ddl("mcp2ohio", "test_writes", "g7_view_probe")

    mock_ddl.assert_called_once_with("mcp2ohio", "test_writes", "g7_view_probe")
    assert "SECURITY DEFINER" not in result
    assert "CREATE VIEW mcp2ohio.test_writes.g7_view_probe AS" in result
    assert "product_name" in result


# ---------------------------------------------------------------- migrate_starburst_ddl_custom

def test_migrate_starburst_ddl_custom_rejects_unsupported_object_type():
    from app.migrate import migrate_starburst_ddl_custom

    mig = migrate_starburst_ddl_custom("procedure", "mcp2ohio", "test_writes", "whatever")
    assert mig.status.value == "failed"
    assert "unsupported object_type" in mig.error.lower()


def test_migrate_starburst_ddl_custom_success_path_never_calls_llm_transpile():
    from app import migrate

    columns = [Column(name="id", data_type="integer"), Column(name="name", data_type="varchar")]
    with (
        patch("app.migrate.starburst_conn.get_table_ddl", return_value="CREATE TABLE ...") as mock_get_ddl,
        patch("app.starburst_ddl_translator.starburst_conn.list_columns", return_value=columns),
        patch("app.migrate._run_lakebridge") as mock_run_lakebridge,
        # G19/G20: `migrate` now applies the transpiled DDL to Databricks, and
        # first checks whether the object is already there. Both are patched so
        # this stays what it was written to be — a no-network test of the ENGINE
        # CHOICE (custom path, never llm-transpile). Warehouse execution is
        # covered by the real integration tests.
        patch("app.migrate.databricks_target.object_exists", return_value=False),
        patch(
            "app.migrate.databricks_target.create_object_from_ddl",
            return_value="lakebridge_demo.g3_migrations.starburst_mcp2ohio_test_writes_products",
        ),
    ):
        mig = migrate.migrate_starburst_ddl_custom("table", "mcp2ohio", "test_writes", "products")

    assert mig.status.value == "completed"
    assert mig.engine.value == "starburst-custom-ddl"
    assert "CREATE TABLE" in mig.output_ddl
    mock_get_ddl.assert_called_once_with("mcp2ohio", "test_writes", "products")
    mock_run_lakebridge.assert_not_called()  # zero calls into the LLM/lakebridge path


# ---------------------------------------------------------------- copy_starburst_table_data

def test_copy_starburst_table_data_happy_path():
    from app import migrate

    columns = [Column(name="id", data_type="integer"), Column(name="name", data_type="varchar")]
    rows = [(1, "a"), (2, "b")]
    with (
        patch("app.migrate.starburst_conn.list_columns", return_value=columns),
        patch("app.migrate.starburst_conn.read_table_rows", return_value=rows) as mock_read,
        patch("app.migrate.databricks_target.create_target_table", return_value="lakebridge_demo.g3_migrations.starburst_mcp2ohio_test_writes_products") as mock_create,
        patch("app.migrate.databricks_target.insert_rows", return_value=2) as mock_insert,
        # G20: copy_* now calls object_exists() purely to report whether the
        # target already existed. Patched so `execute` stays the single
        # verification SELECT COUNT(*) this test asserts on, and so the test
        # needs no live warehouse.
        patch("app.migrate.databricks_target.object_exists", return_value=False),
        patch("app.migrate.databricks_target.execute", return_value=[(2,)]) as mock_execute,
    ):
        mig = migrate.copy_starburst_table_data("mcp2ohio", "test_writes", "products")

    assert mig.status.value == "completed"
    assert mig.row_count == 2
    assert "target rows after insert (verified via SELECT COUNT(*)): 2" in mig.output_ddl
    mock_read.assert_called_once_with("mcp2ohio", "test_writes", "products", ["id", "name"])
    mock_create.assert_called_once()
    assert mock_create.call_args.kwargs["type_mapper"].__name__ == "databricks_type_for_trino"
    mock_insert.assert_called_once()
    mock_execute.assert_called_once()
    # G8: target fields must be populated with the real values used above,
    # not left None now that a real target table exists.
    from app import databricks_target
    assert mig.target_catalog == databricks_target.TARGET_CATALOG
    assert mig.target_schema == databricks_target.TARGET_SCHEMA
    assert mig.target_table == "starburst_mcp2ohio_test_writes_products"


def test_copy_starburst_table_data_rejects_injection_shaped_identifiers():
    """Mirrors test_security.py's Redshift injection regression exactly —
    no live connection needed, _ident() rejects before any SQL is built."""
    from app.migrate import copy_starburst_table_data

    mig = copy_starburst_table_data("mcp2ohio", "test_writes", 'evil" ; DROP TABLE x --')
    assert mig.status.value == "failed"
    assert mig.error is not None
    assert "invalid identifier" in mig.error.lower()


def test_copy_starburst_table_data_rejects_injection_shaped_catalog():
    from app.migrate import copy_starburst_table_data

    mig = copy_starburst_table_data('mcp2ohio"; DROP TABLE x; --', "test_writes", "products")
    assert mig.status.value == "failed"
    assert mig.error is not None
    assert "invalid identifier" in mig.error.lower()


# ---------------------------------------------------------------- type_mapper regression

def test_create_target_table_default_type_mapper_unchanged_for_redshift():
    """Regression: create_target_table's new optional type_mapper param
    must default to the existing Redshift mapper so the Redshift call
    site's behavior is provably unchanged."""
    with patch("app.databricks_target.execute") as mock_execute:
        create_target_table("some_table", [("id", "integer"), ("name", "character varying"), ("amt", "numeric")])

    create_call = mock_execute.call_args_list[1]
    created_sql = create_call.args[0]
    assert "`id` INT" in created_sql
    assert "`name` STRING" in created_sql
    assert "`amt` DECIMAL(18,4)" in created_sql  # existing Redshift numeric mapping, untouched


def test_create_target_table_custom_type_mapper_used_when_passed():
    with patch("app.databricks_target.execute") as mock_execute:
        create_target_table(
            "some_table",
            [("amount", "decimal(10,2)")],
            type_mapper=databricks_type_for_trino,
        )

    created_sql = mock_execute.call_args_list[1].args[0]
    assert "`amount` DECIMAL(10,2)" in created_sql

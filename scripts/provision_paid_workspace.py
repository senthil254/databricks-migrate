"""Provision the paid Databricks workspace with everything the app needs.

Idempotent: safe to re-run. Every statement goes through the app's own
`databricks_target.execute()` so this script exercises the same code path the
running app uses — a provisioning script that used a different connection
would prove less than nothing.

What it builds
--------------
  lakebridge_demo                          catalog
    g3_migrations                          schema  — the migration TARGET
    migration_lab                          schema  — Lakebridge llm-transpile staging
      landing                              volume  — llm-transpile needs a real volume
        seed/customers.csv                 real bytes, written via the Files API
        seed/orders.parquet                real bytes, written via the Files API
    demo_seed                              schema  — files read back as tables
      customers_csv                        table loaded from the CSV
      orders_parquet                       table loaded from the parquet
    g3_migrations.mcp_fallback_ping         UC function (a test depends on it)
    demo_seed.demo_customer_tenure          UC function (demo path)

`g3_migrations` is the migration TARGET schema and is kept deliberately sparse —
only `mcp_fallback_ping` is seeded there, because a test asserts it exists and
does not create it. Everything else in that schema should be something a
migration actually produced.

Files cannot be written to a UC volume from a SQL warehouse, so the two data
files go through the Files API (`WorkspaceClient.files.upload`) and are then
read back with COPY INTO. Reading them back is the point: it proves the volume
is real and usable, not merely that CREATE VOLUME parsed.

Run:  backend/.venv/bin/python scripts/provision_paid_workspace.py
"""
from __future__ import annotations

import csv
import io
import os
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND / ".env")

from app import databricks_target as dt  # noqa: E402

CATALOG = dt.TARGET_CATALOG
VOLUME_PATH = f"/Volumes/{CATALOG}/migration_lab/landing"

_ok, _fail = [], []


def step(label: str, fn):
    """Run one provisioning step. A failure is recorded and reported at the
    end rather than aborting — a partial provision that says exactly which
    parts failed is more useful than a traceback halfway through."""
    try:
        fn()
        _ok.append(label)
        print(f"  ok    {label}")
    except Exception as exc:  # noqa: BLE001
        _fail.append((label, str(exc)[:300]))
        print(f"  FAIL  {label}: {str(exc)[:300]}")


def sql(statement: str):
    return lambda: dt.execute(statement)


# ---------------------------------------------------------------- structure
def provision_structure() -> None:
    print("\n[1] catalog / schemas / volume")
    step("catalog", sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG}"))
    for schema in ("g3_migrations", "migration_lab", "demo_seed"):
        step(f"schema {schema}", sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{schema}"))
    step(
        "volume landing",
        sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.migration_lab.landing"),
    )


# ---------------------------------------------------------------- tables
_TABLES = {
    "demo_customers": (
        """CREATE TABLE IF NOT EXISTS {c}.demo_seed.demo_customers (
               customer_id BIGINT, full_name STRING, city STRING,
               signup_date DATE, lifetime_value DECIMAL(12,2))""",
        """INSERT INTO {c}.demo_seed.demo_customers VALUES
             (1,'Ada Lovelace','London',DATE'2021-03-04',18450.75),
             (2,'Grace Hopper','New York',DATE'2020-11-19',29310.00),
             (3,'Alan Turing','Manchester',DATE'2022-06-01',7220.40),
             (4,'Katherine Johnson','Hampton',DATE'2019-02-27',41005.10),
             (5,'Radia Perlman','Boston',DATE'2023-08-15',3390.65)""",
    ),
    "demo_orders": (
        """CREATE TABLE IF NOT EXISTS {c}.demo_seed.demo_orders (
               order_id BIGINT, customer_id BIGINT, order_ts TIMESTAMP,
               amount DECIMAL(10,2), status STRING)""",
        """INSERT INTO {c}.demo_seed.demo_orders VALUES
             (1001,1,TIMESTAMP'2024-01-05 09:14:00',210.50,'shipped'),
             (1002,2,TIMESTAMP'2024-01-07 16:02:00',1899.99,'shipped'),
             (1003,1,TIMESTAMP'2024-02-11 11:45:00',75.00,'returned'),
             (1004,3,TIMESTAMP'2024-03-02 08:30:00',430.25,'pending'),
             (1005,4,TIMESTAMP'2024-03-19 19:20:00',2210.00,'shipped'),
             (1006,5,TIMESTAMP'2024-04-01 13:05:00',59.95,'cancelled')""",
    ),
    "demo_products": (
        """CREATE TABLE IF NOT EXISTS {c}.demo_seed.demo_products (
               product_id BIGINT, sku STRING, name STRING,
               unit_price DECIMAL(10,2), in_stock BOOLEAN)""",
        """INSERT INTO {c}.demo_seed.demo_products VALUES
             (1,'SKU-100','Analytical Engine Kit',4999.00,true),
             (2,'SKU-200','COBOL Reference',49.50,true),
             (3,'SKU-300','Bombe Replica',15750.00,false),
             (4,'SKU-400','Orbital Slide Rule',129.99,true)""",
    ),
}


def _row_count(fq: str) -> int:
    return int(dt.execute(f"SELECT count(*) FROM {fq}")[0][0])


def provision_tables() -> None:
    print("\n[2] managed tables + rows")
    for name, (ddl, insert) in _TABLES.items():
        fq = f"{CATALOG}.demo_seed.{name}"
        step(f"table {name}", sql(ddl.format(c=CATALOG)))
        # Idempotent: only seed when empty, so a re-run doesn't duplicate rows.
        def seed(fq=fq, insert=insert):
            if _row_count(fq) == 0:
                dt.execute(insert.format(c=CATALOG))
        step(f"rows  {name}", seed)


# ---------------------------------------------------------------- functions
_FUNCTIONS = {
    # A test depends on this one existing by name.
    "mcp_fallback_ping": f"""
        CREATE OR REPLACE FUNCTION {CATALOG}.g3_migrations.mcp_fallback_ping(note STRING)
        RETURNS STRING
        COMMENT 'Reachability probe for the Databricks Managed MCP fallback.'
        RETURN concat('pong: ', note)
    """,
    # Lives in demo_seed, NOT g3_migrations. g3_migrations is the migration
    # TARGET schema and is kept deliberately sparse so it shows only what a
    # migration actually produced — a seed function sitting there looks like a
    # migrated object and muddies exactly the thing being demonstrated.
    "demo_customer_tenure": f"""
        CREATE OR REPLACE FUNCTION {CATALOG}.demo_seed.demo_customer_tenure(signup DATE)
        RETURNS INT
        COMMENT 'Whole years between signup and today.'
        RETURN floor(datediff(current_date(), signup) / 365)
    """,
}


def provision_functions() -> None:
    print("\n[3] UC functions")
    for name, ddl in _FUNCTIONS.items():
        step(f"function {name}", sql(ddl))


# ---------------------------------------------------------------- files
def _csv_bytes() -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["customer_id", "full_name", "city", "lifetime_value"])
    for row in [
        (1, "Ada Lovelace", "London", "18450.75"),
        (2, "Grace Hopper", "New York", "29310.00"),
        (3, "Alan Turing", "Manchester", "7220.40"),
        (4, "Katherine Johnson", "Hampton", "41005.10"),
        (5, "Radia Perlman", "Boston", "3390.65"),
    ]:
        w.writerow(row)
    return buf.getvalue().encode()


def _parquet_bytes() -> bytes:
    """Real parquet bytes, generated in a THROWAWAY environment.

    Do not `pip install pyarrow` into backend/.venv to make this work. Doing so
    once during this build made the backend test suite die with a segmentation
    fault (exit 139) inside test_databricks_mcp_client.py — pyarrow changes
    databricks-sql-connector's fetch path, and the app has always run without
    it. Removing pyarrow restored the suite (107 passed).

    So: shell out to `uv run --with pyarrow`, which builds an ephemeral env and
    leaves backend/.venv untouched. Returns b'' if that isn't possible, so the
    caller skips honestly rather than uploading a file that is not parquet.
    """
    script = (
        "import io,sys,pyarrow as pa,pyarrow.parquet as pq\n"
        "t=pa.table({'order_id':[1001,1002,1003,1004,1005,1006],"
        "'customer_id':[1,2,1,3,4,5],"
        "'amount':[210.50,1899.99,75.00,430.25,2210.00,59.95],"
        "'status':['shipped','shipped','returned','pending','shipped','cancelled']})\n"
        "b=io.BytesIO(); pq.write_table(t,b); sys.stdout.buffer.write(b.getvalue())\n"
    )
    try:
        import subprocess

        proc = subprocess.run(
            ["uv", "run", "--quiet", "--with", "pyarrow", "python", "-c", script],
            capture_output=True, timeout=300,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return b""
    return proc.stdout if proc.returncode == 0 and proc.stdout else b""


def provision_files() -> None:
    """Write real bytes into the UC volume, then read them back as tables.

    Uses the Files API because a SQL warehouse cannot write files. The
    read-back with COPY INTO is what actually proves the volume works.
    """
    print("\n[4] files in the volume (Files API) + read back")
    from databricks.sdk import WorkspaceClient

    from app.executor import databricks_config

    w = WorkspaceClient(config=databricks_config())

    def upload(name: str, data: bytes):
        w.files.upload(f"{VOLUME_PATH}/seed/{name}", io.BytesIO(data), overwrite=True)

    step("upload customers.csv", lambda: upload("customers.csv", _csv_bytes()))

    pq_bytes = _parquet_bytes()
    if pq_bytes:
        step("upload orders.parquet", lambda: upload("orders.parquet", pq_bytes))
    else:
        _fail.append(("upload orders.parquet", "could not generate parquet (needs `uv`) — skipped, NOT written"))
        print("  SKIP  upload orders.parquet: could not generate parquet bytes")

    step(
        "table customers_csv",
        sql(
            f"""CREATE TABLE IF NOT EXISTS {CATALOG}.demo_seed.customers_csv
                (customer_id BIGINT, full_name STRING, city STRING, lifetime_value DOUBLE)"""
        ),
    )
    step(
        "load  customers_csv",
        # Explicit casts in a subquery rather than FORMAT_OPTIONS inferSchema:
        # inference types customer_id as INT, which will not merge into the
        # declared BIGINT column (DELTA_FAILED_TO_MERGE_FIELDS).
        sql(
            f"""COPY INTO {CATALOG}.demo_seed.customers_csv
                FROM (
                  SELECT CAST(customer_id AS BIGINT)      AS customer_id,
                         CAST(full_name AS STRING)        AS full_name,
                         CAST(city AS STRING)             AS city,
                         CAST(lifetime_value AS DOUBLE)   AS lifetime_value
                  FROM '{VOLUME_PATH}/seed/customers.csv'
                )
                FILEFORMAT = CSV
                FORMAT_OPTIONS ('header' = 'true')"""
        ),
    )

    if pq_bytes:
        step(
            "table orders_parquet",
            sql(
                f"""CREATE TABLE IF NOT EXISTS {CATALOG}.demo_seed.orders_parquet
                    (order_id BIGINT, customer_id BIGINT, amount DOUBLE, status STRING)"""
            ),
        )
        step(
            "load  orders_parquet",
            sql(
                f"""COPY INTO {CATALOG}.demo_seed.orders_parquet
                    FROM (
                      SELECT CAST(order_id AS BIGINT)    AS order_id,
                             CAST(customer_id AS BIGINT) AS customer_id,
                             CAST(amount AS DOUBLE)      AS amount,
                             CAST(status AS STRING)      AS status
                      FROM '{VOLUME_PATH}/seed/orders.parquet'
                    )
                    FILEFORMAT = PARQUET"""
            ),
        )


def main() -> int:
    print(f"Provisioning {CATALOG} on {dt._WAREHOUSE_HOSTNAME}")
    provision_structure()
    provision_tables()
    provision_functions()
    provision_files()

    print(f"\n{len(_ok)} ok, {len(_fail)} failed")
    for label, err in _fail:
        print(f"  FAILED: {label}: {err}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())

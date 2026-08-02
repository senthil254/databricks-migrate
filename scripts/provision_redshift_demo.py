"""Create small, clean Redshift demo fixtures.

Idempotent: safe to re-run (DROP IF EXISTS then CREATE, tiny row counts).

Why these shapes
----------------
Every column uses a type that survives the Redshift -> Databricks path cleanly:
INTEGER, VARCHAR, DECIMAL, DATE, BOOLEAN. Deliberately avoided:

  * CHAR(n)  — the Morpheus transpiler mis-handles it
    (UNSUPPORTED_CHAR_OR_VARCHAR_AS_STRING); `public.g14_charlen_test` exists
    precisely to document that defect and is not something to demo.
  * huge tables — `public` is the TICKIT sample set, and a whole-schema batch
    over it was measured at 15/27 items in ~25 minutes because it copies real
    rows. Small tables keep a schema batch to seconds.

  demo_fast_test  (existing schema, 3 tables added)
    products, regions, payments
  demo_schema_test (new schema, 2 tables)
    departments, employees

`demo_schema_test` exists so "batch migrate the whole schema" finishes fast:
2 tables and no routines = 4 batch items (each table expands to DDL + data).

Run:  backend/.venv/bin/python scripts/provision_redshift_demo.py
"""
from __future__ import annotations

import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND / ".env")

from app.connectors import redshift as redshift_conn  # noqa: E402

# (schema, table, create_sql, insert_sql)
FIXTURES: list[tuple[str, str, str, str]] = [
    (
        "demo_fast_test", "products",
        """CREATE TABLE demo_fast_test.products (
               product_id   INTEGER       NOT NULL,
               sku          VARCHAR(20)   NOT NULL,
               product_name VARCHAR(60)   NOT NULL,
               unit_price   DECIMAL(10,2) NOT NULL,
               in_stock     BOOLEAN       NOT NULL
           )""",
        """INSERT INTO demo_fast_test.products VALUES
             (1,'SKU-1001','Wireless Mouse',       25.99, true),
             (2,'SKU-1002','Mechanical Keyboard',  89.50, true),
             (3,'SKU-1003','27in Monitor',        249.00, false),
             (4,'SKU-1004','USB-C Dock',          139.95, true),
             (5,'SKU-1005','Laptop Stand',         45.00, true),
             (6,'SKU-1006','Noise Cancelling Headset', 199.99, false)""",
    ),
    (
        "demo_fast_test", "regions",
        """CREATE TABLE demo_fast_test.regions (
               region_id   INTEGER     NOT NULL,
               region_name VARCHAR(40) NOT NULL,
               country     VARCHAR(40) NOT NULL
           )""",
        """INSERT INTO demo_fast_test.regions VALUES
             (1,'North East','United States'),
             (2,'West Coast','United States'),
             (3,'Midlands','United Kingdom'),
             (4,'Bavaria','Germany'),
             (5,'South India','India')""",
    ),
    (
        "demo_fast_test", "payments",
        """CREATE TABLE demo_fast_test.payments (
               payment_id     INTEGER       NOT NULL,
               order_id       INTEGER       NOT NULL,
               amount         DECIMAL(10,2) NOT NULL,
               paid_on        DATE          NOT NULL,
               payment_method VARCHAR(20)   NOT NULL
           )""",
        """INSERT INTO demo_fast_test.payments VALUES
             (5001, 1, 120.50, DATE '2024-01-15','card'),
             (5002, 2, 89.99,  DATE '2024-01-22','bank_transfer'),
             (5003, 3, 249.00, DATE '2024-02-03','card'),
             (5004, 4, 45.00,  DATE '2024-02-19','paypal'),
             (5005, 5, 310.75, DATE '2024-03-07','card'),
             (5006, 6, 15.25,  DATE '2024-03-28','bank_transfer'),
             (5007, 7, 199.99, DATE '2024-04-11','card'),
             (5008, 8, 62.40,  DATE '2024-04-30','paypal')""",
    ),
    (
        "demo_schema_test", "departments",
        """CREATE TABLE demo_schema_test.departments (
               department_id   INTEGER     NOT NULL,
               department_name VARCHAR(40) NOT NULL,
               location        VARCHAR(40) NOT NULL
           )""",
        """INSERT INTO demo_schema_test.departments VALUES
             (10,'Engineering','London'),
             (20,'Finance','New York'),
             (30,'Marketing','Berlin'),
             (40,'Support','Bangalore'),
             (50,'Operations','Toronto')""",
    ),
    (
        "demo_schema_test", "employees",
        """CREATE TABLE demo_schema_test.employees (
               employee_id   INTEGER       NOT NULL,
               full_name     VARCHAR(60)   NOT NULL,
               department_id INTEGER       NOT NULL,
               hired_on      DATE          NOT NULL,
               salary        DECIMAL(10,2) NOT NULL
           )""",
        """INSERT INTO demo_schema_test.employees VALUES
             (1,'Amara Osei',      10, DATE '2021-03-01', 82000.00),
             (2,'Ravi Krishnan',   20, DATE '2020-07-15', 74500.00),
             (3,'Elena Petrova',   30, DATE '2022-01-10', 68000.00),
             (4,'Tom Whitfield',   40, DATE '2023-05-22', 51000.00),
             (5,'Mei Lin Chen',    50, DATE '2019-11-04', 91000.00)""",
    ),
]

SCHEMAS = ["demo_fast_test", "demo_schema_test"]


def main() -> int:
    conn = redshift_conn._connect()
    ok, failed = [], []
    try:
        cur = conn.cursor()
        for s in SCHEMAS:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {s}")
            print(f"  ok    schema {s}")
        for schema, table, create_sql, insert_sql in FIXTURES:
            fq = f"{schema}.{table}"
            try:
                # DROP+CREATE rather than IF NOT EXISTS: a re-run must give the
                # same row counts, not append duplicates.
                cur.execute(f"DROP TABLE IF EXISTS {fq}")
                cur.execute(create_sql)
                cur.execute(insert_sql)
                cur.execute(f"SELECT COUNT(*) FROM {fq}")
                n = cur.fetchone()[0]
                ok.append((fq, n))
                print(f"  ok    {fq}  ({n} rows)")
            except Exception as exc:  # noqa: BLE001
                failed.append((fq, str(exc)[:200]))
                print(f"  FAIL  {fq}: {str(exc)[:200]}")
        conn.commit()
    finally:
        conn.close()

    print(f"\n{len(ok)} tables created, {len(failed)} failed")
    for fq, err in failed:
        print(f"  FAILED {fq}: {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""ONE-OFF setup script (G18, plan section 6) — NOT app code.

Creates real, small, readable demo routines that the UI will display as
source code:

  * Redshift  demo_fast_test.sp_top_customers      (stored PROCEDURE)
  * Redshift  demo_fast_test.f_customer_tenure     (SQL FUNCTION)
  * Starburst galaxy.functions.f_order_size        (SQL FUNCTION)

Both Redshift routines reference the REAL tables that already exist in
demo_fast_test: customers(id, name, signup_year) and
orders(id, customer_id, amount).

No Starburst PROCEDURE is created: CREATE PROCEDURE is a grammar-level
SYNTAX_ERROR on Trino/Starburst — the feature does not exist, and faking
one is forbidden by this project's rules.

Run:  cd backend && .venv/bin/python ../scripts/create_sample_routines.py
"""
from __future__ import annotations

import os
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND / ".env")

from app.connectors import redshift as rs  # noqa: E402
from app.connectors import starburst as sb  # noqa: E402

SCHEMA = "demo_fast_test"

REDSHIFT_PROCEDURE = f"""
CREATE OR REPLACE PROCEDURE {SCHEMA}.sp_top_customers(min_spend FLOAT)
AS $$
BEGIN
    DROP TABLE IF EXISTS {SCHEMA}.top_customers;
    CREATE TABLE {SCHEMA}.top_customers AS
    SELECT c.id            AS customer_id,
           c.name          AS customer_name,
           c.signup_year   AS signup_year,
           COUNT(o.id)     AS order_count,
           SUM(o.amount)   AS total_spend
    FROM {SCHEMA}.customers c
    JOIN {SCHEMA}.orders o ON o.customer_id = c.id
    GROUP BY c.id, c.name, c.signup_year
    HAVING SUM(o.amount) >= min_spend;
END;
$$ LANGUAGE plpgsql;
"""

# Redshift SQL UDFs reference parameters POSITIONALLY ($1), not by declared
# name — a real quirk already recorded in MEMORY.md.
REDSHIFT_FUNCTION = f"""
CREATE OR REPLACE FUNCTION {SCHEMA}.f_customer_tenure(signup_year INTEGER)
RETURNS INTEGER
STABLE
AS $$
    SELECT CAST(DATE_PART(year, CURRENT_DATE) - $1 AS INTEGER)
$$ LANGUAGE sql;
"""

STARBURST_FUNCTION = """
CREATE OR REPLACE FUNCTION galaxy.functions.f_order_size(amount DOUBLE)
RETURNS VARCHAR
RETURN CASE
    WHEN amount < 50 THEN 'small'
    WHEN amount < 250 THEN 'medium'
    ELSE 'large'
END
"""


def run_redshift() -> None:
    conn = rs._connect()
    try:
        conn.autocommit = True
        cur = conn.cursor()
        for label, sql in (
            ("procedure sp_top_customers", REDSHIFT_PROCEDURE),
            ("function f_customer_tenure", REDSHIFT_FUNCTION),
        ):
            cur.execute(sql)
            print(f"[redshift] created {label}")
    finally:
        conn.close()


def run_starburst() -> None:
    conn = sb._connect()
    cur = conn.cursor()
    cur.execute(STARBURST_FUNCTION)
    cur.fetchall()
    print("[starburst] created function galaxy.functions.f_order_size")


if __name__ == "__main__":
    run_redshift()
    run_starburst()
    print("\n--- read back through the app's own connector functions ---")
    print(rs.get_procedure_ddl(SCHEMA, "sp_top_customers"))
    print()
    print(rs.get_function_ddl(SCHEMA, "f_customer_tenure"))
    print()
    print(sb.get_udf_ddl("f_order_size"))

-- Snowflake-dialect sample: customer dimension build
-- Exercises: CREATE OR REPLACE, VARIANT, IFF, NVL, DATEADD, QUALIFY, ROW_NUMBER

CREATE OR REPLACE TABLE analytics.dim_customer AS
SELECT
    c.c_custkey                                   AS customer_id,
    c.c_name                                      AS customer_name,
    NVL(c.c_address, 'UNKNOWN')                   AS address,
    IFF(c.c_acctbal < 0, 'DELINQUENT', 'ACTIVE')  AS account_status,
    c.c_acctbal                                   AS account_balance,
    n.n_name                                      AS nation,
    r.r_name                                      AS region,
    DATEADD(day, -30, CURRENT_DATE())             AS lookback_start,
    TO_VARCHAR(CURRENT_TIMESTAMP(), 'YYYY-MM-DD') AS load_date
FROM raw.customer c
LEFT JOIN raw.nation n ON c.c_nationkey = n.n_nationkey
LEFT JOIN raw.region r ON n.n_regionkey = r.r_regionkey
WHERE c.c_acctbal IS NOT NULL
QUALIFY ROW_NUMBER() OVER (PARTITION BY c.c_custkey ORDER BY c.c_acctbal DESC) = 1;

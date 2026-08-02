-- Snowflake-dialect sample: order aggregation with CTEs and window functions
-- Exercises: WITH, LISTAGG, DIV0, TRY_CAST, semi-structured access, FLATTEN

WITH monthly AS (
    SELECT
        o_custkey                          AS customer_id,
        DATE_TRUNC('MONTH', o_orderdate)   AS order_month,
        COUNT(*)                           AS order_count,
        SUM(o_totalprice)                  AS gross_revenue,
        DIV0(SUM(o_totalprice), COUNT(*))  AS avg_order_value
    FROM raw.orders
    WHERE o_orderstatus <> 'F'
    GROUP BY 1, 2
),
ranked AS (
    SELECT
        m.*,
        RANK() OVER (PARTITION BY order_month ORDER BY gross_revenue DESC) AS revenue_rank,
        LAG(gross_revenue) OVER (PARTITION BY customer_id ORDER BY order_month) AS prev_month_revenue
    FROM monthly m
)
SELECT
    customer_id,
    order_month,
    order_count,
    gross_revenue,
    avg_order_value,
    revenue_rank,
    TRY_CAST(prev_month_revenue AS DECIMAL(18,2)) AS prev_month_revenue,
    LISTAGG(DISTINCT TO_VARCHAR(order_count), ',') WITHIN GROUP (ORDER BY order_count) AS order_counts
FROM ranked
WHERE revenue_rank <= 100
GROUP BY 1, 2, 3, 4, 5, 6, 7
ORDER BY order_month DESC, revenue_rank ASC;

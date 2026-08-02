-- Snowflake-dialect sample: SCD Type 2 MERGE
-- Exercises: MERGE INTO, multi-WHEN clauses, stored-proc-ish patterns, streams

MERGE INTO analytics.dim_product AS tgt
USING (
    SELECT
        p_partkey     AS product_id,
        p_name        AS product_name,
        p_brand       AS brand,
        p_retailprice AS retail_price,
        CURRENT_TIMESTAMP() AS effective_from
    FROM raw.part
) AS src
ON tgt.product_id = src.product_id AND tgt.is_current = TRUE

WHEN MATCHED
     AND (tgt.retail_price <> src.retail_price OR tgt.brand <> src.brand)
     THEN UPDATE SET
        tgt.is_current    = FALSE,
        tgt.effective_to  = src.effective_from

WHEN NOT MATCHED
     THEN INSERT (product_id, product_name, brand, retail_price, effective_from, effective_to, is_current)
     VALUES (src.product_id, src.product_name, src.brand, src.retail_price, src.effective_from, NULL, TRUE);

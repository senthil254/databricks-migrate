-- Snowflake-dialect sample: semi-structured JSON handling
-- Exercises: VARIANT colon access, LATERAL FLATTEN, PARSE_JSON, OBJECT_CONSTRUCT
-- These are the constructs most likely to need manual review after transpilation.

CREATE OR REPLACE VIEW analytics.v_event_detail AS
SELECT
    e.event_id,
    e.payload:user.id::STRING            AS user_id,
    e.payload:user.email::STRING         AS user_email,
    e.payload:device.type::STRING        AS device_type,
    e.payload:metrics.duration_ms::NUMBER AS duration_ms,
    f.value:name::STRING                 AS tag_name,
    f.value:weight::FLOAT                AS tag_weight,
    OBJECT_CONSTRUCT(
        'event', e.event_type,
        'ts',    e.event_ts
    )                                    AS event_meta
FROM raw.events e,
     LATERAL FLATTEN(input => e.payload:tags) f
WHERE e.event_ts >= DATEADD(hour, -24, CURRENT_TIMESTAMP())
  AND IS_NULL_VALUE(e.payload:user) = FALSE;

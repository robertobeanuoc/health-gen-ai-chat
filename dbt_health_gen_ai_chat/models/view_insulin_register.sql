{{
config(
    materialized='view',
    on_schema_change='sync_all_columns'
)}}

SELECT 

    uuid,
    row_crated_at,
    "timestamp",
    timestamp_year,
    timestamp_month,
    timestamp_day,
    timestamp_hour,
    insulin_type,
    insulin_value,
    is_rapid 

FROM {{ source('abbot', 'insulin_register') }}

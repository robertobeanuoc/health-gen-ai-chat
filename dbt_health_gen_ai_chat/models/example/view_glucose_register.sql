{{
    config(
        materialized='view',
    )
}}
SELECT 

    uuid,
    row_created_at,
    row_updated_at,
    "timestamp",    
    HOUR("timestamp") AS "timehour",
    DATE("timestamp") AS "timestamp_day",
    glucose_value,
    sensor_scan


FROM  {{ source('cgm_abbot_connector', 'glucose_register') }}
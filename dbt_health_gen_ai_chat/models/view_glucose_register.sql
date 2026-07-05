{{
    config(
        materialized='view',
        on_schema_change='sync_all_columns',
        description='This view contains glucose register data.'
    )
}}
SELECT 

    uuid,
    row_created_at,
    row_updated_at,
    "timestamp" as "glucose_timestamp",    
    HOUR("timestamp") AS "glucose_timestamp_hour",
    DATE("timestamp") AS "glucose_timestamp_day",
    glucose_value,
    sensor_scan


FROM  {{ source('abbot', 'glucose_register') }}
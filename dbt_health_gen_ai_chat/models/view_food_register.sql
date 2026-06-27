{{
config(
    materialized='view',
    on_schema_change='sync_all_columns'
)}}

SELECT 

    uuid,
    file_uid,
    created_at,
    HOUR(created_at) AS "timehour",
    DATE(created_at) AS "timestamp_day",
    food_type,
    glycemic_index,
    glycemic_index * 
    weight_grams


FROM {{ source('food', 'food_register') }}
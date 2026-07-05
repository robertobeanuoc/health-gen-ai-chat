{{
config(
    materialized='view',
    on_schema_change='sync_all_columns'
)}}

SELECT 

    uuid,
    file_uid,
    HOUR(created_at) AS "timehour",
    DATE(created_at) AS "timestamp_day",
    food_type,
    glycemic_index,
    weight_grams,
    carbohydrate_percentage,
    carbohydrate_weight_grams,
    absorption_type


FROM {{ source('food', 'food_register') }}
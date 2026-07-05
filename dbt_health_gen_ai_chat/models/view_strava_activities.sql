{{
config(
    materialized='view',
    on_schema_change='sync_all_columns',    
    description='This view contains Strava activities data.',            
)
}}

SELECT 
    activity_id,
    "name",
    activity_type,
    sport_type,
    start_date,
    start_date_local,
    distance_m,
    moving_time_s,
    elapsed_time_s,
    total_elevation_gain_m


FROM  {{ source('strava', 'strava_activities') }}
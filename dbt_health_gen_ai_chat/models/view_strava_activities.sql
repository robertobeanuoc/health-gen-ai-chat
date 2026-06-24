{{
config(
    materialized='view',
    on_schema_change='sync_all_columns',    
    description='This view contains Strava activities data.',            
)
}}

SELECT 
*
FROM  {{ source('straba_to_db', 'strava_activities') }}
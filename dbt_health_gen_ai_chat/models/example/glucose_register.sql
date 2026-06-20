select *
from {{ source('cgm_abbot_connector', 'glucose_register') }}
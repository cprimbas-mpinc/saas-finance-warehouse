select
    customer_id,
    customer_name,
    segment,
    region,
    industry,
    cast(created_date as date) as created_date
from {{ source('raw', 'customers') }}

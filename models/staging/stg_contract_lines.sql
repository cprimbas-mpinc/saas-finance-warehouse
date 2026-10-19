select
    line_id,
    subscription_id,
    customer_id,
    product,
    cast(start_month as date)                    as start_month,
    cast(nullif(end_month, '') as date)          as end_month,      -- null = evergreen monthly line
    cast(mrr as decimal(18, 2))                  as mrr,
    billing_frequency
from {{ source('raw', 'contract_lines') }}

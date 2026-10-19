select
    invoice_id,
    customer_id,
    subscription_id,
    line_id,
    cast(invoice_date as date)                   as invoice_date,
    cast(service_start_month as date)            as service_start_month,
    cast(service_end_month as date)              as service_end_month,
    cast(amount as decimal(18, 2))               as amount,
    currency
from {{ source('raw', 'invoices') }}

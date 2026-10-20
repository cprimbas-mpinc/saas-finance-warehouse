-- Invoice grain with the billing month and customer attributes. Invoices whose customer is
-- missing from the master (control DQ-01) keep their amount with an 'Unmapped' segment, so
-- billings totals always tie to the subledger.
select
    i.invoice_id,
    i.customer_id,
    coalesce(c.segment, 'Unmapped')                as segment,
    coalesce(c.region, 'Unmapped')                 as region,
    coalesce(c.industry, 'Unmapped')               as industry,
    cast(date_trunc('month', i.invoice_date) as date) as billing_month,
    i.amount
from {{ ref('stg_invoices') }} i
left join {{ ref('stg_customers') }} c using (customer_id)
where date_trunc('month', i.invoice_date) between date '{{ var("window_start") }}' and date '{{ var("window_end") }}'

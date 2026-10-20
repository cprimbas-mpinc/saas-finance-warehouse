-- Invoice x month recognized revenue, limited to the reporting window. Invoices whose customer is
-- missing from the master (control DQ-01) keep their revenue under an 'Unmapped' segment, so
-- revenue totals always tie to the subledger and the GL reconciliation.
select
    r.invoice_id,
    r.customer_id,
    coalesce(c.segment, 'Unmapped')    as segment,
    coalesce(c.region, 'Unmapped')     as region,
    coalesce(c.industry, 'Unmapped')   as industry,
    r.revenue_month,
    r.recognized_amount
from {{ ref('int_invoice_revenue_schedule') }} r
left join {{ ref('stg_customers') }} c using (customer_id)
where r.revenue_month between date '{{ var("window_start") }}' and date '{{ var("window_end") }}'

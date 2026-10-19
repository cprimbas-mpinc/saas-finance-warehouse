-- Invoice x month recognized revenue, limited to the reporting window.
select
    r.invoice_id,
    r.customer_id,
    c.segment,
    r.revenue_month,
    r.recognized_amount
from {{ ref('int_invoice_revenue_schedule') }} r
left join {{ ref('stg_customers') }} c using (customer_id)
where r.revenue_month between date '{{ var("window_start") }}' and date '{{ var("window_end") }}'

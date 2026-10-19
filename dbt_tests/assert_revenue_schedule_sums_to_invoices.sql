-- Completeness: every invoice's revenue schedule sums back to the invoice amount, to the cent.
select i.invoice_id, i.amount, sum(r.recognized_amount) as scheduled
from {{ ref('stg_invoices') }} i
left join {{ ref('int_invoice_revenue_schedule') }} r using (invoice_id)
group by 1, 2
having coalesce(sum(r.recognized_amount), 0) <> i.amount

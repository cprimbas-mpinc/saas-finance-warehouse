-- BIL-02: every invoice amount equals contracted MRR x service months on its contract line.
with invoices as (
    select
        i.*,
        datediff('month', i.service_start_month, i.service_end_month) + 1 as service_months
    from {{ ref('stg_invoices') }} i
)

select
    i.invoice_id                                  as exception_key,
    i.invoice_id,
    i.customer_id,
    i.line_id,
    i.service_months,
    l.mrr                                         as contracted_mrr,
    l.mrr * i.service_months                      as expected_amount,
    i.amount                                      as invoiced_amount,
    i.amount - l.mrr * i.service_months           as variance
from invoices i
join {{ ref('stg_contract_lines') }} l using (line_id)
where i.amount <> l.mrr * i.service_months

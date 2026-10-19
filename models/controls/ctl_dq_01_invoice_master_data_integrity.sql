-- DQ-01: every invoice maps to a customer in the CRM master and a contract line in billing.
-- An invoice that maps to neither is revenue with no customer or contract behind it.
select
    i.invoice_id                                  as exception_key,
    i.invoice_id,
    i.customer_id,
    i.line_id,
    i.amount,
    c.customer_id is null                         as missing_customer,
    l.line_id is null                             as missing_contract_line
from {{ ref('stg_invoices') }} i
left join {{ ref('stg_customers') }} c using (customer_id)
left join {{ ref('stg_contract_lines') }} l on l.line_id = i.line_id
where c.customer_id is null or l.line_id is null

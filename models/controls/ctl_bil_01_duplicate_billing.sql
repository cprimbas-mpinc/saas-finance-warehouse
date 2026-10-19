-- BIL-01: no contract line is billed more than once for the same service months.
-- One exception row per later (suspected duplicate) invoice.
select
    later.invoice_id                              as exception_key,
    later.invoice_id                              as suspected_duplicate_invoice_id,
    earlier.invoice_id                            as original_invoice_id,
    later.customer_id,
    later.line_id,
    later.service_start_month,
    later.service_end_month,
    later.amount
from {{ ref('stg_invoices') }} later
join {{ ref('stg_invoices') }} earlier
  on earlier.line_id = later.line_id
 and earlier.invoice_id < later.invoice_id
 and earlier.service_start_month <= later.service_end_month   -- overlapping service periods
 and earlier.service_end_month   >= later.service_start_month
qualify row_number() over (partition by later.invoice_id order by earlier.invoice_id) = 1

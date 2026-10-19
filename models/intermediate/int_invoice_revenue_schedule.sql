-- Ratable revenue schedule: each invoice is recognized evenly across its service months.
-- Rounding residue goes to the final month so the schedule always sums back to the invoice amount.
-- Simplifying assumption (documented in docs/metric_definitions.md): monthly, not daily, proration.
with invoices as (
    select
        *,
        datediff('month', service_start_month, service_end_month) + 1 as service_months
    from {{ ref('stg_invoices') }}
),

exploded as (
    select
        i.invoice_id,
        i.customer_id,
        i.amount,
        i.service_months,
        cast(m.revenue_month as date)                                       as revenue_month,
        row_number() over (partition by i.invoice_id order by m.revenue_month) as month_seq,
        -- Cast back to decimal: dividing money in DuckDB yields a double, and money is never float.
        cast(round(i.amount / i.service_months, 2) as decimal(18, 2))       as monthly_amount
    from invoices i,
         unnest(generate_series(i.service_start_month, i.service_end_month, interval 1 month)) as m(revenue_month)
)

select
    invoice_id,
    customer_id,
    revenue_month,
    month_seq,
    service_months,
    cast(case
        when month_seq < service_months then monthly_amount
        else amount - monthly_amount * (service_months - 1)
    end as decimal(18, 2)) as recognized_amount
from exploded

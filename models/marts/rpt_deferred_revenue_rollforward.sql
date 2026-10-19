-- Subledger deferred revenue bridge: beginning + billings - recognized = ending.
with billings as (
    select date_trunc('month', invoice_date) as month_start, sum(amount) as billings
    from {{ ref('stg_invoices') }}
    group by 1
),

recognized as (
    select revenue_month as month_start, sum(recognized_amount) as recognized_revenue
    from {{ ref('int_invoice_revenue_schedule') }}
    group by 1
),

monthly as (
    select
        s.month_start,
        coalesce(b.billings, 0)            as billings,
        coalesce(r.recognized_revenue, 0)  as recognized_revenue
    from {{ ref('int_month_spine') }} s
    left join billings b using (month_start)
    left join recognized r using (month_start)
)

select
    month_start,
    coalesce(sum(billings - recognized_revenue) over prior_months, 0)  as beginning_deferred_revenue,
    billings,
    recognized_revenue,
    sum(billings - recognized_revenue) over through_month              as ending_deferred_revenue
from monthly
window
    through_month as (order by month_start rows between unbounded preceding and current row),
    prior_months  as (order by month_start rows between unbounded preceding and 1 preceding)

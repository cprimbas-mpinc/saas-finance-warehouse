-- Trailing-twelve-month retention on a customer cohort basis.
-- Cohort = customers paying 12 months before the measurement month.
--   NRR = cohort ARR today / cohort ARR a year ago            (expansion counts, new logos don't)
--   GRR = sum(least(today, a year ago)) / cohort ARR a year ago (expansion capped, so GRR <= 100%)
with pairs as (
    select
        cur.month_start,
        cur.customer_id,
        prev.mrr * 12 as arr_year_ago,
        cur.mrr  * 12 as arr_today
    from {{ ref('int_customer_mrr_monthly') }} cur
    join {{ ref('int_customer_mrr_monthly') }} prev
      on prev.customer_id = cur.customer_id
     and prev.month_start = cur.month_start - interval 12 month
    where prev.mrr > 0
)

select
    month_start,
    count(*)                                                     as cohort_customers,
    sum(arr_year_ago)                                            as cohort_arr_year_ago,
    sum(arr_today)                                               as cohort_arr_today,
    round(sum(arr_today) / sum(arr_year_ago), 4)                 as net_revenue_retention,
    round(sum(least(arr_today, arr_year_ago)) / sum(arr_year_ago), 4) as gross_revenue_retention,
    count(*) filter (where arr_today > 0)                        as cohort_customers_retained
from pairs
group by 1

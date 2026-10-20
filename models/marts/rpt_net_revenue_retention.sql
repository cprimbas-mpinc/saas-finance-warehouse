-- Trailing-twelve-month retention on a customer cohort basis.
-- Cohort = customers paying 12 months before the measurement month.
--   NRR = cohort ARR today / cohort ARR a year ago            (expansion counts, new logos don't)
--   GRR = sum(least(today, a year ago)) / cohort ARR a year ago (expansion capped, so GRR <= 100%)
select
    month_start,
    count(*)                                                       as cohort_customers,
    sum(arr_year_ago)                                              as cohort_arr_year_ago,
    sum(arr_today)                                                 as cohort_arr_today,
    round(sum(arr_today) / sum(arr_year_ago), 4)                   as net_revenue_retention,
    round(sum(arr_retained_capped) / sum(arr_year_ago), 4)         as gross_revenue_retention,
    count(*) filter (where arr_today > 0)                          as cohort_customers_retained
from {{ ref('fct_customer_retention_pairs') }}
group by 1

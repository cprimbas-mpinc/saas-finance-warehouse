-- Customer x measurement month, for customers paying 12 months earlier (the retention cohort).
-- Grain chosen so NRR/GRR can be sliced by any customer attribute and re-aggregated correctly:
-- the ratio is always computed from summed numerators and denominators, never averaged.
select
    cur.month_start,
    cur.customer_id,
    c.segment,
    c.region,
    c.industry,
    prev.mrr * 12                          as arr_year_ago,
    cur.mrr  * 12                          as arr_today,
    least(cur.mrr, prev.mrr) * 12          as arr_retained_capped
from {{ ref('int_customer_mrr_monthly') }} cur
join {{ ref('int_customer_mrr_monthly') }} prev
  on prev.customer_id = cur.customer_id
 and prev.month_start = cur.month_start - interval 12 month
left join {{ ref('stg_customers') }} c on c.customer_id = cur.customer_id
where prev.mrr > 0

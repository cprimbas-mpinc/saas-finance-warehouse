-- Contracted MRR per customer per month, densified so every month from a customer's first
-- contract through the end of the window has a row (zero when nothing is active). Dense rows are
-- what make churn and reactivation visible: a customer who disappears shows up as a drop to zero.
with active_lines as (
    select
        s.month_start,
        l.customer_id,
        sum(l.mrr) as mrr
    from {{ ref('int_month_spine') }} s
    join {{ ref('stg_contract_lines') }} l
      on l.start_month <= s.month_start
     and (l.end_month is null or l.end_month >= s.month_start)
    group by 1, 2
),

customer_first_month as (
    select customer_id, min(start_month) as first_month
    from {{ ref('stg_contract_lines') }}
    group by 1
)

select
    s.month_start,
    c.customer_id,
    coalesce(a.mrr, 0) as mrr
from customer_first_month c
join {{ ref('int_month_spine') }} s
  on s.month_start >= c.first_month
left join active_lines a
  on a.customer_id = c.customer_id
 and a.month_start = s.month_start

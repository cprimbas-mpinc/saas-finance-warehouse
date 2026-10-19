with lifecycle as (
    select
        customer_id,
        min(month_start) filter (where mrr > 0)  as first_paid_month,
        max(month_start) filter (where mrr > 0)  as last_paid_month
    from {{ ref('int_customer_mrr_monthly') }}
    group by 1
),

current_state as (
    select customer_id, mrr as current_mrr
    from {{ ref('int_customer_mrr_monthly') }}
    where month_start = date '{{ var("window_end") }}'
)

select
    c.customer_id,
    c.customer_name,
    c.segment,
    c.region,
    c.industry,
    c.created_date,
    l.first_paid_month,
    l.last_paid_month,
    coalesce(cs.current_mrr, 0)          as current_mrr,
    coalesce(cs.current_mrr, 0) * 12     as current_arr,
    coalesce(cs.current_mrr, 0) > 0      as is_active
from {{ ref('stg_customers') }} c
left join lifecycle l using (customer_id)
left join current_state cs using (customer_id)

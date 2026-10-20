-- Customer-month grain. Classifies the change in contracted MRR versus the prior month.
-- Movements are netted at the customer level: if one product expands and another contracts in the
-- same month, the customer shows a single net expansion or contraction. Customer-level netting is
-- the most common board convention; product-level movements would come from contract lines instead.
with base as (
    select
        month_start,
        customer_id,
        mrr,
        coalesce(lag(mrr) over w, 0)                                       as prior_mrr,
        coalesce(max(case when mrr > 0 then 1 else 0 end) over (
            partition by customer_id order by month_start
            rows between unbounded preceding and 1 preceding), 0) = 1      as was_previously_paying
    from {{ ref('int_customer_mrr_monthly') }}
    window w as (partition by customer_id order by month_start)
)

select
    b.month_start,
    b.customer_id,
    c.segment,
    c.region,
    c.industry,
    b.mrr,
    b.prior_mrr,
    b.mrr - b.prior_mrr as mrr_change,
    case
        when b.prior_mrr = 0 and b.mrr > 0 and not b.was_previously_paying then 'new'
        when b.prior_mrr = 0 and b.mrr > 0                                 then 'reactivation'
        when b.prior_mrr > 0 and b.mrr = 0                                 then 'churn'
        when b.mrr > b.prior_mrr                                           then 'expansion'
        when b.mrr < b.prior_mrr                                           then 'contraction'
        when b.mrr > 0                                                     then 'flat'
        else 'inactive'
    end as movement_type
from base b
left join {{ ref('stg_customers') }} c using (customer_id)

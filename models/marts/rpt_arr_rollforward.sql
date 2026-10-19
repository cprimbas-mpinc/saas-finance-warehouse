-- Monthly ARR bridge: beginning + new + expansion + reactivation + contraction + churn = ending.
-- Contraction and churn are stored as negative amounts so the bridge foots by simple addition.
-- ARR = contracted recurring MRR x 12 (excludes one-time and usage fees, which this company doesn't bill).
{% set movements = ['new', 'expansion', 'reactivation', 'contraction', 'churn'] %}
select
    month_start,
    sum(prior_mrr) * 12                                                              as beginning_arr,
    {% for m in movements -%}
    coalesce(sum(case when movement_type = '{{ m }}' then mrr_change end), 0) * 12   as {{ 'churned' if m == 'churn' else m }}_arr,
    {% endfor -%}
    sum(mrr) * 12                                                                    as ending_arr,
    count(*) filter (where mrr > 0)                                                  as paying_customers,
    count(*) filter (where movement_type = 'new')                                    as new_logos,
    count(*) filter (where movement_type = 'churn')                                  as churned_logos
from {{ ref('fct_customer_mrr_movements') }}
group by 1

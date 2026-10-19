-- GL activity by account and period, with running balances signed to each account's normal balance.
with activity as (
    select
        s.month_start                     as period_month,
        coa.account_number,
        coa.account_name,
        coa.normal_balance,
        coalesce(sum(gl.debit), 0)        as debits,
        coalesce(sum(gl.credit), 0)       as credits
    from {{ ref('int_month_spine') }} s
    cross join {{ ref('chart_of_accounts') }} coa
    left join {{ ref('stg_gl_journal_lines') }} gl
      on gl.period_month = s.month_start
     and gl.account_number = coa.account_number
    group by 1, 2, 3, 4
)

select
    *,
    case when normal_balance = 'credit' then credits - debits else debits - credits end as net_activity,
    sum(case when normal_balance = 'credit' then credits - debits else debits - credits end)
        over (partition by account_number order by period_month) as ending_balance
from activity

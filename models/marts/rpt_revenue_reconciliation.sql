-- Monthly reconciliation of revenue and deferred revenue: billing subledger vs general ledger.
-- This is the workpaper behind controls REV-01 and REV-02.
with gl as (
    select
        period_month as month_start,
        max(case when account_number = '4000' then net_activity end)   as gl_revenue,
        max(case when account_number = '2400' then ending_balance end) as gl_deferred_revenue
    from {{ ref('int_gl_account_monthly') }}
    group by 1
)

select
    d.month_start,
    d.recognized_revenue                              as subledger_revenue,
    gl.gl_revenue,
    gl.gl_revenue - d.recognized_revenue              as revenue_variance,
    d.ending_deferred_revenue                         as subledger_deferred_revenue,
    gl.gl_deferred_revenue,
    gl.gl_deferred_revenue - d.ending_deferred_revenue as deferred_revenue_variance
from {{ ref('rpt_deferred_revenue_rollforward') }} d
join gl using (month_start)

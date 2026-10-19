-- REV-02: subledger deferred revenue balance ties to GL account 2400 at each month end.
select
    month_start                                   as exception_key,
    month_start,
    subledger_deferred_revenue,
    gl_deferred_revenue,
    deferred_revenue_variance,
    {{ var('recon_threshold_usd') }}              as threshold_usd
from {{ ref('rpt_revenue_reconciliation') }}
where abs(deferred_revenue_variance) > {{ var('recon_threshold_usd') }}

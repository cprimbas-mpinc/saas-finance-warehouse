-- REV-01: recognized revenue in the billing subledger ties to GL account 4000 each month.
-- Returns one row per month whose variance exceeds the investigation threshold.
select
    month_start                                   as exception_key,
    month_start,
    subledger_revenue,
    gl_revenue,
    revenue_variance,
    {{ var('recon_threshold_usd') }}              as threshold_usd
from {{ ref('rpt_revenue_reconciliation') }}
where abs(revenue_variance) > {{ var('recon_threshold_usd') }}

-- Deferred revenue is a liability for service not yet delivered; a negative balance means revenue
-- was recognized ahead of billing, which this company's contracts don't allow.
select * from {{ ref('rpt_deferred_revenue_rollforward') }}
where ending_deferred_revenue < 0

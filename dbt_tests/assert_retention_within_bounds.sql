-- Sanity bounds: GRR can never exceed 100% and NRR outside 50-200% signals a broken definition.
select * from {{ ref('rpt_net_revenue_retention') }}
where gross_revenue_retention > 1
   or net_revenue_retention not between 0.5 and 2.0

-- ARR-01: the ARR bridge foots (beginning + movements = ending) and each month's beginning
-- balance equals the prior month's ending balance. A metrics-integrity control: if the bridge
-- doesn't foot, the board deck is wrong no matter how clean the source data is.
with checks as (
    select
        month_start,
        beginning_arr,
        ending_arr,
        lag(ending_arr) over (order by month_start) as prior_ending_arr,
        beginning_arr
          + coalesce(new_arr, 0) + coalesce(expansion_arr, 0) + coalesce(reactivation_arr, 0)
          + coalesce(contraction_arr, 0) + coalesce(churned_arr, 0) - ending_arr as bridge_difference
    from {{ ref('rpt_arr_rollforward') }}
)

select
    month_start                                   as exception_key,
    *
from checks
where bridge_difference <> 0
   or (prior_ending_arr is not null and prior_ending_arr <> beginning_arr)

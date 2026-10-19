-- One row per reporting month (first-of-month convention used throughout the warehouse).
select cast(month_start as date) as month_start
from generate_series(
    date '{{ var("window_start") }}',
    date '{{ var("window_end") }}',
    interval 1 month
) as t(month_start)

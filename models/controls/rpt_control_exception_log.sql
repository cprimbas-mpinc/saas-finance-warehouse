-- Exception log: every exception the controls found, joined to the workflow record that tracks it
-- to resolution (seeds/control_exception_workflow.csv stands in for a ticketing system).
--   unassigned = found by a control, nobody has picked it up yet (needs triage)
--   open / investigating / resolved = owner-maintained workflow status
--   cleared = a logged exception the controls no longer find (fixed at the source)
with current_exceptions as (
    {% for control_id, model_name in control_registry() %}
    select '{{ control_id }}' as control_id, cast(exception_key as varchar) as exception_key
    from {{ ref(model_name) }}
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
),

workflow as (
    select * from {{ ref('control_exception_workflow') }}
)

select
    coalesce(c.control_id, w.control_id)                                   as control_id,
    coalesce(c.exception_key, w.exception_key)                             as exception_key,
    case
        when c.exception_key is null then 'cleared'
        when w.exception_key is null then 'unassigned'
        else w.status
    end                                                                    as status,
    c.exception_key is not null                                            as found_in_latest_run,
    w.owner,
    w.root_cause,
    w.action,
    w.identified_date,
    w.due_date,
    w.resolved_date,
    datediff('day', w.identified_date, w.resolved_date)                    as days_to_resolve,
    case when w.resolved_date is null and w.identified_date is not null
         then datediff('day', w.identified_date, date '{{ var("as_of_date") }}') end as days_open,
    coalesce(w.resolved_date is null and w.due_date < date '{{ var("as_of_date") }}', false) as is_overdue
from current_exceptions c
full outer join workflow w
  on w.control_id = c.control_id
 and w.exception_key = c.exception_key

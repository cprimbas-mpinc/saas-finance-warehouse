-- One row per control with its exception count for this run.
{% for control_id, model_name in control_registry() %}
select
    '{{ control_id }}'                            as control_id,
    '{{ model_name }}'                            as control_model,
    count(*)                                      as exception_count,
    case when count(*) = 0 then 'PASS' else 'EXCEPTION' end as result
from {{ ref(model_name) }}
{% if not loop.last %}union all{% endif %}
{% endfor %}

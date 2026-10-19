-- One row per control with its exception count for this run.
{% set controls = [
    ('REV-01', 'ctl_rev_01_revenue_reconciliation'),
    ('REV-02', 'ctl_rev_02_deferred_revenue_reconciliation'),
    ('BIL-01', 'ctl_bil_01_duplicate_billing'),
    ('BIL-02', 'ctl_bil_02_invoice_contract_variance'),
    ('DQ-01',  'ctl_dq_01_invoice_master_data_integrity'),
    ('GL-01',  'ctl_gl_01_unbalanced_journal_entries'),
    ('GL-02',  'ctl_gl_02_manual_je_segregation_of_duties'),
    ('ARR-01', 'ctl_arr_01_rollforward_integrity'),
] %}
{% for control_id, model_name in controls %}
select
    '{{ control_id }}'                            as control_id,
    '{{ model_name }}'                            as control_model,
    count(*)                                      as exception_count,
    case when count(*) = 0 then 'PASS' else 'EXCEPTION' end as result
from {{ ref(model_name) }}
{% if not loop.last %}union all{% endif %}
{% endfor %}

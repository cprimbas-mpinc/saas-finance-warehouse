-- GL-02: every manual journal entry is approved by someone other than its preparer.
select
    je_id                                         as exception_key,
    je_id,
    min(period_month)                             as period_month,
    min(description)                              as description,
    min(prepared_by)                              as prepared_by,
    min(approved_by)                              as approved_by,
    sum(debit)                                    as entry_amount,
    case when min(approved_by) is null then 'not approved' else 'self-approved' end as issue
from {{ ref('stg_gl_journal_lines') }}
where je_source = 'manual'
group by je_id
having min(approved_by) is null or min(approved_by) = min(prepared_by)

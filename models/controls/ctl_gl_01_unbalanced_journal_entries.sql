-- GL-01: every journal entry balances (total debits = total credits).
select
    je_id                                         as exception_key,
    je_id,
    min(period_month)                             as period_month,
    min(je_source)                                as je_source,
    min(prepared_by)                              as prepared_by,
    sum(debit)                                    as total_debits,
    sum(credit)                                   as total_credits,
    sum(debit) - sum(credit)                      as out_of_balance
from {{ ref('stg_gl_journal_lines') }}
group by je_id
having sum(debit) <> sum(credit)

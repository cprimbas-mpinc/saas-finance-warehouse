select
    je_id,
    cast(line_number as integer)                 as line_number,
    cast(period as date)                         as period_month,
    cast(posting_date as date)                   as posting_date,
    account_number,
    cast(debit as decimal(18, 2))                as debit,
    cast(credit as decimal(18, 2))               as credit,
    source                                       as je_source,
    description,
    prepared_by,
    nullif(approved_by, '')                      as approved_by
from {{ source('raw', 'gl_journal_lines') }}

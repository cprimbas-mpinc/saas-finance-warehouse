# Control Evidence Package

**Company:** Halyard Software, Inc. (synthetic) · **Run:** 2026-10-20 01:41 UTC · **Data mode:** seeded (seed 42)

Each control below is an automated query over the full population (not a sample). A control model returns only exception rows, so an empty result is the evidence of operating effectiveness for the run.

## Summary

| Control | Name | Frequency | Owner | Exceptions | Result |
|---|---|---|---|---|---|
| REV-01 | Revenue subledger-to-GL reconciliation | Monthly (close) | Revenue Accounting Manager | 1 | **EXCEPTION** |
| REV-02 | Deferred revenue subledger-to-GL reconciliation | Monthly (close) | Revenue Accounting Manager | 0 | **PASS** |
| BIL-01 | Duplicate billing detection | Each billing run | Billing Operations Lead | 1 | **EXCEPTION** |
| BIL-02 | Invoice-to-contract price accuracy | Each billing run | Billing Operations Lead | 1 | **EXCEPTION** |
| DQ-01 | Invoice master-data integrity | Daily | Financial Data Engineering | 1 | **EXCEPTION** |
| GL-01 | Journal entries balance | Daily | General Ledger Manager | 1 | **EXCEPTION** |
| GL-02 | Manual journal entry segregation of duties | Monthly (close) | Controller | 1 | **EXCEPTION** |
| ARR-01 | ARR roll-forward integrity | Monthly (metrics close) | Head of Financial Data & Analytics | 0 | **PASS** |

## Data tested

Source files are fingerprinted so a reviewer can confirm the evidence came from this exact data.

| File | Rows | SHA-256 (first 16) |
|---|---|---|
| contract_lines.csv | 580 | c97f02501832f6ae |
| customers.csv | 333 | c0a0104a8c2269a6 |
| gl_journal_lines.csv | 316 | b1b1cecd33555e3e |
| invoices.csv | 2175 | 4f4664df75517f49 |

## Control detail

### REV-01 · Revenue subledger-to-GL reconciliation
- **Risk:** Revenue in the financial statements doesn't match what the billing system supports (e.g., unsupported top-side entries).
- **Control objective:** Recognized revenue per the billing subledger ties to GL account 4000 each month within the investigation threshold.
- **Assertion:** Occurrence, Accuracy · **Type:** Detective, Automated · **Frequency:** Monthly (close)
- **Population tested:** model `ctl_rev_01_revenue_reconciliation` over the full reporting window
- **Result:** EXCEPTION (1 exception)

| month_start | subledger_revenue | gl_revenue | revenue_variance | threshold_usd |
|---|---|---|---|---|
| 2025-06-01 | 828700.00 | 853700.00 | 25000.00 | 500 |

Full detail: `exceptions/REV-01.csv`. Follow-up: owner to investigate, document root cause, and correct or support each item before close sign-off.

### REV-02 · Deferred revenue subledger-to-GL reconciliation
- **Risk:** The deferred revenue liability is misstated, so revenue is pulled forward or pushed out.
- **Control objective:** Subledger deferred revenue balance ties to GL account 2400 at every month end within the threshold.
- **Assertion:** Completeness, Cut-off · **Type:** Detective, Automated · **Frequency:** Monthly (close)
- **Population tested:** model `ctl_rev_02_deferred_revenue_reconciliation` over the full reporting window
- **Result:** PASS (0 exceptions)

### BIL-01 · Duplicate billing detection
- **Risk:** A contract term is invoiced twice, overstating billings, AR and revenue.
- **Control objective:** No contract line is billed more than once for overlapping service months.
- **Assertion:** Occurrence · **Type:** Detective, Automated · **Frequency:** Each billing run
- **Population tested:** model `ctl_bil_01_duplicate_billing` over the full reporting window
- **Result:** EXCEPTION (1 exception)

| suspected_duplicate_invoice_id | original_invoice_id | customer_id | line_id | service_start_month | service_end_month | amount |
|---|---|---|---|---|---|---|
| INV-001227 | INV-001152 | C-0021 | LN-000065 | 2025-04-01 | 2026-03-01 | 76800.00 |

Full detail: `exceptions/BIL-01.csv`. Follow-up: owner to investigate, document root cause, and correct or support each item before close sign-off.

### BIL-02 · Invoice-to-contract price accuracy
- **Risk:** Customers are billed at prices that differ from the signed contract.
- **Control objective:** Every invoice equals contracted MRR x service months for its contract line.
- **Assertion:** Accuracy · **Type:** Detective, Automated · **Frequency:** Each billing run
- **Population tested:** model `ctl_bil_02_invoice_contract_variance` over the full reporting window
- **Result:** EXCEPTION (1 exception)

| invoice_id | customer_id | line_id | service_months | contracted_mrr | expected_amount | invoiced_amount | variance |
|---|---|---|---|---|---|---|---|
| INV-000972 | C-0006 | LN-000017 | 12 | 10500.00 | 126000.00 | 128400.00 | 2400.00 |

Full detail: `exceptions/BIL-02.csv`. Follow-up: owner to investigate, document root cause, and correct or support each item before close sign-off.

### DQ-01 · Invoice master-data integrity
- **Risk:** Revenue is recorded with no valid customer or contract behind it.
- **Control objective:** Every invoice references a customer in the CRM master and a contract line in billing.
- **Assertion:** Existence, Completeness · **Type:** Detective, Automated · **Frequency:** Daily
- **Population tested:** model `ctl_dq_01_invoice_master_data_integrity` over the full reporting window
- **Result:** EXCEPTION (1 exception)

| invoice_id | customer_id | line_id | amount | missing_customer | missing_contract_line |
|---|---|---|---|---|---|
| INV-001519 | C-9001 | LN-900001 | 1500.00 | True | True |

Full detail: `exceptions/DQ-01.csv`. Follow-up: owner to investigate, document root cause, and correct or support each item before close sign-off.

### GL-01 · Journal entries balance
- **Risk:** An out-of-balance entry misstates the ledger (e.g., transposition errors on manual entries).
- **Control objective:** Total debits equal total credits for every journal entry.
- **Assertion:** Accuracy · **Type:** Detective, Automated · **Frequency:** Daily
- **Population tested:** model `ctl_gl_01_unbalanced_journal_entries` over the full reporting window
- **Result:** EXCEPTION (1 exception)

| je_id | period_month | je_source | prepared_by | total_debits | total_credits | out_of_balance |
|---|---|---|---|---|---|---|
| JE-2025-03-006 | 2025-03-01 | manual | j.alvarez | 12400.00 | 12040.00 | 360.00 |

Full detail: `exceptions/GL-01.csv`. Follow-up: owner to investigate, document root cause, and correct or support each item before close sign-off.

### GL-02 · Manual journal entry segregation of duties
- **Risk:** One person can both create and approve a manual entry, so errors or fraud go unreviewed.
- **Control objective:** Every manual journal entry has an approver who is not its preparer.
- **Assertion:** Occurrence, Authorization · **Type:** Detective, Automated · **Frequency:** Monthly (close)
- **Population tested:** model `ctl_gl_02_manual_je_segregation_of_duties` over the full reporting window
- **Result:** EXCEPTION (1 exception)

| je_id | period_month | description | prepared_by | approved_by | entry_amount | issue |
|---|---|---|---|---|---|---|
| JE-2025-09-006 | 2025-09-01 | Software subscription accrual | d.kim | d.kim | 8750.00 | self-approved |

Full detail: `exceptions/GL-02.csv`. Follow-up: owner to investigate, document root cause, and correct or support each item before close sign-off.

### ARR-01 · ARR roll-forward integrity
- **Risk:** The ARR bridge reported to leadership and the board doesn't foot or doesn't carry forward between months.
- **Control objective:** Beginning ARR + movements = ending ARR, and each month's beginning equals the prior month's ending.
- **Assertion:** Accuracy (management reporting) · **Type:** Detective, Automated · **Frequency:** Monthly (metrics close)
- **Population tested:** model `ctl_arr_01_rollforward_integrity` over the full reporting window
- **Result:** PASS (0 exceptions)

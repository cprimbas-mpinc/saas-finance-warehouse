# Metric Definitions

These are the definitions the warehouse implements. On a real team this page is the contract between Finance, the data team and leadership. If a number in a deck doesn't match this page, the deck is wrong or this page needs a reviewed change.

| Metric | Definition | Model | Notes and judgment calls |
|---|---|---|---|
| **MRR** | Sum of contracted monthly recurring price across a customer's active contract lines in the month | `int_customer_mrr_monthly` | Contracted, not billed: an annual customer contributes MRR every month, not 12x in the invoice month. |
| **ARR** | MRR × 12 | `rpt_arr_rollforward` | Recurring only. One-time and usage fees would be excluded (this company bills neither). |
| **New ARR** | ARR from customers with no prior paid month | `fct_customer_mrr_movements` | Counted in the first paid month. |
| **Expansion / Contraction** | Month-over-month change in ARR for customers paying in both months | same | **Netted at the customer level.** If one product expands and another contracts in the same month, the customer shows one net movement. |
| **Churn** | Prior-month ARR of customers who drop to zero | same | Recorded as a negative amount so the bridge foots by addition. |
| **Reactivation** | ARR from a customer who paid before, went to zero, and came back | same | Kept separate from New so new-logo growth isn't inflated by win-backs. |
| **NRR** (net revenue retention) | Current ARR of the cohort paying 12 months ago ÷ that cohort's ARR 12 months ago | `rpt_net_revenue_retention` | Trailing-12 cohort method. Includes expansion; excludes new logos. |
| **GRR** (gross revenue retention) | Σ min(current ARR, ARR 12 months ago) ÷ cohort ARR 12 months ago | same | Expansion capped per customer, so GRR ≤ 100% by construction. |
| **Recognized revenue** | Invoice amount spread evenly across its service months | `int_invoice_revenue_schedule` | **Monthly proration** (simplification; a production system would prorate daily for mid-month starts). The rounding residue lands in the last month, so every schedule sums to its invoice to the cent. |
| **Billings** | Invoice amounts by invoice-date month | `rpt_deferred_revenue_rollforward` | |
| **Deferred revenue** | Cumulative billings − cumulative recognized revenue | same | Ties to GL 2400 (control REV-02). |

## Why ARR and revenue differ

ARR is a forward-looking run rate built from contracts. Revenue is a GAAP number recognized from invoices as service is delivered. They are reconciled by design, not expected to match. The usual gaps are timing (a contract signed on the 28th adds full ARR but almost no revenue that month), billing errors (an invoice that doesn't match the contract, caught by BIL-02), and entries made outside the subledger (caught by REV-01).

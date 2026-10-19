"""Generate synthetic source-system data for Halyard Software, Inc. (a fictional B2B SaaS company).

Writes four raw extracts, the way they would land from each source system:

    customers.csv            CRM customer master
    contract_lines.csv       Billing system contract lines (one row per price period of a subscription)
    invoices.csv             Billing system invoices
    gl_journal_lines.csv     ERP general ledger journal lines

By default it also plants a known set of control exceptions (duplicate invoice, unsupported manual
revenue entry, etc.) and writes them to seeded_exceptions.json. The controls in the warehouse are
tested against that manifest: every planted exception must be caught, and nothing else.

Run with --clean to generate the same company with no planted exceptions.
Output is deterministic for a given --seed.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

WINDOW_START = date(2023, 1, 1)
WINDOW_END = date(2025, 12, 1)  # last reporting month (first-of-month convention)


# ---------------------------------------------------------------------------- date helpers

def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def month_index(d: date) -> int:
    return (d.year - WINDOW_START.year) * 12 + d.month - WINDOW_START.month


def months_between_inclusive(start: date, end: date) -> int:
    return month_index(end) - month_index(start) + 1


def month_end(d: date) -> date:
    return add_months(d, 1) - timedelta(days=1)


ALL_MONTHS = [add_months(WINDOW_START, i) for i in range(months_between_inclusive(WINDOW_START, WINDOW_END))]


# ---------------------------------------------------------------------------- reference data

SEGMENTS = {
    # segment: (MRR range, rounding, share annual billing, annual churn at renewal, monthly churn)
    "SMB": ((400, 1_500), 50, 0.40, 0.15, 0.025),
    "Mid-Market": ((2_000, 6_000), 100, 0.70, 0.10, 0.015),
    "Enterprise": ((8_000, 25_000), 500, 1.00, 0.06, 0.0),
}
REGIONS = ["North America", "North America", "North America", "EMEA", "APAC"]
INDUSTRIES = ["Logistics", "Healthcare", "Retail", "Manufacturing", "Financial Services", "Media", "Education"]
NAME_A = ["Blue", "Granite", "North", "Silver", "Harbor", "Summit", "Cedar", "Iron", "Bright", "Prairie",
          "Copper", "Lake", "Atlas", "Keystone", "Pioneer", "Redwood", "Beacon", "Falcon", "Ridge", "Meridian"]
NAME_B = ["water", "line", "field", "stone", "point", "gate", "works", "path", "bridge", "view"]
NAME_C = ["Logistics", "Health", "Supply", "Foods", "Partners", "Systems", "Labs", "Group", "Holdings", "Co."]


@dataclass
class ContractLine:
    line_id: str
    subscription_id: str
    customer_id: str
    product: str
    start_month: date
    end_month: date | None  # inclusive; None = evergreen monthly line still active
    mrr: int
    billing_frequency: str  # annual | monthly


@dataclass
class Generator:
    rng: random.Random
    customers: list[dict] = field(default_factory=list)
    lines: list[ContractLine] = field(default_factory=list)
    invoices: list[dict] = field(default_factory=list)
    gl_lines: list[dict] = field(default_factory=list)
    _sub_seq: int = 0
    _line_seq: int = 0
    _inv_seq: int = 0
    _je_seq: dict = field(default_factory=dict)
    _names: set = field(default_factory=set)

    # ------------------------------------------------------------------ ids
    def next_sub(self) -> str:
        self._sub_seq += 1
        return f"SUB-{self._sub_seq:05d}"

    def next_line(self) -> str:
        self._line_seq += 1
        return f"LN-{self._line_seq:06d}"

    def next_invoice(self) -> str:
        self._inv_seq += 1
        return f"INV-{self._inv_seq:06d}"

    def next_je(self, period: date) -> str:
        key = period.strftime("%Y-%m")
        self._je_seq[key] = self._je_seq.get(key, 0) + 1
        return f"JE-{key}-{self._je_seq[key]:03d}"

    def company_name(self) -> str:
        while True:
            name = f"{self.rng.choice(NAME_A)}{self.rng.choice(NAME_B)} {self.rng.choice(NAME_C)}"
            if name not in self._names:
                self._names.add(name)
                return name

    def price(self, segment: str) -> int:
        (lo, hi), step, *_ = SEGMENTS[segment]
        return int(round(self.rng.uniform(lo, hi) / step) * step)

    # ------------------------------------------------------------------ customers + contracts
    def build_customers_and_contracts(self) -> None:
        cust_n = 0
        for i, month in enumerate(ALL_MONTHS):
            new_logos = int(4 + i * 0.25 + self.rng.random() * 3)
            for _ in range(new_logos):
                cust_n += 1
                segment = self.rng.choices(["SMB", "Mid-Market", "Enterprise"], weights=[55, 33, 12])[0]
                cid = f"C-{cust_n:04d}"
                self.customers.append({
                    "customer_id": cid,
                    "customer_name": self.company_name(),
                    "segment": segment,
                    "region": self.rng.choice(REGIONS),
                    "industry": self.rng.choice(INDUSTRIES),
                    "created_date": (month - timedelta(days=self.rng.randint(5, 40))).isoformat(),
                })
                annual = self.rng.random() < SEGMENTS[segment][2]
                core_end = self.simulate_line(cid, segment, "Core Platform", month, self.price(segment), annual)
                # Add-on product for some mid-market and enterprise customers.
                if segment != "SMB" and self.rng.random() < 0.30:
                    add_start = add_months(month, self.rng.randint(3, 15))
                    if add_start <= WINDOW_END and (core_end is None or add_start <= core_end):
                        add_mrr = int(round(self.price(segment) * 0.2 / 50) * 50)
                        self.simulate_line(cid, segment, "Analytics Add-on", add_start, add_mrr, annual,
                                           hard_stop=core_end)

    def simulate_line(self, cid: str, segment: str, product: str, start: date, mrr: int, annual: bool,
                      hard_stop: date | None = None) -> date | None:
        """Simulate one subscription's life. Returns its final service month (None if still active)."""
        _, step, _, renewal_churn, monthly_churn = SEGMENTS[segment]
        sub_id = self.next_sub()
        freq = "annual" if annual else "monthly"

        def stop(end_month: date) -> date:
            return min(end_month, hard_stop) if hard_stop else end_month

        if annual:
            term_start = start
            while term_start <= WINDOW_END:
                term_end = stop(add_months(term_start, 11))
                self.lines.append(ContractLine(self.next_line(), sub_id, cid, product, term_start, term_end, mrr, freq))
                if hard_stop and term_end >= hard_stop:
                    return term_end
                # Renewal decision for the next term.
                roll = self.rng.random()
                if roll < renewal_churn:
                    self.maybe_reactivate(cid, segment, product, add_months(term_end, 1), mrr, annual)
                    return term_end
                if roll < renewal_churn + 0.30:
                    mrr = int(round(mrr * self.rng.uniform(1.10, 1.40) / step) * step)
                elif roll < renewal_churn + 0.40:
                    mrr = max(step, int(round(mrr * self.rng.uniform(0.70, 0.90) / step) * step))
                term_start = add_months(term_end, 1)
            return None

        # Monthly: price changes create a new line on the same subscription.
        line_start = start
        month = start
        while True:
            nxt = add_months(month, 1)
            if nxt > WINDOW_END:
                self.lines.append(ContractLine(self.next_line(), sub_id, cid, product, line_start, None, mrr, freq))
                return None
            if hard_stop and month >= hard_stop:  # add-on ends with the core subscription
                self.lines.append(ContractLine(self.next_line(), sub_id, cid, product, line_start, month, mrr, freq))
                return month
            roll = self.rng.random()
            if roll < monthly_churn:
                self.lines.append(ContractLine(self.next_line(), sub_id, cid, product, line_start, month, mrr, freq))
                self.maybe_reactivate(cid, segment, product, nxt, mrr, annual)
                return month
            if roll < monthly_churn + 0.03 or roll > 0.99:
                factor = self.rng.uniform(1.10, 1.50) if roll < 0.99 else self.rng.uniform(0.70, 0.90)
                self.lines.append(ContractLine(self.next_line(), sub_id, cid, product, line_start, month, mrr, freq))
                mrr = max(step, int(round(mrr * factor / step) * step))
                line_start = nxt
            month = nxt

    def maybe_reactivate(self, cid: str, segment: str, product: str, earliest: date, mrr: int, annual: bool) -> None:
        if product != "Core Platform" or segment == "Enterprise" or self.rng.random() > 0.15:
            return
        restart = add_months(earliest, self.rng.randint(3, 9))
        if restart <= WINDOW_END:
            self.simulate_line(cid, segment, product, restart, mrr, annual)

    # ------------------------------------------------------------------ billing
    def build_invoices(self) -> None:
        for ln in self.lines:
            if ln.billing_frequency == "annual":
                if ln.start_month <= WINDOW_END:
                    self.add_invoice(ln.customer_id, ln.subscription_id, ln.line_id, ln.start_month, ln.end_month,
                                     ln.mrr * months_between_inclusive(ln.start_month, ln.end_month))
            else:
                last = min(ln.end_month or WINDOW_END, WINDOW_END)
                m = ln.start_month
                while m <= last:
                    self.add_invoice(ln.customer_id, ln.subscription_id, ln.line_id, m, m, ln.mrr)
                    m = add_months(m, 1)
        self.invoices.sort(key=lambda r: (r["invoice_date"], r["invoice_id"]))

    def add_invoice(self, cid, sub_id, line_id, svc_start, svc_end, amount, invoice_date=None, invoice_id=None) -> dict:
        inv = {
            "invoice_id": invoice_id or self.next_invoice(),
            "customer_id": cid,
            "subscription_id": sub_id,
            "line_id": line_id,
            "invoice_date": (invoice_date or svc_start + timedelta(days=self.rng.randint(0, 4))).isoformat(),
            "service_start_month": svc_start.isoformat(),
            "service_end_month": svc_end.isoformat(),
            "amount": f"{amount:.2f}",
            "currency": "USD",
        }
        self.invoices.append(inv)
        return inv

    def renumber_invoices(self) -> dict[str, str]:
        """Billing systems number invoices in issue order; reassign ids that way and return old -> new."""
        self.invoices.sort(key=lambda r: (r["invoice_date"], r["invoice_id"]))
        mapping = {}
        for n, inv in enumerate(self.invoices, start=1):
            mapping[inv["invoice_id"]] = f"INV-{n:06d}"
            inv["invoice_id"] = mapping[inv["invoice_id"]]
        return mapping

    # ------------------------------------------------------------------ revenue engine (mirrors the dbt logic)
    def revenue_by_month(self) -> tuple[dict, dict]:
        billings, recognized = {}, {}
        for inv in self.invoices:
            amt = round(float(inv["amount"]), 2)
            bill_month = date.fromisoformat(inv["invoice_date"]).replace(day=1)
            billings[bill_month] = billings.get(bill_month, 0) + amt
            s, e = date.fromisoformat(inv["service_start_month"]), date.fromisoformat(inv["service_end_month"])
            n = months_between_inclusive(s, e)
            per = round(amt / n, 2)
            for k in range(n):
                m = add_months(s, k)
                piece = per if k < n - 1 else round(amt - per * (n - 1), 2)
                recognized[m] = recognized.get(m, 0) + piece
        return billings, recognized

    # ------------------------------------------------------------------ general ledger
    def je(self, period: date, posting: date, source: str, desc: str, entries: list[tuple[str, float, float]],
           prepared_by: str = "system", approved_by: str | None = "system") -> str:
        je_id = self.next_je(period)
        for n, (acct, dr, cr) in enumerate(entries, start=1):
            self.gl_lines.append({
                "je_id": je_id, "line_number": n, "period": period.isoformat(), "posting_date": posting.isoformat(),
                "account_number": acct, "debit": f"{dr:.2f}", "credit": f"{cr:.2f}", "source": source,
                "description": desc, "prepared_by": prepared_by, "approved_by": approved_by or "",
            })
        return je_id

    def build_gl(self) -> None:
        billings, recognized = self.revenue_by_month()
        prior_billings = 0.0
        for m in ALL_MONTHS:
            eom = month_end(m)
            b, r = round(billings.get(m, 0), 2), round(recognized.get(m, 0), 2)
            self.je(m, eom, "billing_system", "Monthly billings", [("1200", b, 0), ("2400", 0, b)])
            self.je(m, eom, "revenue_engine", "Ratable revenue recognition", [("2400", r, 0), ("4000", 0, r)])
            if prior_billings:
                self.je(m, eom, "cash_application", "Customer receipts", [("1000", prior_billings, 0), ("1200", 0, prior_billings)])
            hosting = round(r * self.rng.uniform(0.16, 0.20), 2)
            self.je(m, eom, "ap_subledger", "Cloud hosting invoices", [("6000", hosting, 0), ("2000", 0, hosting)])
            if m.month in (3, 6, 9, 12):  # routine quarter-end manual accrual, properly approved
                accrual = float(self.rng.randint(30, 90) * 100)
                self.je(m, eom - timedelta(days=1), "manual", "Quarter-end software accrual",
                        [("6100", accrual, 0), ("2000", 0, accrual)], prepared_by="j.alvarez", approved_by="m.chen")
            prior_billings = b


# ---------------------------------------------------------------------------- planted exceptions

def plant_billing_exceptions(g: Generator) -> list[dict]:
    """Billing-side exceptions. Planted before the GL is built, so they flow through to the ledger
    the way a real billing error would."""
    planted = []
    annual = [i for i in g.invoices if i["line_id"] and i["service_start_month"] != i["service_end_month"]]

    # BIL-01: the same contract term billed twice (re-run of an invoice batch).
    src = next(i for i in annual if i["service_start_month"] == "2025-04-01")
    dup = g.add_invoice(src["customer_id"], src["subscription_id"], src["line_id"],
                        date.fromisoformat(src["service_start_month"]), date.fromisoformat(src["service_end_month"]),
                        float(src["amount"]), invoice_date=date.fromisoformat(src["invoice_date"]) + timedelta(days=3))
    planted.append({"control_id": "BIL-01", "key": dup["invoice_id"], "note": f"duplicate of {src['invoice_id']}"})

    # BIL-02: invoice billed at a price that is not in the contract (+$200/month uplift, 12 months).
    target = next(i for i in annual if i["service_start_month"] == "2025-02-01"
                  and months_between_inclusive(date.fromisoformat(i["service_start_month"]),
                                               date.fromisoformat(i["service_end_month"])) == 12)
    target["amount"] = f"{float(target['amount']) + 2_400:.2f}"
    planted.append({"control_id": "BIL-02", "key": target["invoice_id"], "note": "billed $2,400 above contract"})

    # DQ-01: invoice for a customer and contract that do not exist in the masters.
    orphan = g.add_invoice("C-9001", "SUB-90001", "LN-900001", date(2025, 7, 1), date(2025, 7, 1), 1_500)
    planted.append({"control_id": "DQ-01", "key": orphan["invoice_id"], "note": "customer and contract missing from masters"})

    g.invoices.sort(key=lambda r: (r["invoice_date"], r["invoice_id"]))
    return planted


def plant_gl_exceptions(g: Generator) -> list[dict]:
    planted = []
    # REV-01: an approved but unsupported top-side revenue entry. Approval alone doesn't make it valid;
    # only the subledger-to-GL reconciliation catches it.
    je = g.je(date(2025, 6, 1), date(2025, 6, 30), "manual", "Q2 revenue true-up per sales leadership",
              [("1200", 25_000, 0), ("4000", 0, 25_000)], prepared_by="r.patel", approved_by="m.chen")
    planted.append({"control_id": "REV-01", "key": "2025-06-01", "note": f"unsupported manual revenue entry {je}"})

    # GL-01: transposition error leaves a manual entry out of balance (12,400 vs 12,040).
    je = g.je(date(2025, 3, 1), date(2025, 3, 28), "manual", "Consulting accrual",
              [("6100", 12_400, 0), ("2000", 0, 12_040)], prepared_by="j.alvarez", approved_by="m.chen")
    planted.append({"control_id": "GL-01", "key": je, "note": "debits exceed credits by 360.00"})

    # GL-02: a manual entry approved by the same person who prepared it.
    je = g.je(date(2025, 9, 1), date(2025, 9, 25), "manual", "Software subscription accrual",
              [("6100", 8_750, 0), ("2000", 0, 8_750)], prepared_by="d.kim", approved_by="d.kim")
    planted.append({"control_id": "GL-02", "key": je, "note": "preparer approved own entry"})
    return planted


# ---------------------------------------------------------------------------- output

def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data/raw", help="output directory for raw extracts")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--clean", action="store_true", help="generate data with no planted exceptions")
    args = ap.parse_args()

    g = Generator(rng=random.Random(args.seed))
    g.build_customers_and_contracts()
    g.build_invoices()
    planted = [] if args.clean else plant_billing_exceptions(g)
    mapping = g.renumber_invoices()
    for p in planted:
        p["key"] = mapping.get(p["key"], p["key"])
        p["note"] = re.sub(r"INV-\d{6}", lambda m: mapping.get(m.group(0), m.group(0)), p["note"])
    g.build_gl()
    if not args.clean:
        planted += plant_gl_exceptions(g)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "customers.csv", g.customers)
    write_csv(out / "contract_lines.csv", [{
        "line_id": l.line_id, "subscription_id": l.subscription_id, "customer_id": l.customer_id,
        "product": l.product, "start_month": l.start_month.isoformat(),
        "end_month": l.end_month.isoformat() if l.end_month else "", "mrr": f"{l.mrr:.2f}",
        "billing_frequency": l.billing_frequency,
    } for l in g.lines])
    write_csv(out / "invoices.csv", g.invoices)
    write_csv(out / "gl_journal_lines.csv", g.gl_lines)
    (out / "seeded_exceptions.json").write_text(json.dumps(
        {"mode": "clean" if args.clean else "seeded", "seed": args.seed, "exceptions": planted}, indent=2))

    print(f"Generated {len(g.customers)} customers, {len(g.lines)} contract lines, {len(g.invoices)} invoices, "
          f"{len(g.gl_lines)} GL lines -> {out} ({'clean' if args.clean else f'{len(planted)} planted exceptions'})")


if __name__ == "__main__":
    main()

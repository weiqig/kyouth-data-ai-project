# Demo Dataset

Use these files to test the main end-to-end workflows:

## Finance
- `finance/finance_invoice_complete.txt` — should map well to Finance: Invoice.
- `finance/finance_invoice_incomplete_needs_review.txt` — intentionally missing required invoice fields; should remain `needs_review`.
- `finance/finance_invoice_invalid_values.txt` — contains invalid date/currency values for validation testing.
- `finance/finance_bank_statement.csv` — structured CSV example for Finance: Bank Statement.

## Construction
- `construction/construction_purchase_order.txt` — construction purchase order template example.
- `construction/construction_progress_claim.txt` — construction progress claim template example.

## Auto discovery
- `auto_discovery/generic_meeting_note.md` — generic document for auto-discovery testing.

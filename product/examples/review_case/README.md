# Human review example

All four orders, IDs and supplier names are synthetic test fixtures, not financial evidence.
No payments are made. Both original CSV files remain unchanged during review.

Use **Data assistant** with the explicit review prompt below, or **Folder batches**, for revision-bound human review. The assistant routes this request to the existing financial Runtime.
Set Input folder to `pending_files` and BI system folder to `bi_system`.

| Order | Input | BI reference | Expected result |
| --- | --- | --- | --- |
| REVIEW-001 | Amount 100.00; pending; supplier present | Identical | Automatically archive |
| REVIEW-002 | Amount 125.00 | Amount 100.00 | Review amount difference 25.00 |
| REVIEW-003 | Payment status paid | Payment status pending | Review payment status |
| REVIEW-004 | Supplier name blank | Example Supplier D | Review missing required value |

Prompt:
`Reconcile the orders in the Input folder against the BI system folder, automatically archive matching records, pause on discrepancies or missing required fields for human review, and generate an Excel report without automatically applying corrections.`

In Data assistant, select both folders, enter the prompt and choose Start task. The conversation shows an Open review button. In Folder batches, choose Prepare task then Run task, or Scan folders then Run ready tables.
Expected initial state: 4 input rows, 1 completed row/archive receipt, 3 held rows and one review task.

Open review. The missing supplier name is detected first. Review the proposed reference value, save the
correction and resume validation. The amount and payment-status differences then appear.
Approve corrections only after checking the displayed values. Revalidation after those decisions can finish
all four rows. No review decisions are pre-seeded or automatically approved.

Identical scans reuse previous task evidence. Once this exact example has been fully reviewed in a workspace,
repeating it can reuse completed receipts instead of asking again. To repeat the initial review scenario,
copy the files and give the same new order IDs to both copies; preserve all intended differences.

# Finance Flow · Delivery V1 RC1

This source candidate packages Finance Flow 1.0 for a Windows reviewer. The product retains individual reconciliation, folder batches, the local Data assistant, human review, exports and the local archive. Start in the [root README](../README.md#start-on-windows). The [product guide](../product/README.md) covers a separate demonstration workspace and browser/service launch options.

## Four-order demonstration

Use a fresh workspace. The supplied records are synthetic. Open the two CSV files side by side and keep the originals unchanged. Both have four orders keyed by supplier ID and order ID. [Source orders](../product/examples/review_case/pending_files/orders_for_review.csv) · [BI reference](../product/examples/review_case/bi_system/bi_reference.csv) · [Sample origin](../product/examples/review_case/README.md)

### 1. Establish a clean comparison

1. Under **Files & references**, import `bi_reference.csv` twice, once as source orders and once as BI reference. Using the same fixture in both roles gives a known matching control. Check the seven mapped columns and four rows.
2. Create an individual reconciliation with those two imports. Give it a title such as **Demo – matching orders** and an instruction to compare the four orders. Clear **Use local AI to prepare the execution plan**.
3. Choose **Generate plan**, inspect the proposed steps and click **Approve plan & run**. Expect a completed task with four rows, four local receipts and no review decisions.
4. Download the reconciled CSV and full JSON report. The four order IDs and amounts should match the reference. Open the local archive and locate the receipts for this task.

### 2. Hold a discrepancy for a reviewer

1. Import `orders_for_review.csv` as a new source. Create a second task with this source and the same BI reference. Keep local AI planning off. Generate the plan, inspect it and approve the run.
2. Open **Review findings**. Compare each held row with the reference below before choosing **Review correction** and the reference value. Use **Save corrections & revalidate**. Additional differences may become visible once required fields are valid.

   | Order | Source | BI reference | Expected reviewer action |
   | --- | --- | --- | --- |
   | REVIEW-001 | 100.00, pending | Same | Leave unchanged. |
   | REVIEW-002 | 125.00 | 100.00 | Inspect the 25.00 difference and confirm 100.00. |
   | REVIEW-003 | paid | pending | Confirm the reference payment status. |
   | REVIEW-004 | Blank supplier name | Example Supplier D | Confirm the missing name. |

3. When no findings remain, choose **Resume & revalidate**. Download the reconciled CSV and final JSON report. The working output should contain four matching orders, including 100.00 for REVIEW-002. The original source CSV still contains 125.00. The report contains the signed-in review decisions.
4. In the local archive, distinguish the two tasks by task ID. With both tasks completed in this fresh workspace, expect eight receipts in total. Stop the application normally and reopen the **same data directory**. Sign in again, open both tasks and compare the receipt IDs and reports without rerunning either task.

For the folder-batch variant, select only `product/examples/review_case/pending_files` and `product/examples/review_case/bi_system`. The [batch walkthrough](../product/examples/review_case/README.md) explains why clean rows can complete before a held task is reviewed. For a larger example, the repository also includes UCI Online Retail-derived files. Their attribution, licence, transformations and deliberately introduced differences are documented separately. [Benchmark provenance](../product/examples/PROVENANCE.json)

## Verification and boundaries

The R4B checkpoint reran all five Python and 19 JavaScript waiting/retry tests. Earlier Windows regression evidence covers 758 pytest cases, 16 RPA unittest cases and the three Node suites (51, 58 and 61 cases respectively). Those earlier suites overlap. The earlier independent full Python rerun remained incomplete.

On Windows with Python 3.12.10 and an existing environment, the extracted source started from a new folder containing spaces. The homepage and four static assets matched the archive bytes. Both four-order tasks completed. A signed-in synthetic reviewer confirmed three corrections across two revisions, including 125.00 to 100.00 on REVIEW-002. Both CSV exports matched all four reference rows. Two normal launcher shutdowns completed; reopening the same separate workspace preserved all eight receipt IDs, the decisions and the exported CSVs. No live model was called. The reviewer actions were automated. Installation on a clean machine, native WebView interaction, live-model cold start, enterprise connections, multi-machine operation and real user acceptance remain open.

BI values come from files chosen by the operator. OA receipts stay in the local reconciliation archive. Access control is intended for one local owner. An application login does not encrypt the workspace or backups. Keep data directories and backups outside the source package.

## Source, contributors and release state

The project builds on the ENT207 team's AI-RPA finance platform, its Agent Runtime and financial tools. The assistant navigation work from **leng327** is attributed to PR #3 at source commit `29392fa72b103f4cc6d82436a5d6617a6c85a1d3`. Yusong Yang directed the technical integration and makes adoption decisions. Codex assisted implementation, packaging and local testing. ChatGPT assisted planning and independent review.

The source archive combines checkpoint `43c4a055c5f7356ca257f061e3f3059eaec4aad1` with the pending delivery documentation. Its `DELIVERY_MANIFEST.json` lists the included bytes and exclusions. It excludes two historical Assistant workbooks whose individual provenance is unconfirmed. Their entries remain in the repository and Git history. Runtime workspaces, local environments, model weights and private review materials are outside the source archive.

After independent review, the delivery documentation can be considered for a separate local commit. A later GitHub submission requires publication authorization and a fresh check of main and the overlap with PR #3. Delivery V1 RC1 is a source candidate; a remote release, course submission and production acceptance remain separate decisions.

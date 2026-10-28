"""Explicit reconciliation/review requests use the existing financial Runtime."""
from pathlib import Path
import re

from product.input_folders import input_files
from product.storage import digest


def review_requested(instruction):
    reconcile = re.search(r"\breconcil\w*\b|对账|核对订单", instruction, re.I)
    human = re.search(r"\b(?:human|manual)\s+(?:review|approval|confirmation)\b|人工(?:复核|审核|确认|\s*review)", instruction, re.I)
    archive = re.search(r"\b(?:automatically\s+archive|archive\s+(?:matching|matched|clean|validated))\b|自动归档|(?:正常|匹配).*?归档", instruction, re.I)
    if not (reconcile and human and archive): return False
    before = instruction[max(0, archive.start() - 18):archive.start()]
    return not re.search(r"(?:do not|don't|never|不要|无需|不允许)\s*$", before, re.I)


def review_summary(view):
    return {key: view[key] for key in ("id", "code", "status", "input_rows", "matched_rows", "unresolved_rows",
            "archive_receipts", "review_tasks", "report_available", "attention", "busy", "error")}


def review_message(view):
    if view["status"] == "completed":
        return f"Reconciliation complete: {view['matched_rows']} of {view['input_rows']} input rows are reconciled. Original files are unchanged."
    if view["status"] == "cancelled":
        return "Reconciliation was stopped at a tool boundary. Open the batch to inspect retained records. No review decisions were applied automatically."
    if view["status"] == "failed":
        return "Reconciliation stopped. Existing evidence is retained; inspect the batch details before retrying."
    return (f"{view['matched_rows']} of {view['input_rows']} input rows completed automatically; "
            f"{view['unresolved_rows']} rows remain unresolved. Open review for discrepancies, or Open batch for table setup. "
            "No corrections or review decisions were applied automatically.")


def run_review(assistant, chat_id, turn_id, state, turn):
    service = assistant.service; chat = assistant.chat(chat_id)
    turn["workflow"] = "reconciliation_review"
    if not chat["bi_folder"]:
        turn["message"] = "Start a new conversation and select both Input folder and BI system folder for reconciliation with human review."
        return "needs_input"
    roots = {"input": Path(chat["folder"]), "bi": Path(chat["bi_folder"])}
    expected = {(file.get("group", "input"), file["name"]): file["sha256"] for file in assistant.catalog(chat_id)}
    current = {(group, path.relative_to(root).as_posix()) for group, root in roots.items() for path in input_files(root, service.store.root)}
    if current != set(expected):
        raise ValueError("The folder contents changed after this conversation was captured. Start a new conversation to use the current files.")
    for (group, name), sha in expected.items():
        if digest(roots[group] / name) != sha:
            raise ValueError("An input or BI file changed after capture. Start a new conversation before reconciling current files.")
    def attached(batch_id):
        turn["batch_id"] = batch_id
        turn["message"] = "Running local reconciliation; clean rows are archived and differences wait for human review."
        assistant.persist(chat_id, turn_id, state, turn, "running")
    view = service.batches.run_for_assistant(chat["folder"], chat["bi_folder"], chat["actor"], turn_id,
        expected=expected, attached=attached, existing_id=turn.get("batch_id"))
    turn["batch_id"] = view["id"]
    turn["steps"].append({"tool": "reconcile_review", "arguments": {"batch_id": view["id"]},
                          "status": "error" if view["status"] == "failed" else "success", "result": review_summary(view)})
    turn["message"] = review_message(view)
    if view["status"] == "failed": turn["error"] = view["error"]
    return view["status"] if view["status"] in ("completed", "needs_review", "cancelled", "failed") else "needs_review"

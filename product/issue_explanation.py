"""Read-only, evidence-bound advice. Model text is never rendered or executed."""
import copy
from decimal import Decimal, InvalidOperation, localcontext
import json

from backend.app.tools.rules import PAYMENT_STATUSES, RECORD_STATUSES, REQUIRED_FIELDS, parse_amount

MAX_PROPOSAL_BYTES = 4096
MODEL_NAME = "qwen3.5:4b"
UNCERTAINTY = "ROOT_CAUSE_UNKNOWN"
SUGGESTIONS = {
    "REVIEW_BOTH_SOURCES": "Verify the source and imported reference independently before deciding what to correct.",
    "KEEP_PENDING_REVIEW": "Keep this finding pending until a person verifies the evidence.",
    "VERIFY_REFERENCE_VALUE": "If independently verified, a person may select the reference value using the existing review control.",
    "ENTER_VERIFIED_VALUE": "If independently verified, a person may enter a correction using the existing review control.",
    "FIX_SOURCE_AND_REIMPORT": "Verify and correct the source outside this advice, then import a new version.",
}
FINDINGS = {
    "amount_mismatch": ("SOURCE_REFERENCE_DISAGREE", "The source and imported reference amounts differ."),
    "payment_status_mismatch": ("SOURCE_REFERENCE_DISAGREE", "The source and imported reference payment statuses differ."),
    "record_status_mismatch": ("SOURCE_REFERENCE_DISAGREE", "The source and imported reference record statuses differ."),
    "record_not_found": ("NO_REFERENCE_MATCH", "No matching record was found in the imported BI reference. This finding does not establish a BI technical failure."),
    "ambiguous_reference": ("MULTIPLE_REFERENCE_MATCHES", "Multiple imported BI records match; a unique reference value is unavailable."),
    "missing_value": ("SOURCE_VALUE_MISSING", "A required source value is missing. Its replacement is not established by this finding."),
    "invalid_amount": ("SOURCE_AMOUNT_INVALID", "The source amount does not satisfy the existing amount rules. No replacement amount is inferred."),
    "invalid_date": ("SOURCE_DATE_INVALID", "The source date does not satisfy the existing date rules. No replacement date is inferred."),
    "duplicate_business_key": ("DUPLICATE_SOURCE_KEY", "The source contains a repeated business key. This does not establish duplicate payment."),
}
STATUSES = {
    "advice_ready": "The local model selected validated advice from the supplied evidence and options.",
    "model_unavailable": "Local model advice is unavailable; deterministic rule information is shown.",
    "model_timeout": "The local model did not return advice within the request budget. Showing deterministic rule information.",
    "model_busy": "The local model is busy. Showing deterministic rule information. You can request advice again later.",
    "model_rejected": "The model response failed validation; deterministic rule information is shown.",
    "model_error": "Local model advice failed; deterministic rule information is shown.",
    "unsupported": "This finding has no supported model context; deterministic rule information is shown.",
    "insufficient_evidence": "Verified values are insufficient for model advice; deterministic rule information is shown.",
}


class AdviceFailure(RuntimeError):
    def __init__(self, status):
        self.status = status if status in STATUSES and status.startswith("model_") else "model_error"
        super().__init__(self.status)


def strict_json(raw, limit=MAX_PROPOSAL_BYTES):
    if not isinstance(raw, str) or len(raw) > limit or len(raw.encode("utf-8")) > limit:
        raise ValueError("Invalid JSON size/type")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(_value):
        raise ValueError("Nonfinite JSON value")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def money(value):
    # This bound limits display/model input only, never financial validation.
    if not isinstance(value, (str, int, float, Decimal)) or isinstance(value, bool) or len(str(value)) > 128:
        raise ValueError("No bounded exact amount")
    value = parse_amount(value)
    with localcontext() as context:
        context.prec = max(40, len(value.as_tuple().digits) + 4)
        return format(value, ".2f")


def build_facts(issue):
    kind = issue.get("type")
    field = issue.get("field") if issue.get("field") in REQUIRED_FIELDS else None
    supported = kind in FINDINGS and type(issue.get("row")) is int and issue["row"] >= 2
    code, text = FINDINGS[kind] if supported else ("INSUFFICIENT_CONTEXT", "This finding requires source verification; there is insufficient supported context for model advice.")
    facts = [{"id": "F_FINDING", "source": "rule", "label": "Deterministic finding", "value": kind if supported else "unsupported"}]
    suggestions = ["KEEP_PENDING_REVIEW", "FIX_SOURCE_AND_REIMPORT"]
    status = None if supported else "unsupported"
    if supported and kind.endswith("_mismatch"):
        suggestions.insert(0, "REVIEW_BOTH_SOURCES")
    if supported and issue.get("can_correct") is True and field in {"supplier_name", "amount", "date", "payment_status", "record_status"} and issue.get("reference_value") is not None:
        suggestions.extend(["VERIFY_REFERENCE_VALUE", "ENTER_VERIFIED_VALUE"])
    if supported and kind == "amount_mismatch":
        try:
            if field != "amount":
                raise ValueError("Wrong amount field")
            source, reference = money(issue.get("original_value")), money(issue.get("reference_value"))
            with localcontext() as context:
                context.prec = max(len(source), len(reference), 40) + 4
                difference = Decimal(source) - Decimal(reference)
                if difference == 0:
                    raise ValueError("No amount mismatch")
                delta = format(difference, ".2f")
            for identifier, role, label, value in (
                ("F_AMOUNT_SOURCE", "input", "Source amount", source),
                ("F_AMOUNT_BI", "reference", "Imported BI amount", reference),
                ("F_AMOUNT_DIFF", "rule", "Source minus reference", delta)):
                facts.append({"id": identifier, "source": role, "label": label, "value": value})
            text = f"The source amount is {source}; the imported BI reference amount is {reference}. The source-minus-reference difference is {delta}. Neither source is assumed correct."
        except (ValueError, InvalidOperation, OverflowError):
            status = "insufficient_evidence"
            suggestions = ["KEEP_PENDING_REVIEW", "FIX_SOURCE_AND_REIMPORT"]
            text = "The stored finding reports an amount difference, but bounded exact values are unavailable for this explanation. Verify the source and reference."
    elif supported and kind in ("payment_status_mismatch", "record_status_mismatch"):
        allowed = PAYMENT_STATUSES if kind == "payment_status_mismatch" else RECORD_STATUSES
        for identifier, role, label, value in (
            ("F_STATUS_SOURCE", "input", "Source status", issue.get("original_value")),
            ("F_STATUS_BI", "reference", "Imported BI status", issue.get("reference_value"))):
            if isinstance(value, str) and value in allowed:
                facts.append({"id": identifier, "source": role, "label": label, "value": value})
    return {"summary_code": code, "issue_type": kind if supported else "unsupported", "field": field,
        "facts": facts, "suggestion_ids": suggestions, "explanation": text + " The underlying cause is not established by this evidence.",
        "fallback_status": status}


def proposal_schema(context):
    def selection(values):
        return {"type": "array", "minItems": 1, "maxItems": len(values), "uniqueItems": True,
                "items": {"type": "string", "enum": values}}
    return {"type": "object", "additionalProperties": False,
        "required": ["summary_code", "fact_ids", "suggestion_ids", "uncertainty"], "properties": {
            "summary_code": {"type": "string", "enum": [context["summary_code"]]},
            "fact_ids": selection([fact["id"] for fact in context["facts"]]),
            "suggestion_ids": selection(context["suggestion_ids"]),
            "uncertainty": {"type": "string", "enum": [UNCERTAINTY]}}}


def validate_proposal(raw, context):
    proposal = strict_json(raw)
    if not isinstance(proposal, dict) or set(proposal) != {"summary_code", "fact_ids", "suggestion_ids", "uncertainty"}:
        raise ValueError("Unknown/missing proposal fields")
    if proposal["summary_code"] != context["summary_code"] or proposal["uncertainty"] != UNCERTAINTY:
        raise ValueError("Unsupported summary/claim")
    for key, allowed in (("fact_ids", [fact["id"] for fact in context["facts"]]), ("suggestion_ids", context["suggestion_ids"])):
        values = proposal[key]
        if (not isinstance(values, list) or not 1 <= len(values) <= len(allowed) or
                any(not isinstance(v, str) or v not in allowed for v in values) or len(values) != len(set(values))):
            raise ValueError("Unsupported fact or recommendation")
    return proposal


def advise(issue, provider):
    bundle = build_facts(issue)
    # No raw cells, identifiers, paths, messages or authentication material.
    context = {key: copy.deepcopy(bundle[key]) for key in ("summary_code", "issue_type", "field", "facts", "suggestion_ids")}
    status = bundle["fallback_status"]
    proposal = None
    if status is None:
        try:
            method = getattr(provider, "explain_issue", None)
            if method is None:
                raise AdviceFailure("model_unavailable")
            raw = method(copy.deepcopy(context), proposal_schema(context))
            proposal = validate_proposal(raw, context)
            status = "advice_ready"
        except AdviceFailure as exc:
            status = exc.status
        except (ValueError, TypeError, KeyError, RecursionError, UnicodeError):
            status = "model_rejected"
        except Exception:
            status = "model_error"
    selected = proposal["suggestion_ids"] if proposal else bundle["suggestion_ids"]
    return {"mode": "local_model" if proposal else "rules_only", "status": status,
        "status_message": STATUSES[status], "model": MODEL_NAME if proposal else None, "advisory_only": True,
        "facts": bundle["facts"], "explanation": bundle["explanation"],
        "selected_fact_ids": proposal["fact_ids"] if proposal else [fact["id"] for fact in bundle["facts"]],
        "uncertainty": UNCERTAINTY,
        "suggestions": [{"id": value, "text": SUGGESTIONS[value], "requires_human_decision": True} for value in selected]}

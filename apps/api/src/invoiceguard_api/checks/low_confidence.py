"""Fields the LLM was not sure about (ADR-010): low confidence forces a human look (ADR-002).

Below the threshold, a field is listed in a warning. The payee IBAN and the totals are what
money moves on, so a low confidence on any of them fails the check and blocks the invoice: it is
never `ready` on a value the model was unsure about. XML invoices have no confidences and get no
result from this check.
"""

from invoiceguard_api.checks.model import CheckContext, CheckResult
from invoiceguard_api.models import CheckStatus

CHECK_TYPE = "low_confidence"
# BT-84 payee IBAN; BT-109, BT-110, BT-112, BT-115 net, VAT, gross total and amount due.
CRITICAL_TERMS = frozenset({"BT-84", "BT-109", "BT-110", "BT-112", "BT-115"})


def check(context: CheckContext) -> list[CheckResult]:
    if not context.confidences:
        return []
    threshold = context.confidence_threshold
    low = [field for field in context.confidences if field.confidence < threshold]
    evidence = {
        "threshold": str(threshold),
        "fields": [
            {
                "name": field.name,
                "code": field.code,
                "confidence": str(field.confidence),
                "evidence": field.evidence,
            }
            for field in low
        ],
    }
    if not low:
        return [
            CheckResult(
                CHECK_TYPE,
                CheckStatus.PASSED,
                f"All extracted fields have a confidence of at least {threshold}.",
                evidence,
            )
        ]
    names = ", ".join(field.name for field in low)
    critical = [field.name for field in low if field.code in CRITICAL_TERMS]
    if critical:
        return [
            CheckResult(
                CHECK_TYPE,
                CheckStatus.FAILED,
                f"Low confidence on the payee IBAN or a total ({', '.join(critical)}); "
                f"check against the PDF. All low-confidence fields: {names}.",
                evidence,
            )
        ]
    return [
        CheckResult(
            CHECK_TYPE,
            CheckStatus.WARNING,
            f"Low confidence below {threshold}; check against the PDF: {names}.",
            evidence,
        )
    ]

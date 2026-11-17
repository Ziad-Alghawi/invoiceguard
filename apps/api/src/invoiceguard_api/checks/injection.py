"""Prompt injection (R2-4): the document text tries to instruct an AI or hides text.

The scan itself runs where the file is read (injection.py); this check turns its result into a
check result. A hit fails the check and blocks the invoice: the other checks still decide on
the parsed values as usual, and a reviewer sees the evidence. The processing step also writes a
security event for it.
"""

from dataclasses import asdict

from invoiceguard_api.checks.model import CheckContext, CheckResult
from invoiceguard_api.models import CheckStatus

CHECK_TYPE = "prompt_injection"


def check(context: CheckContext) -> CheckResult:
    scan = context.injection
    if scan is None or not scan.sources:
        return CheckResult(
            CHECK_TYPE,
            CheckStatus.SKIPPED,
            "No document text to scan (for example a scanned PDF without a text layer).",
        )
    evidence = {
        "sources": list(scan.sources),
        "characters": scan.characters,
        "findings": [asdict(finding) for finding in scan.findings],
    }
    if not scan.findings:
        return CheckResult(
            CHECK_TYPE,
            CheckStatus.PASSED,
            "No instructions to an AI and no hidden characters in the document text.",
            evidence,
        )
    rules = ", ".join(sorted({finding.rule for finding in scan.findings}))
    return CheckResult(
        CHECK_TYPE,
        CheckStatus.FAILED,
        f"The document text looks like a prompt injection ({rules}): treat the invoice as "
        "suspicious and check it against the sender.",
        evidence,
    )

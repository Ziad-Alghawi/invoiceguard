"""KoSIT validator: the HTTP client (I/O) and the check on its result (pure). See ADR-009.

The validator runs in its own container in daemon mode: POST the invoice XML to `/`, and it
answers with an XML report and status 200 (acceptable) or 406 (not acceptable). Anything else,
including a timeout or a refused connection, means "no result": the check is then skipped and
processing goes on, because the other checks do not depend on it.
"""

import logging
import urllib.error
import urllib.request
from http import HTTPStatus
from typing import Literal

from invoiceguard_api.checks.model import (
    CheckContext,
    CheckResult,
    Validation,
    ValidationMessage,
)
from invoiceguard_api.models import CheckStatus
from invoiceguard_api.parsing import ParseError
from invoiceguard_api.parsing.safe_xml import parse_xml
from invoiceguard_api.parsing.values import ValueReader

logger = logging.getLogger(__name__)

CHECK_TYPE = "kosit"
_read = ValueReader(
    {
        "rep": "http://www.xoev.de/de/validator/varl/1",
        "s": "http://www.xoev.de/de/validator/framework/1/scenarios",
    }
)
# A broken invoice can produce hundreds of messages; the reviewer needs the first few.
MAX_MESSAGES = 20
NOTEWORTHY = {"warning", "error"}
NOT_CONFIGURED = "The KoSIT validator is not configured (INVOICEGUARD_VALIDATOR_URL)."


class KositValidator:
    def __init__(self, url: str | None, timeout_seconds: float) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds

    def validate(self, xml: bytes) -> Validation:
        if self.url is None:
            return Validation(outcome="unavailable", reason=NOT_CONFIGURED)
        request = urllib.request.Request(
            self.url, data=xml, method="POST", headers={"Content-Type": "application/xml"}
        )
        try:
            # The URL comes from our settings (an http(s) URL), never from the invoice.
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return read_report(response.read())
        except urllib.error.HTTPError as error:
            if error.code == HTTPStatus.NOT_ACCEPTABLE:
                return read_report(error.read())
            reason = f"The KoSIT validator answered HTTP {error.code}."
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            reason = f"The KoSIT validator is not reachable: {error}"
        except ParseError as error:
            reason = f"The KoSIT validator report cannot be read: {error}"
        logger.warning("KoSIT validation skipped: %s", reason)
        return Validation(outcome="unavailable", reason=reason)


def read_report(content: bytes) -> Validation:
    """Read the parts of a KoSIT report the check needs; raises ParseError if it is not XML."""
    root = parse_xml(content)
    messages = tuple(
        ValidationMessage(
            level=node.get("level", ""), code=node.get("code", ""), text=(node.text or "").strip()
        )
        for node in _read.nodes(root, "//rep:message")
    )
    outcome: Literal["accepted", "rejected", "no_scenario"]
    if _read.nodes(root, "rep:assessment/rep:accept"):
        outcome = "accepted"
    elif _read.nodes(root, "rep:noScenarioMatched"):
        outcome = "no_scenario"
    else:
        outcome = "rejected"
    scenario = _read.text(root, "rep:scenarioMatched/s:scenario/s:name")
    return Validation(outcome=outcome, scenario=scenario, messages=messages)


def check(context: CheckContext) -> CheckResult:
    validation = context.validation
    shown = validation.messages[:MAX_MESSAGES]
    evidence = {
        "outcome": validation.outcome,
        "scenario": validation.scenario,
        "message_count": len(validation.messages),
        "messages": [
            {"level": message.level, "code": message.code, "text": message.text}
            for message in shown
        ],
    }
    if validation.outcome == "unavailable":
        reason = validation.reason or NOT_CONFIGURED
        return CheckResult(CHECK_TYPE, CheckStatus.SKIPPED, reason, {"reason": reason})
    if validation.outcome == "no_scenario":
        return CheckResult(
            CHECK_TYPE,
            CheckStatus.WARNING,
            "Not validated: the KoSIT XRechnung configuration has no scenario for this profile.",
            evidence,
        )
    errors = [message.code for message in validation.messages if message.level == "error"]
    if validation.outcome == "rejected":
        codes = ", ".join(dict.fromkeys(errors)) or "see the report"
        return CheckResult(
            CHECK_TYPE,
            CheckStatus.FAILED,
            f"The KoSIT validator rejected the invoice ({codes}).",
            evidence,
        )
    # Accepted documents can still carry rule warnings; "information" messages are not shown.
    warnings = [message for message in validation.messages if message.level in NOTEWORTHY]
    if warnings:
        return CheckResult(
            CHECK_TYPE,
            CheckStatus.WARNING,
            f"Valid ({validation.scenario}), with {len(warnings)} warning(s).",
            evidence,
        )
    return CheckResult(CHECK_TYPE, CheckStatus.PASSED, f"Valid ({validation.scenario}).", evidence)

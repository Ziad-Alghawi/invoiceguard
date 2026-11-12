"""The KoSIT validator client against a local stub server that replays recorded reports, and
(marked `kosit`) against the real validator service when INVOICEGUARD_TEST_VALIDATOR_URL is set."""

import os
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from invoiceguard_api.checks import KositValidator
from invoiceguard_api.checks.kosit import NOT_CONFIGURED

REPORTS = Path(__file__).resolve().parent / "fixtures" / "kosit"
VALIDATOR_URL_ENV = "INVOICEGUARD_TEST_VALIDATOR_URL"


@dataclass
class Reply:
    status: int = 200
    body: bytes = b""
    delay_seconds: float = 0.0
    received: list[tuple[str, str | None, bytes]] = field(default_factory=list)


@pytest.fixture
def stub() -> Iterator[tuple[str, Reply]]:
    """A validator stand-in on a free local port; set `reply` to choose its answer."""
    reply = Reply()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            reply.received.append((self.path, self.headers["Content-Type"], body))
            time.sleep(reply.delay_seconds)
            self.send_response(reply.status)
            self.send_header("Content-Type", "application/xml")
            self.send_header("Content-Length", str(len(reply.body)))
            self.end_headers()
            self.wfile.write(reply.body)

        def log_message(self, format: str, *args: object) -> None:
            """Keep the test output quiet."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/", reply
    server.shutdown()
    server.server_close()


def _report(name: str) -> bytes:
    return (REPORTS / name).read_bytes()


def test_posts_the_xml_and_reads_an_accepted_report(
    stub: tuple[str, Reply], samples: dict[str, bytes]
) -> None:
    url, reply = stub
    reply.body = _report("accepted.xml")

    validation = KositValidator(url, 2).validate(samples["ubl_xrechnung"])

    assert reply.received == [("/", "application/xml", samples["ubl_xrechnung"])]
    assert validation.outcome == "accepted"
    assert validation.scenario == "EN16931 XRechnung (UBL Invoice)"
    assert validation.messages == ()


def test_406_with_rule_errors_is_rejected(stub: tuple[str, Reply]) -> None:
    url, reply = stub
    reply.status, reply.body = 406, _report("rejected.xml")

    validation = KositValidator(url, 2).validate(b"<Invoice/>")

    assert validation.outcome == "rejected"
    assert [(m.level, m.code) for m in validation.messages] == [
        ("error", "BR-CO-15"),
        ("error", "BR-CO-16"),
    ]
    assert validation.messages[0].text.startswith("[BR-CO-15]-Invoice total amount with VAT")


def test_406_without_scenario_is_no_scenario(stub: tuple[str, Reply]) -> None:
    url, reply = stub
    reply.status, reply.body = 406, _report("no_scenario.xml")

    validation = KositValidator(url, 2).validate(b"<Invoice/>")

    assert (validation.outcome, validation.scenario) == ("no_scenario", None)


@pytest.mark.parametrize(
    ("status", "body", "reason"),
    [
        (500, b"", "answered HTTP 500"),
        (422, b"<report/>", "answered HTTP 422"),
        (200, b"not xml", "report cannot be read"),
    ],
)
def test_unexpected_answers_mean_no_result(
    stub: tuple[str, Reply], status: int, body: bytes, reason: str
) -> None:
    url, reply = stub
    reply.status, reply.body = status, body

    validation = KositValidator(url, 2).validate(b"<Invoice/>")

    assert validation.outcome == "unavailable"
    assert reason in (validation.reason or "")


def test_timeout_means_no_result(stub: tuple[str, Reply]) -> None:
    url, reply = stub
    reply.body, reply.delay_seconds = _report("accepted.xml"), 1.0

    started = time.monotonic()
    validation = KositValidator(url, 0.2).validate(b"<Invoice/>")

    assert time.monotonic() - started < 1.0
    assert validation.outcome == "unavailable"
    assert "not reachable" in (validation.reason or "")


def test_refused_connection_means_no_result() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    # Nothing listens on the port any more.
    validation = KositValidator(f"http://127.0.0.1:{port}/", 2).validate(b"<Invoice/>")

    assert validation.outcome == "unavailable"
    assert "not reachable" in (validation.reason or "")


def test_without_url_validation_is_not_configured() -> None:
    validation = KositValidator(None, 2).validate(b"<Invoice/>")

    assert (validation.outcome, validation.reason) == ("unavailable", NOT_CONFIGURED)


# --- Against the real validator service (CI: the Compose service) ----------------------------


@pytest.fixture
def live_validator() -> KositValidator:
    url = os.environ.get(VALIDATOR_URL_ENV)
    if not url:
        pytest.skip(f"{VALIDATOR_URL_ENV} is not set (run the Compose validator service)")
    return KositValidator(url, 60)


@pytest.mark.kosit
@pytest.mark.parametrize(
    ("sample", "outcome"),
    [
        ("ubl_xrechnung", "accepted"),
        ("cii_xrechnung", "accepted"),
        ("ubl_fraud_iban", "accepted"),
        ("zugferd2_basic", "no_scenario"),
    ],
)
def test_real_validator(
    live_validator: KositValidator, samples: dict[str, bytes], sample: str, outcome: str
) -> None:
    assert live_validator.validate(samples[sample]).outcome == outcome


@pytest.mark.kosit
def test_real_validator_rejects_wrong_totals(
    live_validator: KositValidator, samples: dict[str, bytes]
) -> None:
    xml = samples["ubl_xrechnung"].replace(
        b'<cbc:TaxInclusiveAmount currencyID="EUR">5137.23',
        b'<cbc:TaxInclusiveAmount currencyID="EUR">5137.99',
    )

    validation = live_validator.validate(xml)

    assert validation.outcome == "rejected"
    assert "BR-CO-15" in {message.code for message in validation.messages}

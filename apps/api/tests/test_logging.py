import json
import logging
import sys

import pytest

from invoiceguard_api.logging import JsonFormatter, configure_logging


def test_log_line_is_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")

    logging.getLogger("invoiceguard.test").info("hello %s", "world")

    line = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["level"] == "INFO"
    assert record["logger"] == "invoiceguard.test"
    assert record["message"] == "hello world"
    assert "timestamp" in record


def test_exception_is_included() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            "invoiceguard.test", logging.ERROR, __file__, 1, "failed", None, None
        )
        record.exc_info = sys.exc_info()

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "failed"
    assert "ValueError: boom" in payload["exception"]

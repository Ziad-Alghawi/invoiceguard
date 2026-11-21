"""The model comparison (R4-6): every model sees the same invoices, one spend cap covers all of
them, a replay writes the same Markdown, and `--check` fails when the committed file differs."""

import hashlib
from decimal import Decimal
from pathlib import Path

import pytest

from invoiceguard_evals import cli, model_comparison
from invoiceguard_evals.datasets import ExtractionCase, demo_cases, generated_cases
from invoiceguard_evals.model_comparison import compare, prices, render
from invoiceguard_evals.recording import RecordingClient
from invoiceguard_evals.sources import Manifest

from .fakes import RoutingModel

THRESHOLD = Decimal("0.9")
MODELS = ["gemini/a", "gemini/b", "gemini/c"]


def _cases() -> list[ExtractionCase]:
    return [*demo_cases()[:2], *generated_cases("small")[:1]]


def _model(cases: list[ExtractionCase], wrong: str | None = None) -> RoutingModel:
    """A perfect model; with `wrong`, it gets that case's invoice number wrong."""
    truths = {}
    for case in cases:
        truth = case.truth
        if case.case_id == wrong:
            truth = truth.model_copy(update={"invoice_number": "X-1"})
        truths[hashlib.sha256(case.pdf).hexdigest()] = truth
    return RoutingModel(truths, "unused")


def test_every_model_sees_every_invoice_and_the_table_shows_them(tmp_path: Path) -> None:
    cases = _cases()
    wrong = cases[0].case_id
    client = RecordingClient(tmp_path, _model(cases, wrong), Decimal(1))

    results = compare(cases, client, MODELS, "low", THRESHOLD)
    markdown = render(results, client.recorded_on, "low", THRESHOLD)

    assert [(r.model, len(r.runs), r.stopped) for r in results] == [
        (model, 3, None) for model in MODELS
    ]
    assert "| `gemini/a` | unknown |" in markdown
    # 53 of 54 document terms; 1 of 3 invoices has a wrong key term.
    assert "3 of 3 | 0 | 98.1 % | 66.7 % | 100.0 % | 1 of 1 | 9.0 | 9.0 |" in markdown
    assert "| $0.0050 | $0.0150 |" in markdown
    assert f"| {wrong} | invoice_number | `{cases[0].truth.invoice_number}` | `X-1` |" in markdown
    assert "Incomplete" not in markdown


def test_the_cap_stops_the_model_in_progress_and_skips_the_rest(tmp_path: Path) -> None:
    """$0.005 per call and $0.02 kept free: under a $0.04 cap, five calls are made."""
    cases = _cases()
    client = RecordingClient(
        tmp_path, _model(cases), Decimal("0.04"), min_reserve_usd=Decimal("0.02")
    )

    results = compare(cases, client, MODELS, "low", THRESHOLD)
    markdown = render(results, client.recorded_on, "low", THRESHOLD)

    assert [len(r.runs) for r in results] == [3, 2, 0]
    assert results[0].stopped is None
    assert all(r.stopped and "cap" in r.stopped for r in results[1:])
    assert "**Incomplete:** `gemini/b` stopped after 2 of 3 invoices" in markdown
    assert "| `gemini/c` | unknown | - | 0 of 3 | 0 | - |" in markdown


def test_a_failed_extraction_is_listed(tmp_path: Path) -> None:
    cases = _cases()[:1]
    client = RecordingClient(tmp_path, RoutingModel({}, "unused"), Decimal(1))
    client.live = None
    client.missing_as_failure = True

    markdown = render(compare(cases, client, MODELS[:1], "low", THRESHOLD), {}, "low", THRESHOLD)

    assert f"| {cases[0].case_id} | (failed) | - | LLM extraction failed" in markdown


def test_prices_come_from_the_pinned_table() -> None:
    assert prices("gemini/gemini-3.8-flash") == (Decimal("0.75"), Decimal("3.75"))
    assert prices("gemini/not-a-model") is None
    assert len(model_comparison.MODELS) <= 3
    assert "gemini/gemini-3.8-flash" in model_comparison.MODELS


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(cli, "RECORDINGS_DIR", tmp_path / "recordings")
    monkeypatch.setattr(cli, "load_manifest", lambda: Manifest(repositories={}, files=()))
    return tmp_path


def test_the_cli_records_live_then_replay_matches(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = [*demo_cases(), *generated_cases("small")]
    monkeypatch.setattr(cli, "_live_client", lambda: _model(cases))
    out = isolated / "comparison.md"
    models = ["--models", "gemini/a,gemini/b", "--out", str(out)]

    cli.main(["models", *models, "--live", "--max-spend-usd", "1"])
    written = out.read_text("utf-8")
    cli.main(["models", *models, "--check"])

    assert "| `gemini/b` | unknown |" in written
    assert f"{len(cases)} of {len(cases)}" in written
    out.write_text(written + "edited\n", "utf-8")
    with pytest.raises(SystemExit, match="differs from the replay"):
        cli.main(["models", *models, "--check"])


def test_the_cli_smoke_run_takes_the_first_invoices(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = _model(demo_cases())
    monkeypatch.setattr(cli, "_live_client", lambda: model)
    out = isolated / "smoke.md"

    cli.main(["models", "--models", "gemini/a", "--limit", "1", "--live",
              "--max-spend-usd", "1", "--out", str(out)])  # fmt: skip

    assert model.calls == 1
    assert "1 of 1" in out.read_text("utf-8")


@pytest.mark.parametrize(
    ("args", "message"),
    [(["--check", "--live"], "replays only"), (["--models", " , "], None)],
)
def test_the_cli_refuses_bad_arguments(args: list[str], message: str | None) -> None:
    with pytest.raises(SystemExit, match=message):
        cli.main(["models", *args])

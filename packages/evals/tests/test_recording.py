"""The recording client: replay never calls a model, a changed request never hits an old reply,
failed calls are not saved, and the spend cap stops a live run before the next call."""

from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from invoiceguard_api.llm import (
    EmbeddingReply,
    EmbeddingTask,
    FilePart,
    LLMError,
    LLMReply,
    ReasoningEffort,
    TextPart,
    UserPart,
)

from invoiceguard_evals.recording import MissingRecording, RecordingClient, SpendCapReached

from .fakes import FakeEmbeddings

REPLY = LLMReply(
    text='{"ok": true}', input_tokens=10, output_tokens=5, cost_usd=Decimal("0.01"), latency_ms=1200
)


class FakeModel(FakeEmbeddings):
    def __init__(self, reply: LLMReply = REPLY, fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.calls = 0
        self.embedded: list[list[str]] = []

    def embed(
        self, *, model: str, texts: Sequence[str], dimensions: int, task: EmbeddingTask
    ) -> EmbeddingReply:
        self.embedded.append(list(texts))
        if self.fail:
            raise LLMError("quota exceeded", 50)
        return super().embed(model=model, texts=texts, dimensions=dimensions, task=task)

    def structured(
        self,
        *,
        model: str,
        system: str,
        user: Sequence[UserPart],
        schema_name: str,
        schema: dict[str, Any],
        reasoning_effort: ReasoningEffort | None = None,
    ) -> LLMReply:
        self.calls += 1
        if self.fail:
            raise LLMError("quota exceeded", 50)
        return self.reply


def ask(
    client: RecordingClient,
    *,
    system: str = "system",
    pdf: bytes = b"%PDF-1",
    effort: ReasoningEffort | None = "low",
) -> LLMReply:
    return client.structured(
        model="gemini/test",
        system=system,
        user=[TextPart("<<<doc>>>"), FilePart("application/pdf", pdf)],
        schema_name="s",
        schema={"type": "object"},
        reasoning_effort=effort,
    )


def test_live_records_and_replay_answers_without_a_model(tmp_path: Path) -> None:
    model = FakeModel()
    live = RecordingClient(tmp_path, model, max_spend_usd=Decimal(1))

    assert ask(live) == REPLY
    assert (live.live_calls, live.spent_usd) == (1, Decimal("0.01"))
    assert ask(live) == REPLY
    assert (model.calls, live.replayed) == (1, 1)

    replay = RecordingClient(tmp_path)
    assert ask(replay) == REPLY
    assert replay.replayed == 1


def test_recordings_store_the_file_hash_not_the_file(tmp_path: Path) -> None:
    ask(RecordingClient(tmp_path, FakeModel(), Decimal(1)), pdf=b"%PDF-secret-bytes")

    (recording,) = tmp_path.iterdir()
    assert "secret-bytes" not in recording.read_text("utf-8")


@pytest.mark.parametrize(
    "change",
    [{"system": "new prompt"}, {"pdf": b"%PDF-2"}, {"effort": "high"}, {"effort": None}],
)
def test_a_changed_request_misses_the_recording(tmp_path: Path, change: dict[str, Any]) -> None:
    ask(RecordingClient(tmp_path, FakeModel(), Decimal(1)))

    with pytest.raises(MissingRecording, match="Run with --live"):
        ask(RecordingClient(tmp_path), **change)


def test_each_run_number_is_its_own_recording(tmp_path: Path) -> None:
    model = FakeModel()
    client = RecordingClient(tmp_path, model, Decimal(1))
    ask(client)
    client.run = 2
    ask(client)

    assert model.calls == 2
    assert len(list(tmp_path.iterdir())) == 2


def test_the_cap_stops_before_the_next_call(tmp_path: Path) -> None:
    model = FakeModel()
    client = RecordingClient(tmp_path, model, max_spend_usd=Decimal("0.01"))
    ask(client)

    with pytest.raises(SpendCapReached):
        ask(client, pdf=b"%PDF-2")
    assert model.calls == 1


def test_a_failed_call_is_not_recorded(tmp_path: Path) -> None:
    client = RecordingClient(tmp_path, FakeModel(fail=True), Decimal(1))

    with pytest.raises(LLMError):
        ask(client)
    assert list(tmp_path.iterdir()) == []


def test_an_unknown_price_is_recorded_as_unknown(tmp_path: Path) -> None:
    unpriced = LLMReply(text="{}", input_tokens=1, output_tokens=1, cost_usd=None, latency_ms=1)
    ask(RecordingClient(tmp_path, FakeModel(unpriced), Decimal(1)))

    assert ask(RecordingClient(tmp_path)).cost_usd is None


def test_replay_can_count_a_missing_recording_as_a_failed_call(tmp_path: Path) -> None:
    with pytest.raises(LLMError, match="live call failed or was never made"):
        ask(RecordingClient(tmp_path, missing_as_failure=True))


def embed(client: RecordingClient, *texts: str) -> EmbeddingReply:
    return client.embed(model="gemini/embed", texts=texts, dimensions=768, task="similarity")


def test_embeddings_are_recorded_per_text_and_replay_in_any_batch(tmp_path: Path) -> None:
    model = FakeModel()
    recorded = embed(RecordingClient(tmp_path, model, Decimal(1)), "Toner", "Papier")

    replayed = embed(RecordingClient(tmp_path), "Papier", "Toner", "Papier")

    assert replayed.vectors == (recorded.vectors[1], recorded.vectors[0], recorded.vectors[1])
    assert len(replayed.vectors[0]) == 768
    assert model.embedded == [["Toner", "Papier"]]
    assert len(list(tmp_path.iterdir())) == 2


def test_live_embeds_only_the_texts_without_a_recording(tmp_path: Path) -> None:
    model = FakeModel()
    client = RecordingClient(tmp_path, model, Decimal(1))
    embed(client, "Toner")

    reply = embed(client, "Toner", "Ordner")

    assert model.embedded == [["Toner"], ["Ordner"]]
    assert reply.cost_usd == Decimal("0.000002")
    assert client.live_calls == 2


def test_a_missing_embedding_stops_replay_or_counts_as_failed(tmp_path: Path) -> None:
    with pytest.raises(MissingRecording, match="1 text"):
        embed(RecordingClient(tmp_path), "Toner")
    with pytest.raises(LLMError, match="never made"):
        embed(RecordingClient(tmp_path, missing_as_failure=True), "Toner")


def test_the_cap_and_failed_calls_record_no_embedding(tmp_path: Path) -> None:
    with pytest.raises(SpendCapReached):
        embed(RecordingClient(tmp_path, FakeModel(), Decimal(0)), "Toner")
    with pytest.raises(LLMError):
        embed(RecordingClient(tmp_path, FakeModel(fail=True), Decimal(1)), "Toner")
    assert list(tmp_path.iterdir()) == []

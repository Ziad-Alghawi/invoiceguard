"""Rulebook retrieval (R3-4b): does `search_rulebook` find the section that answers a question?

20 questions, 10 in English and 10 in German, written for this set after the rulebook. Each names
the sections that answer it (one or two). The rulebook is indexed as `make index` does it, its
sections embedded through the recording client (task `document`), and every question is searched
with the SQL of `mcp-history`'s tool, top 10:

- **vector**: the question embedded with task `query`, cosine similarity;
- **text**: full text without a key, the question's words joined by OR, English and German
  stemmers. The rulebook is English with the German terms written in, so German questions are
  expected to do worse here; the numbers are reported per language.

hit@k is whether a relevant section is among the first k (the tool returns 3), MRR the mean of
1 / the rank of the first relevant one (0 when none is in the top 10).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from invoiceguard_api.db import make_engine, make_session_factory
from invoiceguard_api.llm import Embedder
from invoiceguard_api.models import EMBEDDING_DIMENSIONS, ModelCall
from invoiceguard_api.rulebook import chunks as rulebook_chunks
from invoiceguard_api.rulebook import index as rulebook_index
from invoiceguard_mcp_history.db import Database
from invoiceguard_mcp_history.server import RULEBOOK_TEXT_SQL, RULEBOOK_VECTOR_SQL, or_query
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from invoiceguard_evals.attack_eval import RULEBOOK_DIR
from invoiceguard_evals.decisions import recreate_database

K = 10
METHODS = ("vector", "text")
LANGUAGES = ("en", "de")


@dataclass(frozen=True)
class Question:
    case_id: str
    language: Literal["en", "de"]
    text: str
    # The sections that answer it, as `file#anchor`.
    relevant: frozenset[str]


def _q(case_id: str, language: Literal["en", "de"], text: str, *relevant: str) -> Question:
    return Question(case_id, language, text, frozenset(relevant))


QUESTIONS = (
    _q("r01", "en", "What should I do when the supplier's bank details changed on an invoice?",
       "iban.md#how-to-resolve-a-changed-iban"),
    _q("r02", "en", "Is a German supplier with a Lithuanian bank account suspicious?",
       "iban.md#foreign-ibans"),
    _q("r03", "en", "How much rounding difference does the VAT calculation check allow?",
       "vat-math.md#thresholds"),
    _q("r04", "en", "We received the same invoice number twice from one seller. What now?",
       "duplicate.md#when-it-fails-or-warns", "duplicate.md#how-to-resolve"),
    _q("r05", "en", "The unit price is higher than on the purchase order. How do I resolve it?",
       "po-match.md#how-to-resolve-a-price-above-the-order"),
    _q("r06", "en", "The e-invoice validator rejected the file with BR-DE rule codes.",
       "kosit.md#how-to-resolve", "kosit.md#when-it-fails-or-warns"),
    _q("r07", "en", "Can one reviewer approve a blocked invoice alone?",
       "review-and-override.md#override-of-a-blocked-invoice-four-eyes"),
    _q("r08", "en", "Which account do I book a 700 euro notebook to?",
       "skr03-accounts.md#assets-and-low-value-items"),
    _q("r09", "en", "What confidence threshold applies to fields extracted from a PDF?",
       "low-confidence.md#thresholds"),
    _q("r10", "en", "An invoice has hidden text that gives orders to an AI assistant.",
       "prompt-injection.md#what-the-check-does", "prompt-injection.md#when-it-fails"),
    _q("r11", "de", "Die IBAN auf der Rechnung ist keine verifizierte Bankverbindung des "
       "Lieferanten. Was ist zu tun?",
       "iban.md#how-to-resolve-a-changed-iban", "iban.md#when-it-fails-or-warns"),
    _q("r12", "de", "Auf welches Konto buche ich Kopierpapier und Toner?",
       "skr03-accounts.md#office-and-it"),
    _q("r13", "de", "Der Lieferant ist nicht in den Kreditorenstammdaten angelegt.",
       "supplier-known.md#when-it-warns", "supplier-known.md#how-to-resolve"),
    _q("r14", "de", "Es wurde weniger berechnet als bestellt, eine Teillieferung.",
       "po-match.md#how-to-resolve-a-partial-delivery"),
    _q("r15", "de", "Die Beträge addieren sich nicht, die Umsatzsteuer ist falsch berechnet.",
       "vat-math.md#when-it-fails", "vat-math.md#how-to-resolve"),
    _q("r16", "de", "Kann eine abgelehnte Rechnung wieder geöffnet werden?",
       "review-and-override.md#reopen"),
    _q("r17", "de", "Eine Mahnung kommt als neues Dokument mit anderer Nummer.",
       "duplicate.md#how-to-resolve", "duplicate.md#when-it-fails-or-warns"),
    _q("r18", "de", "Wie buche ich Bewirtungskosten für ein Geschäftsessen?",
       "skr03-accounts.md#premises-vehicles-services"),
    _q("r19", "de", "Was bedeutet das Vier-Augen-Prinzip bei gesperrten Rechnungen?",
       "review-and-override.md#override-of-a-blocked-invoice-four-eyes"),
    _q("r20", "de", "Die Rechnung nennt keine Bankverbindung, sie wird per Lastschrift bezahlt.",
       "iban.md#when-it-fails-or-warns"),
)  # fmt: skip


def _rank(found: list[str], relevant: frozenset[str]) -> int | None:
    return next((rank for rank, key in enumerate(found, start=1) if key in relevant), None)


def _rate(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def _summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"questions": len(cases)}
    for method in METHODS:
        ranks = [case[method]["rank"] for case in cases]
        summary[method] = {
            "hit1": _rate([rank == 1 for rank in ranks]),
            "hit3": _rate([rank is not None and rank <= 3 for rank in ranks]),
            "mrr": sum(1 / rank for rank in ranks if rank) / len(ranks) if ranks else None,
        }
    return summary


def _keys(rows: list[dict[str, Any]]) -> list[str]:
    return [f"{row['source']}#{row['anchor']}" for row in rows]


def evaluate_rulebook(database_url: str, embedder: Embedder, model: str) -> dict[str, Any]:
    url = recreate_database(database_url)
    engine = make_engine(url)
    chunks = rulebook_chunks.load(RULEBOOK_DIR)
    known = {chunk.key for chunk in chunks}
    unknown = {key for question in QUESTIONS for key in question.relevant} - known
    if unknown:
        raise ValueError(f"Questions name sections that do not exist: {sorted(unknown)}")
    database = Database(make_url(url).set(drivername="postgresql").render_as_string(False))
    try:
        with make_session_factory(engine)() as session:
            empty = {"model": model, "dimensions": EMBEDDING_DIMENSIONS, "vectors": {}}
            rulebook_index.sync(session, chunks, model, embedder, empty)
            spent = session.scalar(select(func.coalesce(func.sum(ModelCall.cost_usd), 0)))
            document_cost = Decimal(spent or 0)
        replies = embedder.embed(
            model=model,
            texts=[question.text for question in QUESTIONS],
            dimensions=EMBEDDING_DIMENSIONS,
            task="query",
        )
        cases = []
        for question, vector in zip(QUESTIONS, replies.vectors, strict=True):
            by_vector = _keys(
                database.rows(
                    RULEBOOK_VECTOR_SQL, {"vector": str(list(vector)), "model": model, "k": K}
                )
            )
            words = or_query(question.text)
            by_text = (
                []
                if words is None
                else _keys(database.rows(RULEBOOK_TEXT_SQL, {"words": words, "k": K}))
            )
            case: dict[str, Any] = {
                "case": question.case_id,
                "language": question.language,
                "question": question.text,
                "relevant": sorted(question.relevant),
            }
            for method, found in (("vector", by_vector), ("text", by_text)):
                case[method] = {"found": found[:3], "rank": _rank(found, question.relevant)}
            cases.append(case)
    finally:
        engine.dispose()
    return {
        "model": model,
        "sections": len(chunks),
        "files": len({chunk.source for chunk in chunks}),
        "embedding_cost_usd": str(document_cost + (replies.cost_usd or Decimal(0))),
        "summary": _summary(cases),
        "by_language": {
            language: _summary([c for c in cases if c["language"] == language])
            for language in LANGUAGES
        },
        "cases": cases,
    }

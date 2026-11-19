"""Booking suggestions and retrieval (R3-4, ADR-020), with the app's own code.

A fresh eval database gets the packaged booking history (`bookings.py`), every text is embedded
through the recording client, and each held-out line is asked for a suggestion with the app's
`neighbours` and `vote`: once by vector and once by the text match, which the app uses for lines
without a vector (the demo's uploads).

- Suggestions: top-1 and top-3 accuracy against the item's account.
- Retrieval: a booking is relevant when it books the same catalogue item. hit@k is whether one of
  the first k neighbours is relevant, MRR the mean of 1 / the rank of the first relevant one
  (0 when none of the K is).
- The first design's vote (plain sum of scores, `vote(..., temperature=None)`), which the app
  replaced after the first run (ADR-020): shown for comparison, top-1 and top-3 only.
- Baselines without retrieval: the supplier's most frequent account (overall for a supplier
  without history), and always the default expense account 4900.
"""

from collections import Counter
from typing import Any

from invoiceguard_api.booking.embedding import EMBEDDING_PURPOSE, embed_missing
from invoiceguard_api.booking.history import import_history, packaged_history
from invoiceguard_api.booking.suggest import K_NEIGHBOURS, Neighbour, neighbours, vote
from invoiceguard_api.booking.text import normalise
from invoiceguard_api.db import make_engine, make_session_factory
from invoiceguard_api.llm import Embedder
from invoiceguard_api.models import Booking, ModelCall
from sqlalchemy import func, select

from invoiceguard_evals.bookings import HeldOutLine, held_out_lines, item_of_text
from invoiceguard_evals.decisions import recreate_database

DEFAULT_ACCOUNT = "4900"
KINDS = ("seen", "unseen", "new_supplier")
METHODS = ("vector", "text", "vector_sum")


def _rank_of_relevant(found: list[Neighbour], item_id: str, items: dict[str, str]) -> int | None:
    for rank, neighbour in enumerate(found, start=1):
        if items.get(neighbour.text) == item_id:
            return rank
    return None


def _baselines(history: list[dict[str, Any]]) -> tuple[dict[str, str], str]:
    """The most frequent account per supplier and overall (ties: the lower account number)."""
    by_supplier: dict[str, Counter[str]] = {}
    overall: Counter[str] = Counter()
    for invoice in history:
        counter = by_supplier.setdefault(invoice["supplier_vat_id"], Counter())
        for line in invoice["lines"]:
            counter[line["account"]] += 1
            overall[line["account"]] += 1

    def top(counter: Counter[str]) -> str:
        return min(counter, key=lambda account: (-counter[account], account))

    return {vat_id: top(counter) for vat_id, counter in by_supplier.items()}, top(overall)


def _case(
    line: HeldOutLine,
    results: dict[str, tuple[list[Neighbour], list[str]]],
    items: dict[str, str],
    supplier_top: dict[str, str],
    overall_top: str,
) -> dict[str, Any]:
    case: dict[str, Any] = {
        "case": line.case_id,
        "kind": line.kind,
        "line": line.text,
        "account": line.account,
        "baselines": {
            "supplier_top": supplier_top.get(line.supplier_vat_id, overall_top),
            "default": DEFAULT_ACCOUNT,
        },
    }
    for method, (found, ranked) in results.items():
        rank = _rank_of_relevant(found, line.item_id, items)
        case[method] = {
            "suggested": ranked,
            "top1": ranked[:1] == [line.account],
            "top3": line.account in ranked[:3],
            "rank": rank,
        }
    return case


def _rate(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def _summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"lines": len(cases)}
    for method in METHODS:
        ranks = [case[method]["rank"] for case in cases]
        summary[method] = {
            "top1": _rate([case[method]["top1"] for case in cases]),
            "top3": _rate([case[method]["top3"] for case in cases]),
            "hit1": _rate([rank == 1 for rank in ranks]),
            "hit3": _rate([rank is not None and rank <= 3 for rank in ranks]),
            f"hit{K_NEIGHBOURS}": _rate([rank is not None for rank in ranks]),
            "mrr": sum(1 / rank for rank in ranks if rank) / len(ranks) if ranks else None,
        }
    for baseline in ("supplier_top", "default"):
        summary[baseline] = {
            "top1": _rate([case["baselines"][baseline] == case["account"] for case in cases])
        }
    return summary


def evaluate_bookings(database_url: str, embedder: Embedder, model: str) -> dict[str, Any]:
    url = recreate_database(database_url)
    engine = make_engine(url)
    history = packaged_history()
    lines = held_out_lines()
    items = {normalise(text): item for text, item in item_of_text().items()}
    supplier_top, overall_top = _baselines(history)
    try:
        with make_session_factory(engine)() as session:
            imported = import_history(session, history)
            session.commit()
            texts = [*session.scalars(select(Booking.text).distinct()), *(x.text for x in lines)]
            embed_missing(session, embedder, model, texts)
            cost = session.scalar(
                select(func.coalesce(func.sum(ModelCall.cost_usd), 0)).where(
                    ModelCall.purpose == EMBEDDING_PURPOSE
                )
            )
            cases = []
            for line in lines:
                results: dict[str, tuple[list[Neighbour], list[str]]] = {}
                for method, method_model in (("vector", model), ("text", None)):
                    used, found = neighbours(session, method_model, line.text, line.supplier_vat_id)
                    if used != method:
                        raise RuntimeError(f"{line.case_id}: expected {method}, got {used}")
                    results[method] = (found, [s.account for s in vote(found)])
                    if method == "vector":
                        results["vector_sum"] = (
                            found,
                            [s.account for s in vote(found, temperature=None)],
                        )
                cases.append(_case(line, results, items, supplier_top, overall_top))
    finally:
        engine.dispose()
    return {
        "model": model,
        "history_bookings": imported,
        "history_invoices": len(history),
        "embedded_texts": len(set(normalise(text) for text in texts)),
        "embedding_cost_usd": str(cost),
        "summary": _summary(cases),
        "by_kind": {kind: _summary([c for c in cases if c["kind"] == kind]) for kind in KINDS},
        "cases": cases,
    }

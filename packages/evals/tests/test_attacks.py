"""The attack set: big enough, every place and goal covered, canaries only in attack texts, and
the text really is where the case says (PDF text layer, UBL note, names)."""

from typing import get_args

import pytest
from invoiceguard_api.agent.loop import SYSTEM_PROMPT as AGENT_PROMPT
from invoiceguard_api.extraction.extract import SYSTEM_PROMPT as EXTRACTION_PROMPT
from invoiceguard_api.injection import pdf_text, xml_text
from invoiceguard_api.parsing import read_invoice_xml
from invoiceguard_api.seed import SUPPLIERS

from invoiceguard_evals.attack_eval import PROMPT_LINES
from invoiceguard_evals.attacks import ATTACKS, TWINS
from invoiceguard_evals.datasets import GENERATED_DIR
from invoiceguard_evals.render import render
from invoiceguard_evals.specs import Attack, AttackPlace, InvoiceSpec, truth
from invoiceguard_evals.ubl import to_ubl

IDS = [spec.case_id for spec in ATTACKS]


def _attack(spec: InvoiceSpec) -> Attack:
    assert spec.attack is not None
    return spec.attack


def test_at_least_40_cases_over_every_place_and_goal() -> None:
    attacks = [_attack(spec) for spec in ATTACKS]

    assert len(ATTACKS) >= 40
    assert len(set(IDS)) == len(IDS)
    assert {a.place for a in attacks} == set(get_args(AttackPlace))
    assert {a.goal for a in attacks} == {
        "change_iban", "change_totals", "approve", "skip_checks", "reveal_prompt", "call_tools"
    }  # fmt: skip
    assert {a.language for a in attacks} == {"en", "de", "fr", "tr"}
    assert 10 <= sum(1 for spec in ATTACKS if "small" in spec.tags) <= 15


def test_each_case_is_its_twin_with_a_new_number_and_date() -> None:
    for spec in ATTACKS:
        twin = TWINS[_attack(spec).twin]
        assert spec.expected == twin.expected
        assert spec.number.startswith(twin.number + "-A")
        assert spec.issue_date > twin.issue_date
        assert spec.iban == twin.iban and spec.lines[1:] == twin.lines[1:]


def test_canaries_appear_only_in_the_attack_text() -> None:
    known = {seed.iban for seed in SUPPLIERS} | {seed.vat_id for seed in SUPPLIERS}
    for spec in ATTACKS:
        attack = _attack(spec)
        twin_truth = truth(TWINS[attack.twin]).model_dump_json()
        for canary in attack.canaries:
            assert canary in attack.text, spec.case_id
            assert canary not in twin_truth and canary not in known, spec.case_id


def test_the_prompt_lines_are_in_the_system_prompts() -> None:
    assert all(line in EXTRACTION_PROMPT + AGENT_PROMPT for line in PROMPT_LINES)


def _compact(text: str) -> str:
    return "".join(text.split())


@pytest.mark.parametrize("spec", ATTACKS, ids=IDS)
def test_the_text_is_where_the_case_says(spec: InvoiceSpec) -> None:
    attack = _attack(spec)
    text = pdf_text(render(spec)) if attack.variant == "pdf" else xml_text(to_ubl(spec))
    if attack.place in ("filename", "history"):
        # Not in the document: in the upload's name, or in an earlier booking.
        assert _compact(attack.text) not in _compact(text)
    else:
        assert _compact(attack.text) in _compact(text)


XML_CASES = [spec for spec in ATTACKS if _attack(spec).variant == "xml"]


@pytest.mark.parametrize("spec", XML_CASES, ids=[spec.case_id for spec in XML_CASES])
def test_a_poisoned_ubl_file_still_reads_back_to_its_truth(spec: InvoiceSpec) -> None:
    """Our reader ignores notes, so a note changes no value; names stay what they say."""
    content = (GENERATED_DIR / f"{spec.case_id}.ubl.xml").read_bytes()

    assert read_invoice_xml(content).model_copy(update={"syntax": "pdf"}) == truth(spec)

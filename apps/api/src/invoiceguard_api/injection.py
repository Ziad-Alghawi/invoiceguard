"""Heuristic prompt-injection scan of an invoice's text (PLAN section 5, R2-4). No LLM (ADR-002).

Invoice text is untrusted data: no model ever gets it as instructions (ADR-010), and the checks
decide on parsed values, not on prose. This scan is a second line: it flags text that tries to
talk to an AI system, so a reviewer looks twice and the attempt is logged as a security event.
It looks for two things in the document text, the XML element text and attribute values, and
the PDF's text layer:

- instructions to an AI, in English or German ("ignore all previous instructions", "you are now",
  "set the status to ...", "Ignoriere alle vorherigen Anweisungen", chat markup), matched after
  Unicode normalisation (NFKC, case folding, invisible characters removed), so full-width letters
  or a zero-width space inside a word do not hide a phrase;
- invisible characters that have no place in an invoice: zero-width characters, bidirectional
  controls and Unicode tag characters (used to hide text from a human reader).

The rules are specific on purpose: business text such as "ignorieren Sie diese Mahnung" or
"please disregard this reminder" does not match. Text drawn white or tiny is in the text layer and
scanned like any other, but hiding it is not itself a signal; text in an image is not seen (a
scanned PDF without a text layer is reported as not scanned).
"""

import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from invoiceguard_api.parsing import ParseError
from invoiceguard_api.parsing.safe_xml import parse_xml

logger = logging.getLogger(__name__)

Source = Literal["xml", "pdf_text"]
# Enough for any invoice; a hostile 1,000-page PDF is not read to the end.
MAX_PDF_PAGES = 20
MAX_FINDINGS = 10
SNIPPET_CONTEXT = 40

# Zero-width space/joiners and marks, bidi embeddings and overrides, word joiner and invisible
# operators, bidi isolates, Unicode tags. Not U+00AD (soft hyphen, common in German text) and
# not U+FEFF (a byte order mark that PDF text extraction can leave behind).
INVISIBLE = re.compile(
    "[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\U000e0000-\U000e007f]"
)

_W = r"[\w-]+"
RULES: dict[str, re.Pattern[str]] = {
    # "ignore all previous instructions", "disregard the above rules", "forget your guidelines"
    "ignore_instructions": re.compile(
        rf"\b(ignore|disregard|forget|override|bypass)\b(?: {_W}){{0,3}}? "
        rf"(previous|prior|above|earlier|preceding|all|any|your|these|those|system)\b"
        rf"(?: {_W}){{0,2}}? (instructions?|rules?|prompts?|directions?|guidelines?|commands?)\b"
    ),
    # "Ignoriere alle vorherigen Anweisungen", "Vergiss deine Regeln"
    "ignore_instructions_de": re.compile(
        rf"\b(ignorier\w*|vergiss|vergessen sie|missacht\w*|übergeh\w*)\b(?: {_W}){{0,4}}? "
        rf"(anweisung\w*|instruktion\w*|regeln|vorgaben|befehl\w*|richtlinien)\b"
    ),
    # "note to the AI assistant", "Hinweis für KI-Assistenten", "message for the language model"
    "addressed_to_ai": re.compile(
        r"\b(note|notice|message|instructions?|hinweis|nachricht|anweisung\w*) "
        r"(to|for|an|für) (the |das |den |die |alle )?"
        r"(ai|ki|llm|assistant|assistent\w*|ki-assistent\w*|ai assistant|chatbot|language model|"
        r"sprachmodell\w*)\b"
    ),
    "system_prompt": re.compile(
        r"\b(system ?prompt|system message|systemnachricht|systemanweisung\w*|developer mode|"
        r"entwicklermodus|jailbreak|do anything now)\b"
    ),
    # "you are now", "act as the", "pretend to be", "du bist jetzt", "ab sofort bist du"
    "role_change": re.compile(
        r"\b(you are now|from now on,? you|act as (an?|the)|pretend (to be|you are)|"
        r"du bist (jetzt|nun|ab sofort)|ab (jetzt|sofort) bist du|verhalte dich wie)\b"
    ),
    "chat_markup": re.compile(
        r"(<\|(im_start|im_end|system|user|assistant)\|>|\[/?inst\]|<</?sys>>)"
    ),
    # "set the status to ready", "change the IBAN to", "mark the invoice as approved"
    "change_decision": re.compile(
        r"\b(set|change|mark|report|output|return) (the |this )?"
        r"(status|iban|bank account|confidence|invoice|rechnung)\b.{0,30}\b"
        r"(to|as) (ready|approved|genehmigt|freigegeben|1(\.0)?|true)\b"
    ),
    "change_decision_de": re.compile(
        r"\b(setze|setzen sie|markiere|markieren sie|gib|geben sie)\b.{0,40}\b"
        r"(status|iban|rechnung)\b.{0,30}\b(auf|als) (ready|genehmigt|freigegeben)\b"
    ),
    # "do not mention this", "don't tell the user", "erwähne das nicht"
    "concealment": re.compile(
        r"\b(do not|don't|never) (mention|tell|reveal|report|disclose)\b"
        r"|\b(erwähne|erwähnen sie|verrate|verraten sie)\b.{0,20}\bnicht\b"
    ),
}


@dataclass(frozen=True)
class Finding:
    kind: Literal["instruction", "invisible_characters"]
    rule: str
    # Where it is, as normalised text (instructions) or as code points (invisible characters).
    # Untrusted text: shown to reviewers as data, never given to a model.
    snippet: str


@dataclass(frozen=True)
class InjectionScan:
    """What was scanned and what was found; no sources means there was no text to scan."""

    sources: tuple[Source, ...] = ()
    characters: int = 0
    findings: tuple[Finding, ...] = field(default=())


def normalise(text: str) -> str:
    text = INVISIBLE.sub("", unicodedata.normalize("NFKC", text))
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _snippet(text: str, start: int, end: int) -> str:
    before = max(0, start - SNIPPET_CONTEXT)
    after = min(len(text), end + SNIPPET_CONTEXT)
    return ("…" if before else "") + text[before:after] + ("…" if after < len(text) else "")


def scan_text(text: str) -> tuple[Finding, ...]:
    """The findings in one text, at most MAX_FINDINGS."""
    findings: list[Finding] = []
    hidden = sorted({f"U+{ord(char):04X}" for char in INVISIBLE.findall(text)})
    if hidden:
        findings.append(Finding("invisible_characters", "invisible_characters", ", ".join(hidden)))
    normalised = normalise(text)
    for rule, pattern in RULES.items():
        for match in pattern.finditer(normalised):
            findings.append(Finding("instruction", rule, _snippet(normalised, *match.span())))
            break
    return tuple(findings[:MAX_FINDINGS])


def xml_text(xml: bytes) -> str:
    """Every element text and attribute value of the XML; empty if it cannot be parsed."""
    try:
        root = parse_xml(xml)
    except ParseError:
        return ""
    parts: list[str] = []
    for element in root.iter():
        parts.extend(str(value) for value in element.attrib.values())
        if isinstance(element.tag, str) and element.text:
            parts.append(element.text)
        if element.tail:
            parts.append(element.tail)
    return "\n".join(part for part in parts if part.strip())


def pdf_text(pdf: bytes) -> str:
    """The text layer of the first MAX_PDF_PAGES pages; empty for a scan or an unreadable PDF."""
    try:
        reader = PdfReader(io.BytesIO(pdf))
        return "\n".join(page.extract_text() or "" for page in reader.pages[:MAX_PDF_PAGES])
    except (PyPdfError, ValueError, KeyError) as error:
        logger.info("PDF text for the injection scan could not be read: %s", error)
        return ""


def scan(xml: bytes | None = None, pdf: bytes | None = None) -> InjectionScan:
    """Scan the invoice XML and/or the PDF text layer."""
    texts: list[tuple[Source, str]] = []
    if xml is not None:
        texts.append(("xml", xml_text(xml)))
    if pdf is not None:
        texts.append(("pdf_text", pdf_text(pdf)))
    texts = [(source, text) for source, text in texts if text.strip()]
    findings = tuple(finding for _, text in texts for finding in scan_text(text))
    return InjectionScan(
        sources=tuple(source for source, _ in texts),
        characters=sum(len(text) for _, text in texts),
        findings=findings[:MAX_FINDINGS],
    )

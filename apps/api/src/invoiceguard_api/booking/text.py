"""The text of an invoice line that is embedded and compared (ADR-020)."""

import hashlib
import unicodedata

# Item names are short; a longer one is cut so a hostile invoice cannot make embeddings costly.
MAX_TEXT_CHARS = 500


def normalise(text: str) -> str:
    """NFC with whitespace collapsed, cut to MAX_TEXT_CHARS. Not NFKC: the text is shown to
    reviewers as printed ("g/m²" stays), and case is kept."""
    return " ".join(unicodedata.normalize("NFC", text).split())[:MAX_TEXT_CHARS]


def text_sha256(normalised: str) -> str:
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()

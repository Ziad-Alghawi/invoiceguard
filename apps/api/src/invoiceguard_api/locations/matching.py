"""How a field value can be printed: one regular expression per field, built by code from the
stored value (P1, ADR-029). No model is involved.

Values are stored normalised (EN 16931 terms: ISO dates, decimals with a dot, IBANs without
spaces), while a PDF prints them for people: "1.234,50 €" or "1,234.50", "27.11.2026" or
"27 November 2026", "DE89 3704 0044 ...". Each pattern accepts the usual German and English
forms and refuses a match inside a longer number or word.
"""

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

# Term codes by kind of value (parsing/fields.py).
AMOUNTS = frozenset({"BT-106", "BT-107", "BT-108", "BT-109", "BT-110", "BT-112", "BT-115"})
LINE_AMOUNTS = frozenset({"BT-131", "BT-146"})
QUANTITIES = frozenset({"BT-129", "BT-152"})
DATES = frozenset({"BT-2", "BT-9"})
COMPACT_IDS = frozenset({"BT-84", "BT-31", "BT-48"})

# Thousands separators seen in invoices: dot, comma, (narrow) no-break space, space, apostrophe.
GROUP = "[.,\u00a0\u202f '\u2019]?"
# Not inside a longer number: no digit, and no separator followed by a digit, on either side.
NUMBER_START = r"(?<![\d])(?<![\d][.,])"
NUMBER_END = r"(?![\d])(?![.,]\d)"

MONTHS = {
    1: ("Januar", "Jänner", "January", "Jan"),
    2: ("Februar", "February", "Feb"),
    3: ("März", "Maerz", "March", "Mär", "Mar"),
    4: ("April", "Apr"),
    5: ("Mai", "May"),
    6: ("Juni", "June", "Jun"),
    7: ("Juli", "July", "Jul"),
    8: ("August", "Aug"),
    9: ("September", "Sept", "Sep"),
    10: ("Oktober", "October", "Okt", "Oct"),
    11: ("November", "Nov"),
    12: ("Dezember", "December", "Dez", "Dec"),
}

# Printed words for the codes an invoice shows as text (UNTDID 1001, UN/ECE Rec. 20).
TYPE_CODE_WORDS = {
    "380": ("Rechnung", "Invoice"),
    "381": ("Gutschrift", "Credit note"),
    "384": ("Rechnungskorrektur", "Korrekturrechnung", "Corrected invoice"),
    "326": ("Teilrechnung", "Partial invoice"),
    "875": ("Abschlagsrechnung",),
}
UNIT_WORDS = {
    "C62": ("Stück", "Stk", "St", "pcs", "piece", "pieces"),
    "H87": ("Stück", "Stk", "St", "pcs", "piece", "pieces"),
    "XPP": ("Stück", "Stk", "pcs"),
    "HUR": ("Stunden", "Stunde", "Std", "hours", "hour", "h"),
    "DAY": ("Tage", "Tag", "days", "day"),
    "MON": ("Monate", "Monat", "months", "month"),
    "LS": ("pauschal", "Pauschale", "lump sum"),
    "KGM": ("kg",),
    "MTK": ("m2", "qm"),
    "MTR": ("m",),
    "LTR": ("l", "Liter", "litre"),
    "SET": ("Set", "Satz"),
}
CURRENCY_SIGNS = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF"}


def _integer(digits: str) -> str:
    """Integer digits with an optional thousands separator between groups of three."""
    head = len(digits) % 3 or 3
    groups = [digits[:head]] + [digits[i : i + 3] for i in range(head, len(digits), 3)]
    return GROUP.join(groups)


def amount_pattern(value: str, *, minimum_decimals: int = 2) -> str | None:
    """1234.5 -> "1.234,50", "1234,50", "1,234.50", "1 234,5000"; a minus may be printed or not."""
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    digits, _, fraction = f"{abs(number):f}".partition(".")
    # Prices are often printed with four decimals: 9.9 may read "9,90" or "9,9000".
    fraction = fraction.rstrip("0").ljust(minimum_decimals, "0")
    sign = r"(?:-\s?)?" if number < 0 else ""
    body = _integer(digits) + (rf"[.,]{fraction}0*" if fraction else "")
    return f"{NUMBER_START}{sign}{body}{NUMBER_END}"


def quantity_pattern(value: str) -> str | None:
    """3, 3.000 or 19.00: the integer alone, or with any number of trailing zero decimals."""
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    digits, _, fraction = f"{abs(number).normalize():f}".partition(".")
    tail = rf"[.,]{fraction}0*" if fraction else r"(?:[.,]0+)?"
    return f"{NUMBER_START}{_integer(digits)}{tail}{NUMBER_END}"


def date_pattern(value: str) -> str | None:
    """2026-11-05 -> 05.11.2026, 5.11.26, 05/11/2026, 11/05/2026, 5. November 2026, Nov 5, 2026."""
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return None
    d = rf"0?{day.day}"
    m = rf"0?{day.month}"
    y = rf"(?:{day.year}|{day.year % 100:02d})"
    months = "|".join(re.escape(name) for name in MONTHS[day.month])
    forms = [
        rf"{d}\s?\.\s?{m}\s?\.\s?{y}",
        rf"{d}/{m}/{y}",
        rf"{m}/{d}/{y}",
        rf"{d}-{m}-{y}",
        re.escape(day.isoformat()),
        rf"{d}\.?\s(?:{months})\.?,?\s{day.year}",
        rf"(?:{months})\.?\s{d}(?:st|nd|rd|th)?,?\s{day.year}",
    ]
    return rf"(?<![\d])(?:{'|'.join(forms)})(?![\d])"


def compact_pattern(value: str) -> str:
    """An IBAN or VAT ID: printed with or without spaces between its characters."""
    chars = [re.escape(char) for char in re.sub(r"\s+", "", value)]
    return r"(?<![0-9A-Za-z])" + r"\s?".join(chars) + r"(?![0-9A-Za-z])"


def text_pattern(value: str) -> str:
    """Names and numbers as printed: any run of whitespace (a line break, too) for a space."""
    words = [re.escape(word) for word in value.split()]
    return r"(?<!\w)" + r"\s+".join(words) + r"(?!\w)"


def words_pattern(words: tuple[str, ...]) -> str:
    return r"(?<!\w)(?:" + "|".join(re.escape(word) for word in words) + r")(?!\w)"


def value_pattern(code: str, value: str) -> re.Pattern[str] | None:
    """The pattern for one stored field, or None when the value cannot be printed as text."""
    # The text layer is NFKC-normalised (text_layer.py), so the value is too: "m²" becomes "m2".
    value = unicodedata.normalize("NFKC", value).strip()
    if not value:
        return None
    pattern: str | None
    if code in AMOUNTS or code in LINE_AMOUNTS:
        pattern = amount_pattern(value)
    elif code in QUANTITIES:
        pattern = quantity_pattern(value)
    elif code in DATES:
        pattern = date_pattern(value)
    elif code in COMPACT_IDS:
        pattern = compact_pattern(value)
    elif code == "BT-3":
        pattern = words_pattern(TYPE_CODE_WORDS.get(value, (value,)))
    elif code == "BT-130":
        pattern = words_pattern(UNIT_WORDS.get(value, (value,)))
    elif code == "BT-5":
        sign = CURRENCY_SIGNS.get(value)
        pattern = words_pattern((value,)) + (f"|{re.escape(sign)}" if sign else "")
    else:
        pattern = text_pattern(value)
    return None if pattern is None else re.compile(pattern, re.IGNORECASE)

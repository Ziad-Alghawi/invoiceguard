"""Readable XRechnung (P1, ADR-029): the official KoSIT visualization of an invoice's XML.

The validator container renders it (its second port, `services/validator`); this module asks for
the HTML, makes it static and marks the field the reviewer clicked:

- every `<script>` and every `on*` attribute is removed. The page is shown in a sandboxed iframe
  under a CSP without scripts anyway; this is the second wall, and it keeps the stored invoice's
  text from ever running as code;
- the viewer's tabs need its script, so their panels are all shown, one below the other, and
  the tab bar is hidden;
- the clicked term gets a highlight and an anchor (`#highlight`): the viewer gives every value
  the CSS class of its business term (`class="BT-84 boxdaten wert"`), one per invoice line for
  line terms, so the n-th element of a line term's class is line n.
"""

import logging
import re
import threading
import urllib.error
import urllib.request
from collections import OrderedDict
from typing import Literal

from lxml import html as lxml_html

logger = logging.getLogger(__name__)

Language = Literal["de", "en"]
HIGHLIGHT_ID = "highlight"
NEWLINE = chr(10)
TERM = re.compile(r"^BT-\d{1,3}$")
# Rendered pages kept per invoice file and language; about 100 KB each.
CACHE_SIZE = 16

STATIC_CSS = """
.menue { display: none !important; }
.divHide, .divShow { display: block !important; }
"""
HIGHLIGHT_CSS = """
#highlight { background: #fde047 !important; color: #111 !important;
  outline: 3px solid #eab308; scroll-margin: 40vh; }
"""


class VisualizationUnavailable(Exception):
    """The visualization service is not configured, not reachable or refused the invoice."""


def make_static(page: str, term: str | None = None, line_no: int | None = None) -> str:
    """The page without scripts or event handlers, all panels shown, the term marked."""
    root = lxml_html.document_fromstring(page)
    for script in list(root.iter("script")):
        parent = script.getparent()
        if parent is not None:
            parent.remove(script)
    elements = [element for element in root.iter() if isinstance(element.tag, str)]
    for element in elements:
        for name in [name for name in element.attrib if str(name).lower().startswith("on")]:
            del element.attrib[name]
    css = STATIC_CSS
    if term is not None and TERM.match(term):
        matches = [e for e in elements if term in (e.get("class") or "").split()]
        if matches:
            index = line_no - 1 if line_no is not None and line_no <= len(matches) else 0
            matches[index].set("id", HIGHLIGHT_ID)
            css += HIGHLIGHT_CSS
    head = root.find("head")
    if head is None:
        head = root.makeelement("head")
        root.insert(0, head)
    style = head.makeelement("style")
    style.text = css
    head.append(style)
    body: str = lxml_html.tostring(root, encoding="unicode")
    return f"<!DOCTYPE html>{NEWLINE}{body}"


class Visualizer:
    """Client of the validator's `/visualize` endpoint, with a small cache per file."""

    def __init__(self, url: str | None, timeout_seconds: float) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self._cache: OrderedDict[tuple[str, Language], str] = OrderedDict()
        self._lock = threading.Lock()

    def render(self, sha256: str, xml: bytes, language: Language) -> str:
        """The visualization's HTML for an invoice file (cached by its SHA-256)."""
        key = (sha256, language)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        page = self._request(xml, language)
        with self._lock:
            self._cache[key] = page
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        return page

    def _request(self, xml: bytes, language: Language) -> str:
        if self.url is None:
            raise VisualizationUnavailable("The XRechnung visualization is not configured.")
        url = f"{self.url.rstrip('/')}/visualize?lang={language}"
        request = urllib.request.Request(
            url, data=xml, method="POST", headers={"Content-Type": "application/xml"}
        )
        try:
            # The URL comes from our settings, never from the invoice.
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return str(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            reason = f"The XRechnung visualization answered HTTP {error.code}."
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            reason = f"The XRechnung visualization is not reachable: {error}"
        logger.warning("XRechnung view unavailable: %s", reason)
        raise VisualizationUnavailable(reason)

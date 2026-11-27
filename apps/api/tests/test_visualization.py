"""Readable XRechnung (P1, ADR-029): the KoSIT visualization made static, with the clicked term
marked; the endpoint with a fake renderer, and (marked `kosit`) the real service."""

import os
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from lxml import html as lxml_html

from conftest import poll_until_done
from invoiceguard_api.visualization import (
    HIGHLIGHT_ID,
    Language,
    VisualizationUnavailable,
    Visualizer,
    make_static,
)

VISUALIZATION_URL_ENV = "INVOICEGUARD_TEST_VISUALIZATION_URL"

# The shape of the KoSIT viewer's page: scripts, tab buttons with handlers, hidden panels and a
# CSS class per business term.
VIEWER_PAGE = """<html lang="de"><head><title>XRechnung</title>
<script>function show(e) { alert(1) }</script></head>
<body onload="init()"><div class="menue"><button onclick="show(this)">Details</button></div>
<div id="uebersicht" class="divShow"><div class="BT-1 boxdaten wert">RE-1</div>
<div class="BT-84 boxdaten wert" onmouseover="steal()">DE60 1234</div></div>
<div id="details" class="divHide">
<div class="BT-153 boxdaten wert">Notebook</div><div class="BT-153 boxdaten wert">Setup</div>
</div><script src="x.js"></script></body></html>"""


def _page(static: str) -> Any:
    return lxml_html.document_fromstring(static)


def test_static_page_has_no_scripts_or_handlers_and_shows_every_panel() -> None:
    static = make_static(VIEWER_PAGE)
    page = _page(static)
    assert static.startswith("<!DOCTYPE html>")
    assert page.xpath("//script") == []
    assert [a for e in page.iter() for a in e.attrib if str(a).lower().startswith("on")] == []
    assert ".divHide, .divShow { display: block !important; }" in static
    assert page.get_element_by_id(HIGHLIGHT_ID, None) is None


def test_the_clicked_term_is_marked_and_line_terms_by_line() -> None:
    page = _page(make_static(VIEWER_PAGE, "BT-84"))
    assert page.get_element_by_id(HIGHLIGHT_ID).text == "DE60 1234"
    assert "#highlight" in page.findtext(".//style")
    assert _page(make_static(VIEWER_PAGE, "BT-153", 2)).get_element_by_id(HIGHLIGHT_ID).text == (
        "Setup"
    )
    # A line beyond the page's lines marks the first; an unknown term marks nothing.
    assert _page(make_static(VIEWER_PAGE, "BT-153", 9)).get_element_by_id(HIGHLIGHT_ID).text == (
        "Notebook"
    )
    assert _page(make_static(VIEWER_PAGE, "BT-999")).get_element_by_id(HIGHLIGHT_ID, None) is None
    # Not a term code: nothing is marked.
    assert "#highlight" not in make_static(VIEWER_PAGE, "BT-1 or x")


def test_visualizer_without_url_is_unavailable() -> None:
    with pytest.raises(VisualizationUnavailable, match="not configured"):
        Visualizer(None, 1.0).render("sha", b"<x/>", "de")


class FakeRenderer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes, Language]] = []
        self.unavailable = False

    def render(self, sha256: str, xml: bytes, language: Language) -> str:
        self.calls.append((sha256, xml, language))
        if self.unavailable:
            raise VisualizationUnavailable("The XRechnung visualization is not reachable.")
        return VIEWER_PAGE


@pytest.fixture
def renderer(client: TestClient) -> FakeRenderer:
    fake = FakeRenderer()
    client.app.state.visualizer = fake  # type: ignore[attr-defined]
    return fake


def _upload(client: TestClient, name: str, content: bytes, media_type: str) -> dict[str, Any]:
    response = client.post("/invoices", files={"file": (name, content, media_type)})
    assert response.status_code == 202, response.text
    return poll_until_done(client, response.headers["location"])


def test_view_of_an_xml_invoice_is_static_html_under_a_sandbox_csp(
    client: TestClient, renderer: FakeRenderer, samples: dict[str, bytes]
) -> None:
    detail = _upload(client, "rechnung.xml", samples["ubl_xrechnung"], "application/xml")
    response = client.get(f"/invoices/{detail['id']}/view?lang=en&highlight=BT-84")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    csp = response.headers["content-security-policy"]
    assert "default-src 'none'" in csp and csp.endswith("sandbox")
    assert "script-src" not in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    assert _page(response.text).get_element_by_id(HIGHLIGHT_ID).text == "DE60 1234"
    ((sha256, xml, language),) = renderer.calls
    assert (sha256, xml, language) == (detail["sha256"], samples["ubl_xrechnung"], "en")


def test_view_of_a_zugferd_pdf_renders_its_embedded_xml(
    client: TestClient, renderer: FakeRenderer, samples: dict[str, bytes]
) -> None:
    pdf = samples["zugferd2_pdf"]
    detail = _upload(client, "zugferd.pdf", pdf, "application/pdf")
    assert client.get(f"/invoices/{detail['id']}/view").status_code == 200
    ((_, xml, language),) = renderer.calls
    assert b"CrossIndustryInvoice" in xml and language == "de"


def test_view_refuses_bad_parameters_and_reports_an_unavailable_service(
    client: TestClient, renderer: FakeRenderer, samples: dict[str, bytes]
) -> None:
    detail = _upload(client, "rechnung.xml", samples["ubl_xrechnung"], "application/xml")
    url = f"/invoices/{detail['id']}/view"
    assert client.get(f"{url}?lang=ar").status_code == 422
    assert client.get(f"{url}?highlight=BT-1%27%5D").status_code == 422
    assert client.get(f"{url}?highlight=BT-153&line=0").status_code == 422
    renderer.unavailable = True
    response = client.get(url)
    assert response.status_code == 503
    assert "not reachable" in response.json()["detail"]


def test_view_needs_xml_a_known_invoice_and_a_login(
    client: TestClient, renderer: FakeRenderer, samples: dict[str, bytes]
) -> None:
    plain = client.post(
        "/invoices", files={"file": ("plain.pdf", samples["text_pdf"], "application/pdf")}
    )
    assert plain.status_code == 202, plain.text
    response = client.get(f"/invoices/{plain.json()['id']}/view")
    assert response.status_code == 404
    assert response.json()["detail"] == "This invoice has no e-invoice XML."
    assert client.get(f"/invoices/{uuid.uuid4()}/view").status_code == 404
    client.cookies.clear()
    assert client.get(f"/invoices/{uuid.uuid4()}/view").status_code == 401
    assert renderer.calls == []


@pytest.fixture
def live_url() -> str:
    url = os.environ.get(VISUALIZATION_URL_ENV)
    if not url:
        pytest.skip(f"{VISUALIZATION_URL_ENV} is not set")
    return url


@pytest.mark.kosit
@pytest.mark.parametrize("fixture", ["ubl_xrechnung", "cii_xrechnung"])
def test_real_visualization_marks_the_iban_row(
    live_url: str, samples: dict[str, bytes], fixture: str
) -> None:
    page = Visualizer(live_url, 10.0).render(fixture, samples[fixture], "de")
    static = _page(make_static(page, "BT-84"))
    marked = static.get_element_by_id(HIGHLIGHT_ID)
    assert "BT-84" in marked.get("class").split()
    assert marked.text_content().replace(" ", "").startswith("DE")
    assert static.xpath("//script") == []


@pytest.mark.kosit
def test_real_visualization_refuses_what_is_no_invoice(
    live_url: str, samples: dict[str, bytes]
) -> None:
    visualizer = Visualizer(live_url, 10.0)
    with pytest.raises(VisualizationUnavailable, match="HTTP 415"):
        visualizer.render("z1", samples["zugferd1"], "de")
    with pytest.raises(VisualizationUnavailable, match="HTTP 422"):
        visualizer.render("xxe", samples["xxe"], "de")

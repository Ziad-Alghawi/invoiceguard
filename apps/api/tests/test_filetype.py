import pytest

from invoiceguard_api.filetype import detect_source_type, safe_filename, source_type_for
from invoiceguard_api.models import SourceType


@pytest.mark.parametrize(
    "content",
    [
        b'<?xml version="1.0" encoding="UTF-8"?><Invoice/>',
        b"\xef\xbb\xbf<?xml version='1.0'?><Invoice/>",
        b"\n  <rsm:CrossIndustryInvoice xmlns:rsm='urn:x'>",
        b"<Invoice>",
    ],
)
def test_xml_is_detected(content: bytes) -> None:
    assert detect_source_type(content) is SourceType.XML


def test_pdf_is_detected() -> None:
    assert detect_source_type(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n") is SourceType.PDF


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"hello, invoice",
        b"MZ\x90\x00",  # Windows executable
        b"PK\x03\x04",  # zip / docx
        b"<!DOCTYPE html><html>",
        b"<!-- comment --><Invoice/>",
        b"<?xmlfoo?>",
        b" %PDF-1.7",  # PDF marker must be at the very start
    ],
)
def test_other_content_is_rejected(content: bytes) -> None:
    assert detect_source_type(content) is None


@pytest.mark.parametrize(
    ("filename", "content", "expected"),
    [
        ("rechnung.xml", b"<Invoice/>", SourceType.XML),
        ("RECHNUNG.PDF", b"%PDF-1.4", SourceType.PDF),
        ("rechnung.pdf", b"<Invoice/>", None),
        ("rechnung.xml", b"%PDF-1.4", None),
        ("rechnung.txt", b"<Invoice/>", None),
        ("rechnung", b"%PDF-1.4", None),
    ],
)
def test_extension_and_content_must_agree(
    filename: str, content: bytes, expected: SourceType | None
) -> None:
    assert source_type_for(filename, content) is expected


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("rechnung.xml", "rechnung.xml"),
        ("../../etc/passwd.xml", "passwd.xml"),
        ("C:\\Users\\x\\rechnung.pdf", "rechnung.pdf"),
        ("a" * 300 + ".pdf", "a" * 255),
        ("", ""),
    ],
)
def test_safe_filename_keeps_only_the_base_name(filename: str, expected: str) -> None:
    assert safe_filename(filename) == expected

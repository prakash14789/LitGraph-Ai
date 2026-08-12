"""Unit tests for src.services.ingestion.pdf_parser.

Uses a small synthetic PDF (built with fitz itself) rather than committing
real papers — deterministic, no network dependency, no copyright question.
The heuristics were separately verified against two real arXiv papers
(Attention Is All You Need, BERT) during development; see INGEST-001 commit
message for what that caught and fixed.
"""

import fitz
import pytest

from src.services.ingestion.pdf_parser import parse_pdf


@pytest.fixture
def synthetic_pdf(tmp_path):
    path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    y = 50
    for text, size, step in [
        ("A Test Paper About Widgets", 18, 30),
        ("Jane Doe, John Smith", 11, 40),
        ("Abstract", 13, 20),
        ("This paper is about widgets and their uses.", 10, 30),
        ("Introduction", 13, 20),
        ("Widgets have been studied for decades.", 10, 30),
        ("Method", 13, 20),
        ("We built a new widget.", 10, 30),
        ("References", 13, 20),
        ("[1] Doe, J. Widget theory. 2020.", 10, 15),
        ("[2] Smith, J. Widget practice. 2021.", 10, 15),
    ]:
        page.insert_text((72, y), text, fontsize=size)
        y += step
    doc.save(str(path))
    doc.close()
    return str(path)


def test_extracts_title(synthetic_pdf):
    result = parse_pdf(synthetic_pdf)
    assert result.ok
    assert result.title == "A Test Paper About Widgets"


def test_finds_sections(synthetic_pdf):
    result = parse_pdf(synthetic_pdf)
    assert {"abstract", "introduction", "method", "references"} <= result.sections.keys()
    assert "widgets" in result.sections["introduction"].lower()


def test_splits_numbered_references(synthetic_pdf):
    result = parse_pdf(synthetic_pdf)
    assert len(result.references) == 2
    assert "Widget theory" in result.references[0]


def test_nonexistent_file_fails_gracefully():
    result = parse_pdf("Z:/definitely/does/not/exist.pdf")
    assert not result.ok
    assert result.error is not None


def test_corrupt_file_fails_gracefully(tmp_path):
    path = tmp_path / "not_a_pdf.pdf"
    path.write_text("this is just text, not a pdf")
    result = parse_pdf(str(path))
    assert not result.ok
    assert result.error is not None

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


@pytest.fixture
def multi_author_pdf(tmp_path):
    # FIX-2: byline wraps across several lines, as real multi-author papers
    # (GPT-3-style bylines) do — a single-line capture used to keep only
    # "Jane Doe" and silently drop everyone after the first line break.
    path = tmp_path / "multi_author.pdf"
    doc = fitz.open()
    page = doc.new_page()
    y = 50
    for text, size, step in [
        ("A Paper With Many Authors", 18, 30),
        ("Jane Doe, John Smith,", 11, 20),
        ("Alice Lee, Bob Chen", 11, 40),
        ("Abstract", 13, 20),
        ("This paper has many authors.", 10, 30),
    ]:
        page.insert_text((72, y), text, fontsize=size)
        y += step
    doc.save(str(path))
    doc.close()
    return str(path)


def test_extracts_authors_across_multiple_lines(multi_author_pdf):
    result = parse_pdf(multi_author_pdf)
    assert result.ok
    assert result.authors == ["Jane Doe", "John Smith", "Alice Lee", "Bob Chen"]


@pytest.fixture
def comma_less_author_pdf(tmp_path):
    # Live finding: BERT's real PDF byline has no comma/"and" separator at
    # all — one run-on line of names.
    path = tmp_path / "comma_less.pdf"
    doc = fitz.open()
    page = doc.new_page()
    y = 50
    for text, size, step in [
        ("A Paper With A Comma-Less Byline", 18, 30),
        ("Jacob Devlin Ming-Wei Chang Kenton Lee Kristina Toutanova", 11, 30),
        ("Abstract", 13, 20),
        ("This paper has a fused byline.", 10, 30),
    ]:
        page.insert_text((72, y), text, fontsize=size)
        y += step
    doc.save(str(path))
    doc.close()
    return str(path)


def test_splits_comma_less_byline_into_separate_authors(comma_less_author_pdf):
    result = parse_pdf(comma_less_author_pdf)
    assert result.ok
    assert result.authors == ["Jacob Devlin", "Ming-Wei Chang", "Kenton Lee", "Kristina Toutanova"]


@pytest.fixture
def affiliation_line_author_pdf(tmp_path):
    # FIX-A live finding: the line right after the byline is often an
    # affiliation + shared-email block ("Google Brain avaswani@google.com",
    # "{jacobdevlin,mingweichang}@google.com"), which used to get swept into
    # the author list since it isn't a symbol/number-only "noise" line.
    path = tmp_path / "affiliation.pdf"
    doc = fitz.open()
    page = doc.new_page()
    y = 50
    for text, size, step in [
        ("A Paper With An Affiliation Line", 18, 30),
        ("Ashish Vaswani, Noam Shazeer", 11, 20),
        ("Google Brain avaswani@google.com", 10, 30),
        ("Abstract", 13, 20),
        ("This paper has an affiliation line right after the byline.", 10, 30),
    ]:
        page.insert_text((72, y), text, fontsize=size)
        y += step
    doc.save(str(path))
    doc.close()
    return str(path)


def test_excludes_affiliation_and_email_line_from_authors(affiliation_line_author_pdf):
    result = parse_pdf(affiliation_line_author_pdf)
    assert result.ok
    assert result.authors == ["Ashish Vaswani", "Noam Shazeer"]


@pytest.fixture
def per_author_block_pdf(tmp_path):
    # EVAL-002 live finding: ELECTRA's real PDF interleaves one line per
    # author (name, that author's own affiliation, their email) instead of
    # one name-block followed by a noise block at the end — stopping at the
    # first noise line used to keep only the very first author.
    path = tmp_path / "per_author_block.pdf"
    doc = fitz.open()
    page = doc.new_page()
    y = 50
    for text, size, step in [
        ("A Paper With Per-Author Blocks", 18, 30),
        ("Kevin Clark", 11, 15),
        ("Stanford University", 10, 15),
        ("kevclark@cs.stanford.edu", 10, 15),
        ("Minh-Thang Luong", 11, 15),
        ("Google Brain", 10, 15),
        ("thangluong@google.com", 10, 20),
        ("Abstract", 13, 20),
        ("This paper interleaves author blocks.", 10, 30),
    ]:
        page.insert_text((72, y), text, fontsize=size)
        y += step
    doc.save(str(path))
    doc.close()
    return str(path)


def test_collects_authors_from_interleaved_per_author_blocks(per_author_block_pdf):
    result = parse_pdf(per_author_block_pdf)
    assert result.ok
    assert result.authors == ["Kevin Clark", "Minh-Thang Luong"]


@pytest.fixture
def many_authors_with_footnotes_pdf(tmp_path):
    # EVAL-002 live finding: RoBERTa's real PDF has 10 authors, one per
    # line, each with a footnote marker glued directly to the name (no
    # space) — the old 4-line author cap silently truncated to 4 authors
    # before ever reaching the affiliation block.
    path = tmp_path / "many_authors.pdf"
    doc = fitz.open()
    page = doc.new_page()
    y = 50
    for text, size, step in [
        ("A Paper With Many Footnoted Authors", 18, 30),
        ("Yinhan Liu*§", 11, 15),
        ("Myle Ott*§", 11, 15),
        ("Naman Goyal*§", 11, 15),
        ("Jingfei Du*§", 11, 15),
        ("Mandar Joshi*", 11, 15),
        ("Danqi Chen*", 11, 20),
        ("Abstract", 13, 20),
        ("This paper has many footnoted authors.", 10, 30),
    ]:
        page.insert_text((72, y), text, fontsize=size)
        y += step
    doc.save(str(path))
    doc.close()
    return str(path)


def test_collects_all_authors_past_old_four_line_cap_and_strips_footnotes(
    many_authors_with_footnotes_pdf,
):
    result = parse_pdf(many_authors_with_footnotes_pdf)
    assert result.ok
    assert result.authors == [
        "Yinhan Liu",
        "Myle Ott",
        "Naman Goyal",
        "Jingfei Du",
        "Mandar Joshi",
        "Danqi Chen",
    ]


@pytest.fixture
def marker_prefixed_affiliation_pdf(tmp_path):
    # EVAL-002 live finding: RoBERTa's real PDF has footnote-marker-prefixed
    # affiliation lines ("† Paul G. Allen School of...", "§ Facebook AI")
    # naming institutions not in _NOISE_LINE_RE's hardcoded keyword list —
    # these leaked into the author list as if they were names.
    path = tmp_path / "marker_affiliation.pdf"
    doc = fitz.open()
    page = doc.new_page()
    y = 50
    for text, size, step in [
        ("A Paper With Marker-Prefixed Affiliations", 18, 30),
        ("Yinhan Liu*§", 11, 15),
        ("Myle Ott*§", 11, 15),
        ("* Paul G. Allen School of Computer Science", 10, 15),
        ("* Facebook AI", 10, 20),
        ("Abstract", 13, 20),
        ("This paper has marker-prefixed affiliations.", 10, 30),
    ]:
        page.insert_text((72, y), text, fontsize=size)
        y += step
    doc.save(str(path))
    doc.close()
    return str(path)


def test_excludes_marker_prefixed_affiliation_lines_from_authors(marker_prefixed_affiliation_pdf):
    result = parse_pdf(marker_prefixed_affiliation_pdf)
    assert result.ok
    assert result.authors == ["Yinhan Liu", "Myle Ott"]


@pytest.fixture
def wrapped_email_block_pdf(tmp_path):
    # EVAL-002 live finding: RoBERTa's real PDF has a shared curly-brace
    # email block that itself wraps across two lines
    # ("{yinhanliu,myleott,naman,jingfeidu," / "danqi,...}@fb.com") — only
    # the second line has the "}"+"@" the old noise pattern needed, so the
    # first line's comma-separated fragments leaked in as "authors".
    path = tmp_path / "wrapped_email.pdf"
    doc = fitz.open()
    page = doc.new_page()
    y = 50
    for text, size, step in [
        ("A Paper With A Wrapped Email Block", 18, 30),
        ("Yinhan Liu*", 11, 15),
        ("Myle Ott*", 11, 20),
        ("{yinhanliu,myleott,", 10, 15),
        ("naman,jingfeidu}@fb.com", 10, 20),
        ("Abstract", 13, 20),
        ("This paper has a wrapped email block.", 10, 30),
    ]:
        page.insert_text((72, y), text, fontsize=size)
        y += step
    doc.save(str(path))
    doc.close()
    return str(path)


def test_excludes_email_block_wrapped_across_two_lines_from_authors(wrapped_email_block_pdf):
    result = parse_pdf(wrapped_email_block_pdf)
    assert result.ok
    assert result.authors == ["Yinhan Liu", "Myle Ott"]


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

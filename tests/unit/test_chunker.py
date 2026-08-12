"""Unit tests for src.services.ingestion.chunker.

Uses hand-built ParsedPaper objects (no PDF needed — chunker only cares
about already-parsed sections/pages/tables). Heuristics were separately
verified live against two real arXiv papers during development; see
INGEST-002 commit message for what that caught and fixed.
"""

import pytest

from src.services.ingestion import chunker
from src.services.ingestion.chunker import _ENCODING, chunk_paper
from src.services.ingestion.pdf_parser import ParsedPaper, ParsedTable


def _paper(
    sections: dict[str, str], pages: list[str], tables: list[ParsedTable] | None = None
) -> ParsedPaper:
    return ParsedPaper(
        full_text="\n".join(pages),
        pages=pages,
        sections=sections,
        references=[],
        title="Test Paper",
        authors=None,
        tables=tables or [],
    )


@pytest.fixture
def small_limits(monkeypatch):
    """Tiny token budget so a handful of sentences is enough to force
    multiple chunks, without needing a huge test fixture."""
    monkeypatch.setattr(chunker.settings, "chunk_size_tokens", 30)
    monkeypatch.setattr(chunker.settings, "chunk_overlap_tokens", 10)


def test_no_chunk_exceeds_size_limit(small_limits):
    sentence = "Widgets are studied extensively across many different scientific disciplines today."
    section_text = " ".join([sentence] * 6)
    paper = _paper({"introduction": section_text}, pages=[section_text])

    chunks = chunk_paper(paper, paper_id="p1")

    for c in chunks:
        assert len(_ENCODING.encode(c.text)) <= chunker.settings.chunk_size_tokens + 50


def test_no_mid_sentence_split(small_limits):
    sentences = [
        "Widgets are useful.",
        "Gadgets are also useful.",
        "Both have been studied for decades by many researchers worldwide.",
        "Future work should compare them directly in controlled experiments.",
    ]
    section_text = " ".join(sentences)
    paper = _paper({"introduction": section_text}, pages=[section_text])

    chunks = chunk_paper(paper, paper_id="p1")

    for c in chunks:
        assert c.text.rstrip()[-1] in ".!?"
        assert c.text.lstrip()[0].isupper() or c.text.lstrip()[0].isdigit()


def test_section_metadata_preserved(small_limits):
    paper = _paper(
        {"introduction": "Widgets are useful. They come in many shapes."},
        pages=["Widgets are useful. They come in many shapes."],
    )

    chunks = chunk_paper(paper, paper_id="paper-42")

    assert all(c.paper_id == "paper-42" for c in chunks)
    assert all(c.section_name == "introduction" for c in chunks)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_all_sentences_represented(small_limits):
    sentences = [
        "Widgets are useful.",
        "Gadgets are also useful.",
        "Both have been studied for decades by many researchers worldwide.",
        "Future work should compare them directly in controlled experiments.",
    ]
    section_text = " ".join(sentences)
    paper = _paper({"introduction": section_text}, pages=[section_text])

    chunks = chunk_paper(paper, paper_id="p1")

    joined = " ".join(c.text for c in chunks)
    for sentence in sentences:
        assert sentence in joined


def test_consecutive_chunks_overlap(small_limits):
    # Distinct sentences (not repeated) so we can tell *which* sentence
    # actually carried across the boundary, not just that text matches.
    sentences = [
        "Widgets were first studied in the early twentieth century by pioneers.",
        "Gadgets emerged as a distinct research area somewhat later on.",
        "Doohickeys remain the least understood of the three categories.",
        "Thingamajigs are a relatively recent addition to the taxonomy.",
        "Whatchamacallits defy every attempt at rigorous classification.",
        "Contraptions tie all of these categories together conceptually.",
    ]
    section_text = " ".join(sentences)
    paper = _paper({"introduction": section_text}, pages=[section_text])

    chunks = [c for c in chunk_paper(paper, paper_id="p1") if c.section_name == "introduction"]
    assert len(chunks) > 1
    # Every chunk after the first should share at least one sentence with
    # the end of the previous chunk (the carried overlap).
    for prev, cur in zip(chunks, chunks[1:]):
        prev_sentences = {s for s in sentences if s in prev.text}
        cur_sentences = {s for s in sentences if s in cur.text}
        assert prev_sentences & cur_sentences, (prev.text, cur.text)


def test_tables_become_separate_chunks():
    table = ParsedTable(page_number=3, markdown="|A|B|\n|--|--|\n|1|2|")
    paper = _paper({}, pages=["page one text"], tables=[table])

    chunks = chunk_paper(paper, paper_id="p1")

    assert len(chunks) == 1
    assert chunks[0].section_name == "table"
    assert chunks[0].page_number == 3
    assert chunks[0].text == table.markdown


def test_page_number_resolved_from_section_text():
    pages = [
        "Page one has the introduction text right here.",
        "Page two has the conclusion text right here.",
    ]
    paper = _paper(
        {"introduction": pages[0], "conclusion": pages[1]},
        pages=pages,
    )

    chunks = chunk_paper(paper, paper_id="p1")

    intro_chunk = next(c for c in chunks if c.section_name == "introduction")
    conclusion_chunk = next(c for c in chunks if c.section_name == "conclusion")
    assert intro_chunk.page_number == 1
    assert conclusion_chunk.page_number == 2

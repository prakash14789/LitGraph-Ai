"""Parsed paper sections -> overlapping, token-bounded chunks with metadata.

Splits by section first, then packs sentences greedily up to
CHUNK_SIZE_TOKENS with a CHUNK_OVERLAP_TOKENS sentence-level overlap between
consecutive chunks. Tables from the parser become their own single-chunk
entries tagged section="table" (not further split — academic tables rarely
exceed the token cap; if one ever does, that's a known edge case, not a
crash).
"""

import bisect
import re
from dataclasses import dataclass

import tiktoken

from src.config import settings
from src.services.ingestion.pdf_parser import ParsedPaper

_ENCODING = tiktoken.get_encoding("cl100k_base")
# ponytail: naive sentence splitter — misses "Fig. 3" / "et al." style
# abbreviations (splits when it shouldn't) and never merges them back. Good
# enough for chunk boundaries (a slightly-off split doesn't lose content);
# a real sentence tokenizer (nltk/spacy) is the upgrade if this ever matters.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


@dataclass
class Chunk:
    text: str
    paper_id: str
    section_name: str
    chunk_index: int
    page_number: int | None


def chunk_paper(parsed: ParsedPaper, paper_id: str) -> list[Chunk]:
    page_index = _PageIndex(parsed.pages)
    chunks: list[Chunk] = []

    for section_name, text in parsed.sections.items():
        for piece in _split_section(text):
            chunks.append(
                Chunk(
                    text=piece,
                    paper_id=paper_id,
                    section_name=section_name,
                    chunk_index=len(chunks),
                    page_number=page_index.locate(piece),
                )
            )

    for table in parsed.tables:
        # Real page number from PyMuPDF, not a text-search guess — a table's
        # markdown is synthesized, not verbatim page text, so it could never
        # be located via page_index.locate() anyway.
        chunks.append(
            Chunk(
                text=table.markdown,
                paper_id=paper_id,
                section_name="table",
                chunk_index=len(chunks),
                page_number=table.page_number,
            )
        )

    return chunks


def _split_section(text: str) -> list[str]:
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]
    if not sentences:
        return []

    size = settings.chunk_size_tokens
    overlap = settings.chunk_overlap_tokens

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    i = 0

    while i < len(sentences):
        sentence = sentences[i]
        sentence_tokens = len(_ENCODING.encode(sentence))

        if sentence_tokens > size:
            # A single sentence longer than the whole chunk budget (dense
            # equations, long author lists) can't honor "don't split
            # mid-sentence" — hard-split by token as the only option left.
            if current:
                chunks.append(" ".join(current))
                current, current_tokens = [], 0
            chunks.extend(_hard_split(sentence, size))
            i += 1
            continue

        if current_tokens + sentence_tokens > size:
            chunks.append(" ".join(current))
            carried, carried_tokens = _carry_overlap(current, overlap)
            if carried_tokens + sentence_tokens > size:
                # The overlap itself is too big to fit alongside the next
                # sentence — drop it rather than loop forever chasing it.
                carried, carried_tokens = [], 0
            current, current_tokens = carried, carried_tokens
            continue  # re-check this same sentence against the new state

        current.append(sentence)
        current_tokens += sentence_tokens
        i += 1

    if current:
        chunks.append(" ".join(current))

    return chunks


def _carry_overlap(sentences: list[str], overlap_tokens: int) -> tuple[list[str], int]:
    """Trailing sentences worth ~overlap_tokens, to seed the next chunk."""
    carried: list[str] = []
    total = 0
    for sentence in reversed(sentences):
        tokens = len(_ENCODING.encode(sentence))
        if total + tokens > overlap_tokens and carried:
            break
        carried.insert(0, sentence)
        total += tokens
    return carried, total


def _hard_split(sentence: str, size: int) -> list[str]:
    tokens = _ENCODING.encode(sentence)
    return [_ENCODING.decode(tokens[i : i + size]) for i in range(0, len(tokens), size)]


class _PageIndex:
    """Maps a chunk's text back to an approximate page number by searching
    for it in the paper's raw per-page text. Both sides are whitespace-
    normalized before comparing — chunking rejoins sentences with plain
    spaces, so a chunk's text often has a " " exactly where the original
    page text had a "\\n" (mid-sentence PDF line wrap); comparing raw would
    miss those. Best-effort — the located page is rarely off by more than
    one, never exact to the character."""

    def __init__(self, pages: list[str]):
        normalized_pages = [_normalize_ws(page) for page in pages]
        self._full_text = " ".join(normalized_pages)
        self._boundaries: list[int] = []
        offset = 0
        for page in normalized_pages:
            offset += len(page) + 1  # +1 for the joining " "
            self._boundaries.append(offset)

    def locate(self, text: str) -> int | None:
        snippet = _normalize_ws(text)[:40]
        if not snippet:
            return None
        pos = self._full_text.find(snippet)
        if pos == -1:
            return None
        return bisect.bisect_right(self._boundaries, pos) + 1  # 1-indexed


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

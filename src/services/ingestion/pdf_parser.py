"""PDF -> structured paper data. PyMuPDF (fitz) does the heavy lifting —
text extraction already normalizes single-column/two-column/LaTeX layouts
into reading order, so section detection is just a header-line heuristic
(matches known academic section names) rather than font/layout analysis.
"""

import re
from dataclasses import dataclass

import fitz  # PyMuPDF

_SECTION_HEADERS = [
    "abstract",
    "introduction",
    "related work",
    "background",
    "method",
    "methods",
    "methodology",
    "approach",
    "model architecture",
    "architecture",
    "proposed method",
    "system description",
    "training",
    "experiments",
    "experimental setup",
    "evaluation",
    "results",
    "discussion",
    "conclusion",
    "conclusions",
    "future work",
    "limitations",
    "acknowledgments",
    "acknowledgements",
    "references",
    "appendix",
]
# A standalone line that IS a header: optional numbering ("3.2", "IV."),
# then one of the known header phrases, nothing else on the line.
_HEADER_RE = re.compile(
    r"^\s*(?:[\divxIVX]+[.\)]\s*)*(" + "|".join(_SECTION_HEADERS) + r")\s*$",
    re.IGNORECASE,
)
_NUMBERED_REF_RE = re.compile(r"\n(?=\[?\d{1,3}\]?[.\s])")
# Fallback for name-year style refs (no leading number): split before a line
# that looks like it starts a new "Author(s). YEAR." citation. Imperfect —
# long multi-author bylines can still split mid-list — but far better than
# leaving the whole references section as one blob. Ceiling: proper
# reference parsing is what GROBID exists for (see architecture doc §—
# considered, not implemented, too heavy for this project).
_NAME_YEAR_REF_RE = re.compile(
    r"\n(?=[A-Z][\w\-À-ÿ]*[.,]?\s[^\n]{0,120}?(?:19|20)\d{2}\.)", re.DOTALL
)


@dataclass
class ParsedTable:
    page_number: int  # 1-indexed
    markdown: str


@dataclass
class ParsedPaper:
    full_text: str
    pages: list[str]  # raw per-page text — INGEST-002 needs this for page_number metadata
    sections: dict[str, str]
    references: list[str]
    title: str | None
    authors: list[str] | None
    tables: list[ParsedTable]
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def parse_pdf(path: str) -> ParsedPaper:
    """Never raises — a parse failure comes back as ParsedPaper(error=...)."""
    try:
        doc = fitz.open(path)
    except Exception as exc:
        return _failed(f"could not open PDF: {exc}")

    try:
        pages = [page.get_text() for page in doc]
        full_text = "\n".join(pages)
        sections = _split_sections(full_text)
        references = _extract_references(sections.get("references", ""))
        title, authors = _extract_metadata(doc)
        tables = _extract_tables(doc)
    except Exception as exc:
        return _failed(f"could not parse PDF content: {exc}")
    finally:
        doc.close()

    return ParsedPaper(
        full_text=full_text,
        pages=pages,
        sections=sections,
        references=references,
        title=title,
        authors=authors,
        tables=tables,
    )


def _failed(message: str) -> ParsedPaper:
    return ParsedPaper(
        full_text="",
        pages=[],
        sections={},
        references=[],
        title=None,
        authors=None,
        tables=[],
        error=message,
    )


def _split_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {"preamble": []}  # title/authors/abstract before first header
    current = "preamble"
    for line in text.splitlines():
        match = _HEADER_RE.match(line)
        if match:
            current = match.group(1).lower()
            sections.setdefault(current, [])
            continue
        sections[current].append(line)

    result = {name: "\n".join(body).strip() for name, body in sections.items()}
    result = {name: body for name, body in result.items() if body}

    # ponytail: naive header-line matching — misses headers PyMuPDF splits
    # across spans, non-English section names, or unconventional naming.
    # Fallback: whole paper as one section rather than pretend we found structure.
    if len(result) <= 1:
        return {"full_text": text}
    return result


def _extract_references(references_section: str) -> list[str]:
    if not references_section:
        return []
    # Try both styles, keep whichever actually segmented (more pieces == it
    # found real boundaries; a false-positive single match on the wrong
    # style still leaves one giant piece, which the other style beats).
    numbered = _clean_ref_entries(_NUMBERED_REF_RE.split(references_section))
    name_year = _clean_ref_entries(_NAME_YEAR_REF_RE.split(references_section))
    return numbered if len(numbered) >= len(name_year) else name_year


def _clean_ref_entries(entries: list[str]) -> list[str]:
    return [e.strip().replace("\n", " ") for e in entries if e.strip()]


def _extract_metadata(doc: fitz.Document) -> tuple[str | None, list[str] | None]:
    """Best-effort only (per ticket: 'authors if detectable') — title is the
    largest text span on page 1; authors is whatever non-blank line follows
    it before "abstract". No name parsing, just raw candidate strings."""
    if doc.page_count == 0:
        return None, None
    first_page = doc[0]
    # Horizontal lines only — arXiv (and similar) PDFs stamp a rotated
    # "arXiv:xxxx.xxxxx [cs.XX] date" watermark down the page edge that's
    # often the single largest font on the page, out-sizing the real title.
    lines = [
        {"size": max((s["size"] for s in line["spans"]), default=0.0), "text": text}
        for block in first_page.get_text("dict")["blocks"]
        for line in block.get("lines", [])
        if line.get("dir", (1, 0))[1] == 0
        and (text := "".join(s["text"] for s in line["spans"]).strip())
    ]
    if not lines:
        return None, None

    max_size = max(line["size"] for line in lines)
    start = next(i for i, line in enumerate(lines) if line["size"] >= max_size - 0.5)

    # Titles often wrap across 2+ lines at the same font size — merge the
    # whole contiguous run, not just the first line, or a two-line title
    # loses its second half (and the second half gets mistaken for authors).
    title_lines = []
    for line in lines[start:]:
        if line["size"] < max_size - 0.5:
            break
        title_lines.append(line["text"])
    title = " ".join(title_lines).strip() or None

    authors = None
    if title:
        for line in lines[start + len(title_lines) :]:
            if line["text"] and "abstract" not in line["text"].lower():
                authors = [a.strip() for a in re.split(r",| and ", line["text"]) if a.strip()]
                break
    return title, authors


def _extract_tables(doc: fitz.Document) -> list[ParsedTable]:
    tables = []
    for page in doc:
        try:
            found = page.find_tables()
        except Exception:
            continue  # older PyMuPDF without table support — skip, don't crash
        for table in found.tables:
            try:
                tables.append(
                    ParsedTable(page_number=page.number + 1, markdown=table.to_markdown())
                )
            except Exception:
                continue
    return tables

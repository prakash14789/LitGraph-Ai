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
# Byline noise: a line that isn't itself an author name — footnote/symbol-
# only markers, an email address (bare or the "{a,b,c}@domain" shared-
# institutional style), or an affiliation/institution line. Live finding:
# these sit right after the real author names on several real papers
# (Attention Is All You Need, T5, XLNet, DistilBERT) and were getting
# swept into the author list by the multi-line collector below.
_NOISE_LINE_RE = re.compile(
    r"^[†‡∗\*\d\s,]*$"
    r"|^\{.*\}.*@.*\..*$"
    # A curly-brace shared-email block ("{yinhanliu,myleott,...}@fb.com")
    # can itself wrap across two lines — the alternative above only matches
    # when the closing "}" and "@" are on the same line. A real author name
    # never starts with a literal "{", so any line opening with one is
    # noise regardless of whether it's self-contained on this line.
    r"|^\{"
    r"|.*@[\w.-]+\.\w+.*$"
    r"|^\s*(university|department|institute|lab|google|microsoft|stanford|mit)\b"
    # A line that STARTS with a footnote marker followed by real text is an
    # affiliation footnote ("† Paul G. Allen School of...", "§ Facebook
    # AI") regardless of which institution it names — RoBERTa's real PDF
    # live finding: the keyword list above only knows a handful of
    # institutions by name and missed these. An author's own trailing
    # marker ("Yinhan Liu∗§") is a suffix, not a line-leading prefix, so
    # this can't mistake a real name line for noise.
    r"|^[†‡∗\*§]+\s+\S",
    re.IGNORECASE,
)
# Bumped from the original 4 (EVAL-002 live finding, ELECTRA's real PDF):
# that cap counted genuine author-name lines, but a per-author-block byline
# (name/affiliation/email repeated per author, see _extract_metadata) needs
# one slot per author, not per whole-byline chunk — 4 was silently truncating
# any paper with more than 4 authors laid out that way.
_MAX_AUTHOR_LINES = 12
# Safety cap on total lines scanned hunting for authors before "abstract" —
# guards against a runaway scan if a PDF never has "abstract" on its own
# line (noise lines are skipped, not a stop condition, so without this the
# loop would otherwise only be bounded by the page's line count).
_MAX_PREAMBLE_SCAN_LINES = 40
# Footnote/affiliation markers stuck directly against a name with no space
# (e.g. "Yinhan Liu∗§", RoBERTa's real PDF) — trailing only, so a genuine
# name character is never eaten.
_FOOTNOTE_MARKER_RE = re.compile(r"[†‡∗\*§]+$")


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
        # EVAL-001 live finding: PyMuPDF occasionally extracts a NUL byte
        # (0x00) from certain PDFs (malformed/embedded font content) —
        # ELECTRA's real arXiv PDF hit this. Postgres's UTF8 text columns
        # reject NUL outright, and that failure then cascaded into a 2nd
        # failure inside the pipeline's own error handling (see
        # pipeline.py), orphaning the job. Stripped once, at the source,
        # so every downstream consumer (DB, chunker, embeddings) never
        # sees it — cheaper than requiring every writer to remember to
        # sanitize.
        pages = [page.get_text().replace("\x00", "") for page in doc]
        full_text = "\n".join(pages)
        sections = _split_sections(full_text)
        references = _extract_references(sections.get("references", ""))
        title, authors = _extract_metadata(doc)
        title = title.replace("\x00", "") if title else title
        authors = [a.replace("\x00", "") for a in authors] if authors else authors
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

    # Multi-line byline collection: a single line was capturing only the
    # first author on multi-column/wrapped bylines (GPT-3-style 30+ author
    # lists). Keep collecting non-blank, non-noise lines until "abstract" or
    # a scan-length safety cap — whichever comes first. A noise line
    # (affiliation/email/footnote) is *skipped*, not a stop condition: live
    # finding (ELECTRA's real PDF) — some bylines interleave one line per
    # author (name, then that author's own affiliation, then their email,
    # repeated), not one name-block followed by a noise block at the end.
    # Stopping at the first noise line there only ever captured the first
    # author. Skipping past noise instead correctly reaches every author's
    # name line in both layouts; _MAX_PREAMBLE_SCAN_LINES bounds how far
    # this can run if "abstract" is never found on its own line.
    authors = None
    if title:
        author_lines = []
        scanned = 0
        for line in lines[start + len(title_lines) :]:
            text = line["text"]
            if not text:
                continue
            low = text.lower()
            if "abstract" in low:
                break
            scanned += 1
            if scanned > _MAX_PREAMBLE_SCAN_LINES:
                break
            if _NOISE_LINE_RE.match(text) or len(text) > 200:
                continue
            author_lines.append(text)
            if len(author_lines) >= _MAX_AUTHOR_LINES:
                break
        if author_lines:
            # Split per line, not on the lines joined together — a
            # per-author-block layout has already isolated one name per
            # line by the time noise is filtered out above, and joining
            # first would glue those names together with no delimiter left
            # to split back on. A line that itself lists several
            # comma-separated names (the older shared-byline layout) still
            # splits correctly since the split happens on that line alone.
            authors = []
            for line_text in author_lines:
                authors.extend(a.strip() for a in re.split(r",| and ", line_text) if a.strip())
            # Live finding (BERT's real PDF): some bylines have no comma/
            # "and" separator at all ("Jacob Devlin Ming-Wei Chang Kenton
            # Lee Kristina Toutanova" as one run-on line) — the split above
            # then yields a single oversized "name". Only kick in when that
            # happened (len == 1) and it's implausibly long for one person's
            # name, so a genuine short comma-less byline is left alone.
            if len(authors) == 1 and len(authors[0].split()) > 4:
                authors = _split_comma_less_names(authors[0])
            # Trailing footnote/affiliation markers (∗§†‡ etc.) sit directly
            # against the name with no space (e.g. "Yinhan Liu∗§", RoBERTa's
            # real PDF) — strip them so the stored name is just the name.
            authors = [_FOOTNOTE_MARKER_RE.sub("", a).strip() for a in authors]
            authors = [a for a in authors if a]
    return title, authors


def _split_comma_less_names(text: str) -> list[str]:
    """Fallback for comma/and-less bylines — groups consecutive capitalized
    tokens into ~2-word name chunks. Imperfect (a 3-word name like "Jacob R.
    Devlin" would split wrong), but far better than one giant fused string."""
    tokens = text.split()
    names = []
    current: list[str] = []
    for tok in tokens:
        if current and len(current) >= 2 and tok[:1].isupper():
            names.append(" ".join(current))
            current = [tok]
        else:
            current.append(tok)
    if current:
        names.append(" ".join(current))
    return names


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

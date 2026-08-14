"""Unit test for src.services.ingestion.pipeline's pure helpers — no DB/LLM/
Neo4j needed. Covers the live bug found during EVAL-001: raw section text
was passed into extraction prompts completely untruncated, and one
oversized (likely mis-parsed) section blew past Groq's per-request token
cap and crashed the whole paper's extraction with no way to resume."""

from src.services.ingestion.pipeline import _MAX_SECTION_CHARS, _truncate_sections


def test_truncate_sections_leaves_short_sections_untouched():
    sections = {"abstract": "short text", "intro": "a" * 100}
    assert _truncate_sections(sections) == sections


def test_truncate_sections_caps_oversized_sections():
    sections = {"model": "x" * (_MAX_SECTION_CHARS + 500)}
    result = _truncate_sections(sections)
    assert len(result["model"]) == _MAX_SECTION_CHARS + len("\n[truncated]")
    assert result["model"].startswith("x" * _MAX_SECTION_CHARS)
    assert result["model"].endswith("[truncated]")

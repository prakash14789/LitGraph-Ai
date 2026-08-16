"""Unit test for src.services.ingestion.pipeline's pure helpers — no DB/LLM/
Neo4j needed. Covers the live bug found during EVAL-001: raw section text
was passed into extraction prompts completely untruncated, and one
oversized (likely mis-parsed) section blew past Groq's per-request token
cap and crashed the whole paper's extraction with no way to resume."""

from unittest.mock import patch

from src.services.ingestion.entity_extractor import ExtractedClaim, SectionExtraction
from src.services.ingestion.pipeline import (
    _MAX_SECTION_CHARS,
    _TARGET_TYPE_BY_REL,
    _dedupe_claims,
    _drop_conflicting_trained_on,
    _drop_title_and_trivial_claims,
    _is_introduces_grounded,
    _strip_title_from_preamble,
    _truncate_sections,
)
from src.services.ingestion.relation_extractor import ExtractedRelation


def test_truncate_sections_leaves_short_sections_untouched():
    sections = {"abstract": "short text", "intro": "a" * 100}
    assert _truncate_sections(sections) == sections


def test_truncate_sections_caps_oversized_sections():
    sections = {"model": "x" * (_MAX_SECTION_CHARS + 500)}
    result = _truncate_sections(sections)
    assert len(result["model"]) == _MAX_SECTION_CHARS + len("\n[truncated]")
    assert result["model"].startswith("x" * _MAX_SECTION_CHARS)
    assert result["model"].endswith("[truncated]")


# --- EVAL-002 fix 1: email-block noise stripped from preamble -----------


def test_strip_title_from_preamble_removes_title_and_email_block():
    sections = {
        "preamble": "My Great Paper Title\n"
        "{victor, lysandre, julien}@huggingface.co\nAbstract text.",
    }
    result = _strip_title_from_preamble(sections, "My Great Paper Title")
    assert "My Great Paper Title" not in result["preamble"]
    assert "@huggingface.co" not in result["preamble"]
    assert "victor" not in result["preamble"]


def test_strip_title_from_preamble_removes_bare_email_without_title():
    sections = {"preamble": "contact: jane.doe@university.edu for details"}
    result = _strip_title_from_preamble(sections, None)
    assert "@" not in result["preamble"]


# --- EVAL-002 fix 2: within-paper claim dedup ----------------------------


def test_dedupe_claims_drops_near_duplicate_keeping_longer():
    extractions = {
        "abstract": SectionExtraction(
            claims=[
                ExtractedClaim(
                    text="Our model achieves 92 F1.", claim_type="RESULT", confidence=0.9
                )
            ]
        ),
        "conclusion": SectionExtraction(
            claims=[
                ExtractedClaim(
                    text="Our model achieves 92 F1 on the test set.",
                    claim_type="RESULT",
                    confidence=0.9,
                )
            ]
        ),
    }
    with patch("src.services.ingestion.pipeline.embed", return_value=[[1.0, 0.0], [1.0, 0.01]]):
        _dedupe_claims(extractions)
    remaining = [c.text for ext in extractions.values() for c in ext.claims]
    assert remaining == ["Our model achieves 92 F1 on the test set."]


def test_dedupe_claims_keeps_distinct_claims():
    extractions = {
        "abstract": SectionExtraction(
            claims=[ExtractedClaim(text="A", claim_type="RESULT", confidence=0.9)]
        ),
        "conclusion": SectionExtraction(
            claims=[ExtractedClaim(text="B", claim_type="RESULT", confidence=0.9)]
        ),
    }
    with patch("src.services.ingestion.pipeline.embed", return_value=[[1.0, 0.0], [0.0, 1.0]]):
        _dedupe_claims(extractions)
    remaining = [c.text for ext in extractions.values() for c in ext.claims]
    assert len(remaining) == 2


# --- EVAL-002 fix 4: title-match / trivial-fragment claim backstop -------


def test_drop_title_and_trivial_claims_drops_title_match():
    extractions = {
        "preamble": SectionExtraction(
            claims=[
                ExtractedClaim(
                    text="Efficient Estimation of Word Representations",
                    claim_type="RESULT",
                    confidence=0.9,
                ),
                ExtractedClaim(
                    text="Our approach improves accuracy by 5 points over the baseline.",
                    claim_type="RESULT",
                    confidence=0.9,
                ),
            ]
        ),
    }
    _drop_title_and_trivial_claims(extractions, "Efficient Estimation of Word Representations")
    remaining = [c.text for c in extractions["preamble"].claims]
    assert remaining == ["Our approach improves accuracy by 5 points over the baseline."]


def test_drop_title_and_trivial_claims_drops_short_verbless_fragment():
    extractions = {
        "results": SectionExtraction(
            claims=[
                ExtractedClaim(
                    text="Model Architecture Overview", claim_type="RESULT", confidence=0.9
                ),
                ExtractedClaim(
                    text="Results are shown in Table 2.", claim_type="RESULT", confidence=0.9
                ),
            ]
        ),
    }
    _drop_title_and_trivial_claims(extractions, None)
    remaining = [c.text for c in extractions["results"].claims]
    assert remaining == ["Results are shown in Table 2."]


# --- EVAL-002 fix 3: DISTILLED_FROM enforced as a Method-typed target ----


def test_distilled_from_targets_method():
    assert _TARGET_TYPE_BY_REL["DISTILLED_FROM"] == "Method"


# --- EVAL-002 FIX C backstop: INTRODUCES target must be grounded in its
# own evidence_text -------------------------------------------------------


def _relation(relation_type, target, evidence_text, source="paper", **props):
    return ExtractedRelation(
        relation_type=relation_type,
        source=source,
        target=target,
        evidence_text=evidence_text,
        confidence=0.9,
        properties=props,
    )


def test_introduces_grounded_when_target_named_in_evidence():
    r = _relation("INTRODUCES", "RoBERTa", "We call our approach RoBERTa.")
    assert _is_introduces_grounded(r)


def test_introduces_not_grounded_when_evidence_never_mentions_target():
    # Live finding: evidence about a *different* result got attached to an
    # unrelated target name the model appears to have pulled from elsewhere.
    r = _relation(
        "INTRODUCES", "BERTBASE", "Our best model achieves state-of-the-art results on GLUE."
    )
    assert not _is_introduces_grounded(r)


# --- EVAL-002 FIX D backstop: TRAINED_ON dropped when the same pair also
# gets EVALUATES_ON in this run --------------------------------------------


def test_drop_conflicting_trained_on_removes_trained_on_when_pair_also_evaluated():
    trained = _relation("TRAINED_ON", "SST-2", "Our model is trained on SST-2.")
    evaluated = _relation("EVALUATES_ON", "SST-2", "Our model achieves 91.2 on SST-2.")
    entries = [(trained, "paper-1", "dataset-1"), (evaluated, "paper-1", "dataset-1")]

    kept = _drop_conflicting_trained_on(entries)

    assert [r.relation_type for r, _, _ in kept] == ["EVALUATES_ON"]


def test_drop_conflicting_trained_on_keeps_trained_on_for_a_different_dataset():
    trained = _relation("TRAINED_ON", "Wikipedia", "Pretrained on Wikipedia.")
    evaluated = _relation("EVALUATES_ON", "SST-2", "Our model achieves 91.2 on SST-2.")
    entries = [(trained, "paper-1", "dataset-1"), (evaluated, "paper-1", "dataset-2")]

    kept = _drop_conflicting_trained_on(entries)

    assert {r.relation_type for r, _, _ in kept} == {"TRAINED_ON", "EVALUATES_ON"}

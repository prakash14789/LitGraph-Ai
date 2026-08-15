"""EVAL-002 — pure unit tests for run_eval.py's scoring logic (no LLM/HTTP
needed), same rationale as test_pipeline.py's _truncate_sections() coverage:
these are the non-trivial branches (title normalization, score clamping,
aggregation), not the I/O plumbing around them."""

from tests.eval.run_eval import _norm_title, _recall, summarize, to_score


def test_norm_title_ignores_case_and_punctuation():
    assert _norm_title("BERT: Pre-training of Deep Bidirectional Transformers") == _norm_title(
        "bert pre training of deep bidirectional transformers"
    )


def test_norm_title_strips_trailing_disambiguator():
    # eval_dataset.json's own titles carry a "(GPT-2)"-style suffix the real
    # ingested paper title never has — confirmed live to silently zero
    # recall for GPT-2/GPT-3/T5 questions before this fix.
    assert _norm_title("Language Models are Few-Shot Learners (GPT-3)") == _norm_title(
        "Language Models are Few-Shot Learners"
    )


def test_recall_full_when_no_source_papers():
    # A question with no annotated source papers can't be scored against
    # anything — 1.0 (vacuously satisfied), not 0.0 (which would wrongly
    # look like retrieval failure).
    assert _recall([], ["Some Cited Paper"]) == 1.0


def test_recall_counts_matched_fraction():
    assert _recall(["BERT", "RoBERTa"], ["bert!", "Something Else"]) == 0.5


def test_recall_zero_when_nothing_matches():
    assert _recall(["BERT"], ["RoBERTa"]) == 0.0


def test_to_score_clamps_out_of_range():
    assert to_score(5) == 1.0
    assert to_score(-1) == 0.0
    assert to_score(0.5) == 0.5
    assert to_score("not a number") == 0.0


def test_summarize_aggregates_by_category_and_overall():
    run_output = {
        "results": [
            {
                "category": "single-hop",
                "graphrag": {"score": 1.0, "recall": 1.0},
                "vanilla": {"score": 0.0, "recall": 0.5},
                "latency_ms": 100,
            },
            {
                "category": "multi-hop",
                "graphrag": {"score": 0.5, "recall": 0.5},
                "vanilla": {"score": 0.0, "recall": 0.0},
                "latency_ms": 300,
            },
        ]
    }
    summary = summarize(run_output)
    assert summary["overall"]["graphrag"]["accuracy"] == 0.75
    assert summary["overall"]["vanilla"]["accuracy"] == 0.0
    assert summary["by_category"]["single-hop"]["graphrag"]["accuracy"] == 1.0
    assert summary["by_category"]["multi-hop"]["vanilla"]["recall"] == 0.0
    assert summary["avg_latency_ms"] == 200.0

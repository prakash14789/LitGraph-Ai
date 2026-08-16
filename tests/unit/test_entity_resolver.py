"""Unit tests for entity_resolver.resolve_entity — mocked LLM (mock_llm_client)
and mocked embed(), no real API calls.

embed() is patched at src.services.ingestion.entity_resolver.embed, not
src.vectorstore.embedder.embed — entity_resolver.py does `from ... import
embed`, which binds its own module-local name; patching the definition
site wouldn't reach it. Same "where to patch" lesson as SETUP-009's
mock_llm_client bug and every DB-session-patching fixture since."""

import pytest

from src.services.ingestion import entity_resolver
from src.services.ingestion.entity_resolver import ResolvableEntity, resolve_entity

pytestmark = pytest.mark.anyio


def _entity(name, entity_type="Method", description="", aliases=None, id=None, embedding=None):
    return ResolvableEntity(
        name=name,
        entity_type=entity_type,
        description=description,
        aliases=aliases or [],
        id=id,
        embedding=embedding,
    )


async def test_no_candidates_creates_without_calling_llm_or_embedding(mock_llm_client, monkeypatch):
    embed_mock = _mock_embed(monkeypatch)

    result = resolve_entity(_entity("BERT"), [])

    assert result.decision == "create"
    assert result.canonical_name == "BERT"
    mock_llm_client.assert_not_called()
    embed_mock.assert_not_called()


async def test_exact_name_match_merges_without_calling_llm(mock_llm_client, monkeypatch):
    embed_mock = _mock_embed(monkeypatch)
    existing = _entity("BERT", id="node-1", description="a language model")

    result = resolve_entity(_entity("BERT", description="another mention"), [existing])

    assert result.decision == "merge"
    assert result.matched_id == "node-1"
    assert result.method == "exact"
    mock_llm_client.assert_not_called()
    embed_mock.assert_not_called()


async def test_exact_match_is_case_and_whitespace_insensitive(mock_llm_client, monkeypatch):
    _mock_embed(monkeypatch)
    existing = _entity("  BERT  ", id="node-1")

    result = resolve_entity(_entity("bert"), [existing])
    assert result.decision == "merge"
    assert result.method == "exact"


async def test_never_matches_across_entity_types(mock_llm_client, monkeypatch):
    _mock_embed(monkeypatch)
    person_named_bert = _entity("BERT", entity_type="Author", id="author-1")

    result = resolve_entity(_entity("BERT", entity_type="Method"), [person_named_bert])

    assert result.decision == "create"
    mock_llm_client.assert_not_called()


async def test_fuzzy_match_confirmed_by_llm_merges(mock_llm_client, monkeypatch):
    # "GPT-2" vs "GPT2" (hyphen dropped) is a genuine >0.85 SequenceMatcher
    # ratio — a real spelling-variant case, unlike a bigger expansion like
    # "BERT" -> "BERT-base" (that's the embedding pass's job, see below;
    # plain name similarity on that pair doesn't clear 0.85).
    _mock_embed(monkeypatch)
    mock_llm_client.return_value = "DECISION: YES\nREASON: same model, hyphen variant."
    existing = _entity("GPT-2", id="node-1", description="a language model")

    result = resolve_entity(_entity("GPT2", description="a language model"), [existing])

    assert result.decision == "merge"
    assert result.matched_id == "node-1"
    assert result.method == "fuzzy_or_embedding+llm"
    mock_llm_client.assert_called_once()


async def test_verification_call_uses_its_own_independent_key_ring(mock_llm_client, monkeypatch):
    # EVAL-002 FIX E: verification must not share llm_client's module-level
    # ring with bulk extraction — otherwise it silently inherits whatever
    # fallback provider extraction already exhausted its way down to.
    _mock_embed(monkeypatch)
    mock_llm_client.return_value = "DECISION: YES\nREASON: same model, hyphen variant."
    existing = _entity("GPT-2", id="node-1", description="a language model")

    resolve_entity(_entity("GPT2", description="a language model"), [existing])

    assert mock_llm_client.call_args.kwargs["key_ring"] is entity_resolver._verification_key_ring
    from src.utils import llm_client

    assert entity_resolver._verification_key_ring is not llm_client._key_ring


async def test_fuzzy_match_rejected_by_llm_creates_new(mock_llm_client, monkeypatch):
    _mock_embed(monkeypatch)
    mock_llm_client.return_value = "DECISION: NO\nREASON: different entities despite similar name."
    existing = _entity("GPT-2", id="node-1", description="a language model")

    result = resolve_entity(_entity("GPT2", description="unrelated thing"), [existing])

    assert result.decision == "create"
    mock_llm_client.assert_called_once()  # confirms this hit the LLM-rejection path, not a no-op


async def test_embedding_match_confirmed_by_llm_merges_even_with_dissimilar_names(
    mock_llm_client, monkeypatch
):
    _mock_embed(monkeypatch, return_value=[[1.0, 0.0, 0.0]])
    mock_llm_client.return_value = "DECISION: YES\nREASON: same model, full name vs acronym."
    existing = _entity(
        "BERT", id="node-1", description="bidirectional transformer", embedding=[1.0, 0.0, 0.0]
    )

    result = resolve_entity(
        _entity(
            "Bidirectional Encoder Representations from Transformers",
            description="bidirectional transformer",
        ),
        [existing],
    )

    assert result.decision == "merge"
    assert result.matched_id == "node-1"


async def test_dissimilar_candidate_never_reaches_llm(mock_llm_client, monkeypatch):
    _mock_embed(monkeypatch, return_value=[[1.0, 0.0, 0.0]])
    unrelated = _entity(
        "ResNet", id="node-2", description="a vision model", embedding=[0.0, 1.0, 0.0]
    )

    result = resolve_entity(_entity("BERT", description="a language model"), [unrelated])

    assert result.decision == "create"
    mock_llm_client.assert_not_called()


async def test_merge_logic_shorter_canonical_union_aliases_longest_description(
    mock_llm_client, monkeypatch
):
    # Shortlisted via the embedding path (matching mocked vectors), not
    # fuzzy name matching — "BERT" vs "BERT-base" is exactly the kind of
    # pair fuzzy string ratio alone won't catch (see the fuzzy tests above).
    _mock_embed(monkeypatch, return_value=[[1.0, 0.0, 0.0]])
    mock_llm_client.return_value = "DECISION: YES\nREASON: same thing."
    existing = _entity(
        "BERT",
        id="node-1",
        description="short desc",
        aliases=["Bidirectional Encoder Reps"],
        embedding=[1.0, 0.0, 0.0],
    )

    result = resolve_entity(
        _entity("BERT-base", description="a much longer and more detailed description"),
        [existing],
    )

    assert result.decision == "merge"
    assert result.canonical_name == "BERT"
    assert "BERT-base" in result.aliases
    assert "Bidirectional Encoder Reps" in result.aliases
    assert result.description == "a much longer and more detailed description"


async def test_multiple_candidates_tries_next_if_first_rejected(mock_llm_client, monkeypatch):
    # Both candidates shortlisted via embedding similarity, ranked by score
    # (close_but_wrong scores higher — nearly identical vector — so it's
    # tried first, rejected, then real_match is tried and confirmed).
    _mock_embed(monkeypatch, return_value=[[1.0, 0.0, 0.0]])
    mock_llm_client.side_effect = [
        "DECISION: NO\nREASON: not a match.",
        "DECISION: YES\nREASON: this one matches.",
    ]
    close_but_wrong = _entity("BERT-XL", id="node-1", description="x", embedding=[1.0, 0.0, 0.0])
    real_match = _entity("BERT-Base", id="node-2", description="x", embedding=[0.99, 0.14, 0.0])

    result = resolve_entity(
        _entity("BERT-base-uncased", description="x"), [close_but_wrong, real_match]
    )

    assert result.decision == "merge"
    assert result.matched_id == "node-2"
    assert mock_llm_client.call_count == 2


async def test_suffix_variant_shortlisted_without_meeting_raw_fuzzy_ratio(
    mock_llm_client, monkeypatch
):
    # "BERT" vs "BERT-base" only scores ~0.62 on a raw SequenceMatcher ratio
    # (measured live, well under the 0.85 threshold) — this is exactly the
    # ticket's own acceptance-criteria example, caught by the suffix-variant
    # pattern check instead.
    _mock_embed(monkeypatch)
    mock_llm_client.return_value = "DECISION: YES\nREASON: same model, base variant."
    existing = _entity("BERT", id="node-1")

    result = resolve_entity(_entity("BERT-base"), [existing])

    assert result.decision == "merge"
    assert result.matched_id == "node-1"


async def test_suffix_variant_requires_a_boundary_not_just_a_prefix(mock_llm_client, monkeypatch):
    # "BERT" must not match "BERTHA" — sharing a prefix isn't sharing a name.
    _mock_embed(monkeypatch)
    existing = _entity("BERTHA", id="node-1")

    result = resolve_entity(_entity("BERT"), [existing])

    assert result.decision == "create"
    mock_llm_client.assert_not_called()


async def test_acronym_variant_shortlisted_without_meeting_raw_fuzzy_ratio(
    mock_llm_client, monkeypatch
):
    # "BERT" vs its own full expansion scores ~0.14 on a raw ratio — the
    # ticket's second acceptance-criteria example, caught by the acronym
    # pattern check (stopwords like "from" correctly skipped).
    _mock_embed(monkeypatch)
    mock_llm_client.return_value = "DECISION: YES\nREASON: acronym of the same model."
    existing = _entity("BERT", id="node-1")

    result = resolve_entity(
        _entity("Bidirectional Encoder Representations from Transformers"), [existing]
    )

    assert result.decision == "merge"
    assert result.matched_id == "node-1"


async def test_acronym_collision_reaches_llm_rather_than_auto_merging(mock_llm_client, monkeypatch):
    # "GAN" is also the initials of "Graph Attention Network" — a real,
    # different method from "Generative Adversarial Network". The acronym
    # heuristic can't tell these apart (that's not its job); it shortlists
    # both, and relies on step 4's LLM check as the actual arbiter. Confirms
    # the LLM was consulted rather than an initials-match auto-merging.
    _mock_embed(monkeypatch)
    existing = _entity("GAN", id="node-1", description="Generative Adversarial Network")

    resolve_entity(
        _entity("Graph Attention Network", description="a graph neural network"), [existing]
    )

    mock_llm_client.assert_called_once()


def _mock_embed(monkeypatch, return_value=None):
    from unittest.mock import MagicMock

    mock = MagicMock(return_value=return_value if return_value is not None else [[0.0]])
    monkeypatch.setattr(entity_resolver, "embed", mock)
    return mock

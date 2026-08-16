"""Entity resolution (EXTRACT-003) — given a newly-extracted entity, decide
whether it's the same real-world thing as an existing one, per the ticket's
cascading strategy:

1. Exact canonical name match -> merge immediately, skip everything else.
2. Fuzzy name/alias match (ratio > entity_resolution_fuzzy_threshold) -> candidate.
3. Embedding similarity on descriptions (cosine > entity_resolution_embedding_threshold) -> candidate.
4. LLM verification on the union of steps 2+3's candidates, best-scoring
   first — the first one the model confirms as a genuine match wins.
5. Nothing confirmed -> create new entity.

Steps 2 and 3 are independent recall passes, unioned before the LLM does
the precision check — neither alone is sufficient, and neither the ticket's
literal thresholds turned out to work as specified once measured for real
against the ticket's own example pairs:

- Fuzzy name ratio: "BERT" vs "BERT-base" scores ~0.62, "BERT" vs its own
  full expansion scores ~0.14 — both well under the specified >0.85, so a
  plain SequenceMatcher ratio alone misses the ticket's own acceptance
  examples. Fixed with two targeted, boundary-aware pattern checks layered
  on top (see _is_prefix_variant/_is_acronym_variant below): a
  suffix-variant check for "BaseName" vs "BaseName-suffix"/"BaseNameN"
  (BERT/BERT-base, GPT/GPT2 — extremely common ML naming convention) and an
  acronym check for "BERT" vs "Bidirectional Encoder Representations from
  Transformers". Both are boundary/stopword-aware specifically to avoid
  false positives ("BERT" must not match "BERTHA").
- Embedding cosine similarity: real paraphrased-but-same-entity description
  pairs (measured with the local all-MiniLM-L6-v2 model) scored 0.57-0.64,
  not the specified >0.90 — that threshold would make this channel
  essentially never fire on real text. entity_resolution_embedding_threshold
  is calibrated to 0.55 off those real measurements instead (see
  config.py's comment) — a heuristic estimate, not a ticket-literal number,
  with a known ceiling: it hasn't been calibrated against real *negative*
  pairs (genuinely different entities), so it may need tightening if it
  proves too permissive in practice.

String/embedding similarity alone also can't tell "BERT" the language
model from "BERT" someone's name if descriptions happened to look similar,
which is exactly what step 4's LLM check exists to catch.

Never compares across entity_type: a Method is never a candidate match for
a Dataset, regardless of name similarity. This is what actually satisfies
the ticket's "BERT the model vs BERT the person" acceptance example (Author
and Method are different entity_type values, so they never even reach step
1) — verified live. Known remaining gap, not covered by that guard: step 1
merges on exact name match with NO further check, per the ticket's literal
"exact match -> merge [immediately]" instruction — so two *same-type*
entities that happen to share an exact name but are genuinely unrelated
(e.g. two different papers each naming an unrelated method "BERT") would
still auto-merge without ever reaching the LLM. Left as specified rather
than adding an LLM check to the exact-match path, since that would slow
down the common, safe case (a real repeat mention of the same method) to
guard against a same-type exact-name collision that's rare in an academic
corpus — flagged here rather than silently accepted.

This module works on a candidate list passed in by the caller — it doesn't
query Neo4j itself. There's nothing to query yet: EXTRACT-004 (graph
writer) hasn't landed, so the real "existing entities in the graph" lookup
doesn't exist. The interface is what it will be either way: EXTRACT-004
fetches same-type candidates (by canonical name index / embedding search)
and calls resolve_entity with them.
"""

import math
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import structlog

from src.config import settings
from src.services.generation.prompts import (
    ENTITY_RESOLUTION_VERIFICATION_PROMPT,
    entity_resolution_verification_user_prompt,
)
from src.utils import llm_client
from src.vectorstore.embedder import embed

logger = structlog.get_logger()

# EVAL-002 FIX E live finding: verification calls were going through
# llm_client's shared module-level key ring — once bulk entity/relation
# extraction (many calls per paper) had already fallen all the way to the
# local Ollama fallback, every subsequent verification call inherited that
# same degraded state for the rest of the process, even though this step
# only ever fires for the rare fuzzy/embedding-ambiguous case. A weak local
# model gave false "same entity" confirmations here (e.g. two genuinely
# different methods) and false negatives (two names for the same thing not
# confirmed) that a stronger cloud model didn't make. Its own ring means
# verification's low call volume gets its own shot at cloud headroom
# instead of starting already-exhausted.
_verification_key_ring = llm_client._KeyRing()


@dataclass
class ResolvableEntity:
    """One side of a resolution comparison. `id` is None for the
    newly-extracted entity (it doesn't have one yet) and required for an
    existing candidate. `embedding` is expected precomputed for candidates
    (pulled from wherever they're stored) — computed on demand from
    `description` for the new entity if not supplied."""

    name: str
    entity_type: str  # "Method" | "Dataset" | ... — matches Neo4j node labels
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    id: str | None = None
    embedding: list[float] | None = None


@dataclass
class ResolutionResult:
    decision: str  # "merge" | "create"
    matched_id: str | None  # existing candidate's id if merged
    canonical_name: str
    aliases: list[str]
    description: str
    method: str  # "exact" | "fuzzy_or_embedding+llm" | "none" — which stage decided it
    rationale: str  # human-readable, for logging/debugging per the ticket's requirement


def resolve_entity(
    new_entity: ResolvableEntity, candidates: list[ResolvableEntity]
) -> ResolutionResult:
    same_type = [c for c in candidates if c.entity_type == new_entity.entity_type]

    exact = _find_exact_match(new_entity, same_type)
    if exact is not None:
        result = _merge(
            new_entity, exact, method="exact", rationale=f'Exact name match on "{exact.name}".'
        )
        logger.info("entity_resolver.resolved", **_log_fields(new_entity, result))
        return result

    shortlist = _shortlist(new_entity, same_type) if same_type else []
    for candidate, score_note in shortlist:
        if _llm_confirms_match(new_entity, candidate):
            result = _merge(
                new_entity,
                candidate,
                method="fuzzy_or_embedding+llm",
                rationale=f'{score_note}; LLM confirmed "{new_entity.name}" == "{candidate.name}".',
            )
            logger.info("entity_resolver.resolved", **_log_fields(new_entity, result))
            return result

    result = ResolutionResult(
        decision="create",
        matched_id=None,
        canonical_name=new_entity.name,
        aliases=new_entity.aliases,
        description=new_entity.description,
        method="none",
        rationale=(
            f'No exact/fuzzy/embedding candidate for "{new_entity.name}".'
            if not shortlist
            else f'{len(shortlist)} candidate(s) shortlisted for "{new_entity.name}" but none confirmed by LLM.'
        ),
    )
    logger.info("entity_resolver.resolved", **_log_fields(new_entity, result))
    return result


def _find_exact_match(
    new_entity: ResolvableEntity, candidates: list[ResolvableEntity]
) -> ResolvableEntity | None:
    target = _normalize(new_entity.name)
    for c in candidates:
        if _normalize(c.name) == target:
            return c
    return None


def _shortlist(
    new_entity: ResolvableEntity, candidates: list[ResolvableEntity]
) -> list[tuple[ResolvableEntity, str]]:
    """Union of fuzzy-name and embedding-description matches, best combined
    score first. Each entry carries a one-line note on why it qualified —
    folded into the final rationale if the LLM confirms it."""
    new_embedding = new_entity.embedding
    if new_embedding is None and new_entity.description.strip():
        new_embedding = embed([new_entity.description])[0]

    scored: dict[str, tuple[ResolvableEntity, float, str]] = {}
    for c in candidates:
        fuzzy_score = _best_fuzzy_ratio(new_entity, c)
        embed_score = (
            _cosine_similarity(new_embedding, c.embedding)
            if new_embedding is not None and c.embedding is not None
            else 0.0
        )
        notes = []
        if fuzzy_score > settings.entity_resolution_fuzzy_threshold:
            notes.append(f"name similarity {fuzzy_score:.2f}")
        if embed_score > settings.entity_resolution_embedding_threshold:
            notes.append(f"description similarity {embed_score:.2f}")
        if notes:
            key = c.id or c.name
            scored[key] = (c, max(fuzzy_score, embed_score), ", ".join(notes))

    ranked = sorted(scored.values(), key=lambda item: item[1], reverse=True)
    return [(c, note) for c, _score, note in ranked]


def _best_fuzzy_ratio(new_entity: ResolvableEntity, candidate: ResolvableEntity) -> float:
    candidate_names = [candidate.name, *candidate.aliases]
    new_names = [new_entity.name, *new_entity.aliases]
    return max(_name_similarity(a, b) for a in new_names for b in candidate_names)


def _name_similarity(a: str, b: str) -> float:
    """Generic edit-distance ratio, boosted to 1.0 for two common ML naming
    patterns a raw ratio scores too low to catch (measured live building
    this module — see the module docstring): a suffix-variant ("BERT" /
    "BERT-base", "GPT" / "GPT2") or an acronym-of-a-full-name
    ("BERT" / "Bidirectional Encoder Representations from Transformers").
    Both checks are boundary-aware/stopword-aware specifically to avoid
    false positives ("BERT" must not prefix-match "BERTHA")."""
    if _is_prefix_variant(a, b) or _is_acronym_variant(a, b):
        return 1.0
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _is_prefix_variant(a: str, b: str) -> bool:
    shorter, longer = sorted([_normalize(a), _normalize(b)], key=len)
    if len(shorter) < 2 or not longer.startswith(shorter):
        return False
    boundary = longer[len(shorter) : len(shorter) + 1]
    return (
        not boundary or not boundary.isalpha()
    )  # end of string, digit, or separator — not a new word


_ACRONYM_STOPWORDS = {"a", "an", "the", "of", "for", "from", "and", "to", "in", "on", "with"}
_WORD_RE = re.compile(r"[A-Za-z]+")


def _is_acronym_variant(a: str, b: str) -> bool:
    shorter, longer = sorted([a, b], key=len)
    if len(shorter) < 2 or not shorter.isalpha():
        return False
    words = [w for w in _WORD_RE.findall(longer) if w.lower() not in _ACRONYM_STOPWORDS]
    acronym = "".join(w[0] for w in words).upper()
    return len(words) >= 2 and acronym == shorter.upper()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _llm_confirms_match(new_entity: ResolvableEntity, candidate: ResolvableEntity) -> bool:
    user_prompt = entity_resolution_verification_user_prompt(
        new_entity.name,
        new_entity.entity_type,
        new_entity.description,
        candidate.name,
        candidate.entity_type,
        candidate.description,
    )
    raw = llm_client.complete(
        ENTITY_RESOLUTION_VERIFICATION_PROMPT,
        user_prompt,
        model=settings.extraction_model,
        max_tokens=100,
        temperature=0.0,
        key_ring=_verification_key_ring,
    )
    first_line = next((line for line in raw.strip().splitlines() if line.strip()), "")
    return "yes" in first_line.lower()


def _merge(
    new_entity: ResolvableEntity, matched: ResolvableEntity, method: str, rationale: str
) -> ResolutionResult:
    # "Best" canonical name = the shorter one — in practice that's the
    # commonly-used short/acronym form ("BERT") over a fuller name
    # ("Bidirectional Encoder Representations from Transformers"), which
    # becomes an alias instead. Ties keep the existing candidate's name, so
    # an established node doesn't get renamed back and forth on repeat runs.
    canonical_name = new_entity.name if len(new_entity.name) < len(matched.name) else matched.name

    all_names = {matched.name, new_entity.name, *matched.aliases, *new_entity.aliases}
    aliases = sorted(n for n in all_names if n and _normalize(n) != _normalize(canonical_name))

    description = max(matched.description, new_entity.description, key=len)

    return ResolutionResult(
        decision="merge",
        matched_id=matched.id,
        canonical_name=canonical_name,
        aliases=aliases,
        description=description,
        method=method,
        rationale=rationale,
    )


def _normalize(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _log_fields(new_entity: ResolvableEntity, result: ResolutionResult) -> dict:
    return {
        "entity_name": new_entity.name,
        "entity_type": new_entity.entity_type,
        "decision": result.decision,
        "matched_id": result.matched_id,
        "method": result.method,
        "rationale": result.rationale,
    }

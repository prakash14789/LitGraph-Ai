"""Formats retrieved chunks as context, asks the LLM for a cited answer.

Only knows about chunk text and paper_ids — resolving paper_id -> a human
readable title (for real citations) needs a DB session, which lives at the
route layer, keeping this module DB-free like retriever.py/store.py."""

from dataclasses import dataclass

import tiktoken

from src.config import settings
from src.services.vanilla_rag.retriever import RetrievedChunk
from src.utils import llm_client

_SYSTEM_PROMPT = (
    "You are a research assistant answering questions using only the provided "
    "excerpts from academic papers. Cite sources using the bracketed numbers "
    "given with each excerpt, e.g. [1]. If the excerpts don't contain enough "
    "information to answer, say so plainly instead of guessing."
)

# Same encoding context_builder.py already uses for GraphRAG's context_tokens
# stat — COMPARE-001 needs the equivalent number on the vanilla side so the
# Compare page's two stat panels are actually comparable.
_ENCODING = tiktoken.get_encoding("cl100k_base")


@dataclass
class GeneratedAnswer:
    text: str
    context_tokens: int


def generate_answer(query: str, chunks: list[RetrievedChunk]) -> GeneratedAnswer:
    if not chunks:
        return GeneratedAnswer(
            text="No relevant content was found to answer this question.", context_tokens=0
        )

    context = "\n\n".join(
        f"[{i + 1}] (paper_id={c.paper_id}, section={c.section_name}) {c.text}"
        for i, c in enumerate(chunks)
    )
    user_prompt = f"Excerpts:\n\n{context}\n\nQuestion: {query}"

    answer = llm_client.complete(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=settings.generation_model,
        max_tokens=settings.generation_max_tokens,
        temperature=settings.generation_temperature,
    )
    return GeneratedAnswer(text=answer, context_tokens=len(_ENCODING.encode(context)))

"""GraphRAG generator (RETRIEVAL-005) — the last step of the pipeline
RETRIEVAL-001 through -004 built. Takes RETRIEVAL-004's BuiltContext +
the user's query, asks the LLM for a cited answer.

DB-free, same as vanilla_rag/generator.py: it only sees context.text (which
already has paper titles/entity names/evidence baked in by context_builder.py)
and never needs a paper_id -> title lookup itself — the route layer resolves
citations separately, from the same ranked subgraph, not by parsing this
answer's prose (parsing free-form LLM text for citations would be fragile;
the graph data is the reliable source of truth for "which papers were
actually used").

Same `from src.utils import llm_client` + module-qualified `llm_client.complete`
call style as vanilla_rag/generator.py — required for tests' mock_llm_client
fixture (monkeypatches the module attribute) to intercept this call too.
"""

from src.config import settings
from src.services.retrieval.context_builder import BuiltContext
from src.utils import llm_client

_SYSTEM_PROMPT = (
    "You are a research assistant answering questions about a corpus of academic "
    "papers using a knowledge graph extracted from them. You are given ENTITIES "
    "(methods, datasets, papers, and claims), RELATIONSHIPS between them (with "
    "evidence text where available), and RELEVANT TEXT CHUNKS for additional "
    "context. Answer using ONLY this provided context — never rely on outside "
    "knowledge. When you state a fact, name the paper it comes from (papers "
    "appear in the context as 'Title') and reference the specific relationship "
    "or chunk it's grounded in. If the context doesn't contain enough "
    "information to answer the question, say plainly: \"I don't know based on "
    'the available papers." Do not guess.'
)


def generate_answer(query: str, context: BuiltContext) -> str:
    if not context.text.strip():
        return "I don't know based on the available papers — no relevant content was found."

    user_prompt = f"{context.text}\n\nQuestion: {query}"
    return llm_client.complete(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=settings.generation_model,
        max_tokens=settings.generation_max_tokens,
        temperature=settings.generation_temperature,
    )

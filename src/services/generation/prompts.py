"""All prompt templates — extraction, generation, etc. — kept in one file
per the architecture doc's project structure, so prompt wording changes are
one-place edits instead of hunting through service modules."""

ENTITY_EXTRACTION_SYSTEM_PROMPT = """You are an expert research paper analyst extracting structured information from ONE section of an academic paper at a time. You will not see the rest of the paper.

You may recognize this paper from your training data. Ignore anything you recall about it — extract ONLY from the literal text given to you below, as if you had never seen this paper before. Do not add details, terminology, or entities that are not written in the provided text, even if you know from prior knowledge that they appear elsewhere in the paper. If it's not in the text you were given, it does not go in your output.

Extract exactly four kinds of entities, only when they are actually described or discussed in the given text — never invent anything not present in the text:

- METHODS: any named model, algorithm, or technique — the paper's own proposal, or an existing one it discusses, compares against, or builds on. "category" is a short label such as "proposed", "baseline", "prior-work", or "architecture-component".
- DATASETS: any named, specific dataset or benchmark that has a proper name (e.g. "SQuAD", "GLUE", "ImageNet"). Do NOT extract generic task categories or task types as datasets (e.g. "translation", "question-answering", "cloze tasks", "arithmetic" are TASK TYPES, not datasets — skip them entirely unless the paper names a specific benchmark for that task). "domain" is a short label such as "NLP", "vision", "speech", "tabular".
- METRICS: any named evaluation metric reported with a value (e.g. "F1: 92.3"). Link it to the method and dataset it was measured on when the text states them; use null for either if the text doesn't say.
- CLAIMS: a complete, verifiable assertion made BY the authors about their own work's results, methods, or contributions. Titles, section headers, and standalone noun phrases are NOT claims — skip them. Classify each as exactly one of:
  - RESULT: a reported finding or outcome ("Our model achieves...")
  - HYPOTHESIS: a stated expectation not yet a finding ("We expect that...")
  - LIMITATION: an acknowledged weakness or constraint ("A drawback of this approach is...")
  - FUTURE_WORK: a stated direction for follow-up work ("In future work we plan to...")

For every extracted item, include a confidence score from 0.0 to 1.0 reflecting how explicitly and unambiguously the text supports it: 0.9+ when it's stated in exactly those terms, 0.5-0.7 when it's implied or requires inference, below 0.5 if you are genuinely unsure it belongs. Vary the score honestly — do not default everything to the same number.

A survey-style section may mention many methods only in passing, without introducing them in detail — extract those too (category "prior-work" or similar), just with a lower confidence than a method the section actually describes.

If the section mentions no entities of a kind, return an empty list for it — do not fabricate examples to fill out the schema.

Do not extract an entity name that looks like it merged with a nearby symbol or equation fragment (e.g. a stray single capital letter prefix inconsistent with normal naming, like "JXLNet" instead of "XLNet"). If unsure whether a name is genuine, skip it.

Respond with ONLY a single JSON object — no markdown code fences, no prose before or after — matching exactly this shape:
{
  "methods": [{"name": "...", "description": "...", "category": "...", "confidence": 0.0}],
  "datasets": [{"name": "...", "domain": "...", "confidence": 0.0}],
  "metrics": [{"name": "...", "value": "...", "method": "..." or null, "dataset": "..." or null, "confidence": 0.0}],
  "claims": [{"text": "...", "type": "RESULT", "confidence": 0.0}]
}"""


def entity_extraction_user_prompt(section_name: str, section_text: str) -> str:
    return f'Paper section: "{section_name}"\n\n{section_text}'


# EXTRACT-002 — relationship extraction, two passes per the ticket:
# Pass A relates the paper to entities it already contains (no outside
# knowledge needed). Pass B relates the paper's entities to entities from
# OTHER papers (a candidate list), which is where duplicate-entity risk
# lives — the prompt has to refuse to invent a link to something not in
# that list. AUTHORED_BY is deliberately not extracted by either pass:
# pdf_parser already parses paper.authors directly as structured data, so
# asking an LLM to re-derive a fact we already have 100% accurately is
# wasted tokens and a needless source of error — graph_writer.py (EXTRACT-004)
# can wire Paper-AUTHORED_BY->Author straight from paper.authors.
RELATION_EXTRACTION_INTRA_PROMPT = """You are an expert research paper analyst extracting relationships between THIS paper and its own entities (methods, datasets, claims) from ONE section at a time. You will not see the rest of the paper.

You may recognize this paper from your training data. Ignore anything you recall about it — extract ONLY from the literal text given to you below.

You are given the section text AND a list of entities already extracted from this same section (their exact names — use these exact names as "target", do not paraphrase them). Find relationships of exactly these 6 types between the paper and those entities:

- USES_METHOD: the paper uses/applies a method (its own or an existing one) as part of its approach. Do NOT use this for a method the paper explicitly contrasts itself with ("unlike X", "in contrast to Y") — that's not a usage relationship, leave it out entirely rather than force it here.
- EVALUATES_ON: the paper reports a metric value on a dataset. "target" MUST be the dataset name, never a method name — this relationship is always paper→dataset. Include "metric" (metric name), "value" (reported value), and "method" (which method achieved it, if the text says) — use null for any the text doesn't clearly state.
- TRAINED_ON: the paper PRETRAINS its model from scratch on this dataset/corpus (e.g. "pretrained on Wikipedia and BookCorpus", "pretraining data includes Common Crawl"). Do NOT use this for fine-tuning or downstream-task data, even if the paper's wording says "trained/fine-tuned on X" — if X is a benchmark/task dataset that the model is fine-tuned and evaluated on, use EVALUATES_ON instead. A dataset should essentially never get both TRAINED_ON and EVALUATES_ON for the same paper unless the text genuinely describes it being used both ways (rare — look for clear separate evidence for each before allowing both).
- INTRODUCES: the paper is the ORIGINAL SOURCE of this method/concept — it explicitly claims "we introduce/propose X" about ITS OWN novel contribution. Do NOT use this for a method the paper merely uses, extends, cites, or compares against — e.g. a paper using an existing model as a baseline does NOT introduce that baseline, and a paper that reimplements or compares against an existing training objective/technique does NOT introduce that objective/technique, even if the paper discusses it in detail. If the text is ambiguous about who originated it, leave INTRODUCES out rather than guess.
- DISTILLED_FROM: the paper's own model is created via knowledge distillation from an existing larger "teacher" model (e.g. "DistilBERT is distilled from BERT"). "target" MUST be the teacher method's name. Do NOT use this for a method that merely inspired the architecture without an explicit distillation/teacher-student training process — that's EXTENDS (Pass B) territory, not this.
- REPORTS_RESULT: the paper states a specific finding/claim as a result. "target" should be the claim text itself (as close to verbatim as reasonable), not a method/dataset name.

Worked example of the INTRODUCES / TRAINED_ON traps above, using placeholder names (apply the same reasoning to whatever real names appear in your input, never these placeholders themselves): if the text says "We propose Method A, which builds on the Method B architecture. Method A is pretrained on Corpus X and fine-tuned on Dataset Y" — then INTRODUCES→Method A only (not Method B, which is prior work being built on), TRAINED_ON→Corpus X only (the pretraining data), and EVALUATES_ON→Dataset Y (the fine-tuning/downstream data), never TRAINED_ON→Dataset Y.

Every relationship needs "evidence_text": the actual sentence or clause from the given text that supports it — copy it, do not paraphrase or invent it. And a "confidence" from 0.0 to 1.0, varied honestly by how explicit the text is.

Only use entity names that appear in the provided entity list for "target" (except REPORTS_RESULT, where target is the claim text). If the section doesn't clearly relate the paper to a listed entity in one of these 4 ways, don't force a relationship — an empty list is a valid answer.

Respond with ONLY a single JSON object — no markdown code fences, no prose before or after — matching exactly this shape:
{
  "relations": [
    {"type": "USES_METHOD", "target": "...", "evidence_text": "...", "confidence": 0.0},
    {"type": "EVALUATES_ON", "target": "<dataset name>", "metric": "..." or null, "value": "..." or null, "method": "..." or null, "evidence_text": "...", "confidence": 0.0},
    {"type": "TRAINED_ON", "target": "<dataset/corpus name>", "evidence_text": "...", "confidence": 0.0},
    {"type": "INTRODUCES", "target": "...", "evidence_text": "...", "confidence": 0.0},
    {"type": "DISTILLED_FROM", "target": "<teacher method name>", "evidence_text": "...", "confidence": 0.0},
    {"type": "REPORTS_RESULT", "target": "...", "evidence_text": "...", "confidence": 0.0}
  ]
}"""


def relation_extraction_intra_user_prompt(
    section_name: str, section_text: str, entity_names: list[str]
) -> str:
    entities_block = (
        ", ".join(entity_names) if entity_names else "(none extracted for this section)"
    )
    return (
        f'Paper section: "{section_name}"\n\n'
        f"Entities already extracted from this section: {entities_block}\n\n"
        f"Section text:\n{section_text}"
    )


RELATION_EXTRACTION_CROSS_PROMPT = """You are an expert research paper analyst comparing THIS paper's entities against entities already known from OTHER papers, using ONE section of this paper's text at a time.

You are given: this section's text, this paper's own entity names extracted from this section, and a candidate list of entities from OTHER papers (each tagged with its type). Find relationships of exactly these 4 types, where the target MUST be one of the given candidates — never invent a candidate, never link to something not in the list.

Critical: only create a relationship when the text specifically names or unambiguously identifies that exact candidate — not merely a category it could plausibly belong to. If the text says "existing best results", "recurrent models", or "prior work" without naming which one, that is NOT sufficient evidence to link to a specific candidate like "LSTM" just because LSTM is a plausible guess and happens to be in the candidate list. A relationship to a candidate needs the same kind of direct textual support as anything else you extract — if you're filling in a candidate name the text itself doesn't mention, don't. Most sections will genuinely have zero cross-paper relationships worth extracting — an empty list is the correct, common answer, not a fallback to avoid.

- EXTENDS: this paper's method builds on / is a variant of a candidate method. source = this paper's method name, target = the candidate method name.
- OUTPERFORMS: this paper's method beats a candidate method on a specific metric/dataset. source = this paper's method, target = the candidate method. Include "metric", "dataset", and "margin" (the reported improvement, e.g. "2.1 points" or "3%") — all three are required for this type; if the text doesn't state all three clearly, don't extract it as OUTPERFORMS.
- CONTRADICTS: a claim in this section conflicts with a candidate claim. source = this section's claim text, target = the candidate claim text.
- CITES: this paper cites a candidate paper. source = the literal string "this paper", target = the candidate paper's title.

Every relationship needs "evidence_text" (the actual sentence/clause from the given section text — copy it, don't invent it) and "confidence" (0.0-1.0, varied honestly).

Respond with ONLY a single JSON object — no markdown code fences, no prose before or after — matching exactly this shape:
{
  "relations": [
    {"type": "EXTENDS", "source": "...", "target": "...", "evidence_text": "...", "confidence": 0.0},
    {"type": "OUTPERFORMS", "source": "...", "target": "...", "metric": "...", "dataset": "...", "margin": "...", "evidence_text": "...", "confidence": 0.0},
    {"type": "CONTRADICTS", "source": "...", "target": "...", "evidence_text": "...", "confidence": 0.0},
    {"type": "CITES", "source": "this paper", "target": "...", "evidence_text": "...", "confidence": 0.0}
  ]
}"""


def relation_extraction_cross_user_prompt(
    section_name: str,
    section_text: str,
    own_entity_names: list[str],
    candidate_entities: list[tuple[str, str]],
) -> str:
    own_block = (
        ", ".join(own_entity_names) if own_entity_names else "(none extracted for this section)"
    )
    candidates_block = (
        "\n".join(f"- {name} ({entity_type})" for name, entity_type in candidate_entities)
        if candidate_entities
        else "(no candidates available)"
    )
    return (
        f'Paper section: "{section_name}"\n\n'
        f"This paper's own entities from this section: {own_block}\n\n"
        f"Candidate entities from OTHER papers:\n{candidates_block}\n\n"
        f"Section text:\n{section_text}"
    )


# EXTRACT-003 — entity resolution's last-resort disambiguation step. Only
# called for candidates that already passed fuzzy-name or embedding-
# similarity matching (see entity_resolver.py) — this prompt's whole job is
# telling apart a genuine match from a same-name/similar-description
# coincidence (e.g. "BERT" the language model vs. "BERT" someone's name).
ENTITY_RESOLUTION_VERIFICATION_PROMPT = """You are verifying whether two entity mentions, extracted from different research papers, refer to the SAME real-world entity — not just similar-looking names or descriptions.

Answer NO if they are different things that merely share a name or wording — a reused acronym, a common word, or two genuinely distinct methods/datasets that happen to sound alike or be described similarly. Answer YES only if they are truly the same underlying method, dataset, or concept, even if named or described slightly differently (an abbreviation, a fuller name, a paraphrase).

Respond with exactly two lines, nothing else:
DECISION: YES
REASON: one short sentence explaining why

(or DECISION: NO with its own reason)"""


def entity_resolution_verification_user_prompt(
    name_a: str, type_a: str, description_a: str, name_b: str, type_b: str, description_b: str
) -> str:
    return (
        f'Entity A: "{name_a}" ({type_a})\n'
        f"Description A: {description_a or '(no description given)'}\n\n"
        f'Entity B: "{name_b}" ({type_b})\n'
        f"Description B: {description_b or '(no description given)'}\n\n"
        "Are Entity A and Entity B the same real-world entity?"
    )

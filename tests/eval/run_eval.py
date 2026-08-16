"""EVAL-002 — automated evaluation script.

Runs every question in eval_dataset.json through POST /query/compare (already
runs GraphRAG + vanilla RAG concurrently server-side, RETRIEVAL-006 — this
script's own job is scoring + reporting, not re-implementing retrieval).
Requires the backend running and reachable at API_BASE_URL, and the
dataset's papers already ingested (EVAL-001).

Scoring, two independent signals per system per question:
(a) LLM-as-judge correctness: 0 / 0.5 / 1.0 (wrong / partially correct /
    correct) against the dataset's gold_answer. Judge model is pinned
    directly to local Ollama (own OpenAI client, bypassing llm_client.py's
    shared _key_ring) — NOT the same cascading fallback chain the answers
    themselves came through. Found live (EVAL-002 2nd run): this script runs
    as its own process, with its own independent _key_ring state from the
    backend server's — the two exhaust Groq/Gemini/OpenRouter at different
    rates, so the judge can silently drift onto a much weaker model (OpenRouter's
    free 20B tier, in the case that happened) mid-run while the server is
    still answering on a stronger one. A judge whose own quality changes
    between questions isn't a rubric — it invalidated 14 of 27 questions in
    that run (every one scored 0.0/0.0, a dead giveaway). Ollama has no rate
    limit to run out of, so pinning the judge there guarantees constant
    grading quality across the whole run, independent of whatever the
    system under test happens to be running on for any given question —
    which is allowed to vary (real production failover), the *judge*
    is not.
(b) Source-paper recall: fraction of the question's known source_papers whose
    title shows up in that system's own citations/sources. The ticket's
    wording is "gold-answer entities" — the dataset (EVAL-001) only
    annotates source_papers per question, not entity-level spans, so this is
    the honest metric actually computable from what exists, not a literal
    reading of the ticket text. It still measures exactly the thing
    multi-hop questions are testing: did retrieval pull in the right *papers*
    to combine, not just answer fluently.

Usage: poetry run python -m tests.eval.run_eval
(from repo root, backend + worker containers up, dataset papers ingested).
"""

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from openai import OpenAI

from src.config import settings
from src.utils.llm_json import parse_json_response

API_BASE_URL = "http://localhost:8000/api/v1"
DATASET_PATH = Path(__file__).parent / "eval_dataset.json"
RESULTS_DIR = Path(__file__).parent / "eval_results"
_JUDGE_MODEL = "qwen2.5:14b"  # local Ollama — see module docstring for why this is pinned

_JUDGE_SYSTEM_PROMPT = """You are grading a QA system's answer against a gold reference answer. \
Score 1.0 if the answer is fully correct and addresses the question, 0.5 if it's partially \
correct or missing some detail the gold answer has, 0.0 if it's wrong or doesn't address the \
question. Be strict about factual correctness, lenient about phrasing/wording differences. \
Respond with ONLY a JSON object: {"score": 0.0|0.5|1.0, "reasoning": "<one sentence>"}"""

# Own client, deliberately not llm_client.complete() — see module docstring.
# "ollama" placeholder key: same as llm_client.py's own _API_KEYS["ollama"],
# Ollama's local server has no auth but the SDK requires a non-empty string.
_judge_client = OpenAI(api_key="ollama", base_url=settings.ollama_base_url)


def _judge(question: str, gold_answer: str, system_answer: str) -> dict:
    user_prompt = (
        f"Question: {question}\n\nGold answer: {gold_answer}\n\nSystem's answer: {system_answer}"
    )
    # One retry on a transient/malformed response — same rationale as
    # relation_extractor.py's _extract(): a fresh sample sometimes recovers
    # from a one-off slip, cheaper than failing the whole question over it.
    raw = ""
    for _attempt in range(2):
        try:
            response = _judge_client.chat.completions.create(
                model=_JUDGE_MODEL,
                messages=[
                    {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=200,
                # 0, not the app's usual 0.3 default — a judge that can
                # score the same answer differently on a re-run isn't a
                # grading rubric, it's a coin flip. Found live: at 0.3,
                # several close calls in a 27-question run were plausibly
                # judge noise, not a real system difference.
                temperature=0.0,
            )
            raw = response.choices[0].message.content or ""
            if raw:
                break
        except Exception as exc:  # noqa: BLE001 — judge must never take the whole run down
            raw = f"[judge call failed] {type(exc).__name__}: {exc}"
    parsed = parse_json_response(raw)
    if parsed is None or "score" not in parsed:
        # ponytail: a single unparseable judge response shouldn't kill the
        # whole run — score it 0 with the raw text as the reasoning so it's
        # visible (and rare) in the report rather than silently dropped.
        return {"score": 0.0, "reasoning": f"[unparseable judge response] {raw[:200]}"}
    return {"score": to_score(parsed["score"]), "reasoning": parsed.get("reasoning", "")}


def to_score(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


_DISAMBIGUATOR_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _norm_title(title: str | None) -> str:
    # eval_dataset.json's own titles carry a disambiguating suffix real
    # ingested titles don't have — e.g. "...Text-to-Text Transformer (T5)"
    # vs the actual paper's stored title, "...Text-to-Text Transformer".
    # Confirmed live: this was silently zeroing recall for every GPT-2/GPT-3/
    # T5 question even when retrieval was correct (sh-06 — both systems gave
    # a correct T5 answer, both scored recall=0.0). Strip it before
    # normalizing so a real match isn't missed over a parenthetical only one
    # side has.
    stripped = _DISAMBIGUATOR_RE.sub("", title or "")
    return re.sub(r"[^a-z0-9]", "", stripped.lower())


def _recall(source_titles: list[str], cited_titles: list[str]) -> float:
    if not source_titles:
        return 1.0
    cited_norm = {_norm_title(t) for t in cited_titles}
    hits = sum(1 for t in source_titles if _norm_title(t) in cited_norm)
    return hits / len(source_titles)


def _run_one(client: httpx.Client, q: dict, title_by_id: dict[str, str]) -> dict:
    source_titles = [title_by_id[pid] for pid in q["source_papers"] if pid in title_by_id]

    t0 = time.monotonic()
    resp = client.post("/query/compare", json={"query": q["question"]})
    resp.raise_for_status()
    data = resp.json()
    latency_ms = int((time.monotonic() - t0) * 1000)

    graphrag_answer = data["graphrag"]["answer"]
    vanilla_answer = data["vanilla"]["answer"]
    graphrag_cited = [c["title"] for c in data["graphrag"]["citations"] if c.get("title")]
    vanilla_cited = [s["paper_title"] for s in data["vanilla"]["sources"] if s.get("paper_title")]

    graphrag_judge = _judge(q["question"], q["gold_answer"], graphrag_answer)
    vanilla_judge = _judge(q["question"], q["gold_answer"], vanilla_answer)
    print(
        f"    graphrag={graphrag_judge['score']} vanilla={vanilla_judge['score']} ({latency_ms}ms)",
        flush=True,
    )

    return {
        "id": q["id"],
        "category": q["category"],
        "question": q["question"],
        "source_papers": source_titles,
        "latency_ms": latency_ms,
        "graphrag": {
            "answer": graphrag_answer,
            "score": graphrag_judge["score"],
            "reasoning": graphrag_judge["reasoning"],
            "recall": _recall(source_titles, graphrag_cited),
        },
        "vanilla": {
            "answer": vanilla_answer,
            "score": vanilla_judge["score"],
            "reasoning": vanilla_judge["reasoning"],
            "recall": _recall(source_titles, vanilla_cited),
        },
    }


def run() -> dict:
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    title_by_id = {p["id"]: p["title"] for p in dataset["papers"]}
    questions = dataset["questions"]

    results = []
    errors = []
    # 300s, not 120s: EVAL-001 live finding reapplied here — a /query/compare
    # call that falls back to local Ollama mid-run (Groq rate-limited) can
    # take well over a minute for a single generation. One question timing
    # out must not kill the other 26 — per-question try/except + a generous
    # per-call retry, not a bigger blast radius on failure.
    with httpx.Client(base_url=API_BASE_URL, timeout=300.0) as client:
        for i, q in enumerate(questions, 1):
            print(f"[{i}/{len(questions)}] ({q['category']}) {q['question'][:70]}...", flush=True)
            try:
                results.append(_run_one(client, q, title_by_id))
            except Exception as exc:
                print(f"    SKIPPED ({type(exc).__name__}: {exc})", flush=True)
                errors.append({"id": q["id"], "error": f"{type(exc).__name__}: {exc}"})

    return {"generated_at": datetime.now(UTC).isoformat(), "results": results, "errors": errors}


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def summarize(run_output: dict) -> dict:
    results = run_output["results"]
    by_category: dict[str, list[dict]] = {}
    for r in results:
        by_category.setdefault(r["category"], []).append(r)

    def system_stats(rows: list[dict], system: str) -> dict:
        return {
            "accuracy": _avg([r[system]["score"] for r in rows]),
            "recall": _avg([r[system]["recall"] for r in rows]),
        }

    return {
        "overall": {
            "graphrag": system_stats(results, "graphrag"),
            "vanilla": system_stats(results, "vanilla"),
        },
        "by_category": {
            cat: {
                "graphrag": system_stats(rows, "graphrag"),
                "vanilla": system_stats(rows, "vanilla"),
            }
            for cat, rows in by_category.items()
        },
        "avg_latency_ms": _avg([r["latency_ms"] for r in results]),
    }


def render_markdown(run_output: dict, summary: dict) -> str:
    lines = [
        "# LitGraph Evaluation Report",
        "",
        f"Generated: {run_output['generated_at']}",
        f"Questions: {len(run_output['results'])}"
        + (
            f" ({len(run_output['errors'])} skipped due to errors)"
            if run_output.get("errors")
            else ""
        ),
        "",
        "## Overall",
        "",
        "| System | Accuracy | Source-paper recall |",
        "|---|---|---|",
        f"| GraphRAG | {summary['overall']['graphrag']['accuracy']} | {summary['overall']['graphrag']['recall']} |",
        f"| Vanilla RAG | {summary['overall']['vanilla']['accuracy']} | {summary['overall']['vanilla']['recall']} |",
        "",
        f"Avg latency per question (both systems, concurrent): {summary['avg_latency_ms']}ms",
        "",
        "## By category",
        "",
        "| Category | GraphRAG accuracy | Vanilla accuracy | GraphRAG recall | Vanilla recall |",
        "|---|---|---|---|---|",
    ]
    for cat, s in summary["by_category"].items():
        lines.append(
            f"| {cat} | {s['graphrag']['accuracy']} | {s['vanilla']['accuracy']} "
            f"| {s['graphrag']['recall']} | {s['vanilla']['recall']} |"
        )

    wins = [r for r in run_output["results"] if r["graphrag"]["score"] > r["vanilla"]["score"]]
    lines += ["", "## Examples where GraphRAG won", ""]
    if not wins:
        lines.append("None this run.")
    for r in wins[:5]:
        lines += [
            f"**{r['id']}** ({r['category']}): {r['question']}",
            f"- GraphRAG ({r['graphrag']['score']}): {r['graphrag']['reasoning']}",
            f"- Vanilla ({r['vanilla']['score']}): {r['vanilla']['reasoning']}",
            "",
        ]
    return "\n".join(lines)


def main() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    run_output = run()
    summary = summarize(run_output)
    run_output["summary"] = summary

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (RESULTS_DIR / f"results_{stamp}.json").write_text(
        json.dumps(run_output, indent=2), encoding="utf-8"
    )
    (RESULTS_DIR / f"report_{stamp}.md").write_text(
        render_markdown(run_output, summary), encoding="utf-8"
    )

    print("\n" + render_markdown(run_output, summary))
    print(f"\nSaved to {RESULTS_DIR}/results_{stamp}.json and report_{stamp}.md")


if __name__ == "__main__":
    main()

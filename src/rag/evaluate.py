"""Evals: how well the RAG finds and answers. evals/README.md describes the files.

Retrieval (evals/retrieval.jsonl): questions with the passage that answers them, given as a
document and a quote from it. A chunk is relevant when it is from that document and contains
the quote, so the same question scores either chunking. recall@k is the share of questions
with a relevant chunk in the top k; MRR the mean of 1/rank of the first one, 0 past rank 10.

Answers (evals/testset.jsonl), each scored:
- deterministically: it cites a right source and no forbidden one (an outdated version, a
  look-alike), it has the key facts, and it abstains exactly when it should;
- by an LLM judge against the expected answer: correct, partial or incorrect;
- for faithfulness: the share of its claims the passages it was given support.

Calibration (evals/human_grades.jsonl): answers a person graded; the judge grades the same
texts and its agreement with the person is reported, so the judge's scores mean something.
"""

import hashlib
import json
import logging
import re
import statistics
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

import openai

from extraction.collect import write_file
from rag.answer import Answer, Rag, load_prompt, render
from rag.config import EVALS, RagConfig
from rag.llm import OpenRouter
from rag.search import Filters, Retriever

log = logging.getLogger(__name__)
VERDICTS = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {"type": "string"},
        "verdict": {"type": "string", "enum": list(VERDICTS)},
    },
    "required": ["reason", "verdict"],
    "additionalProperties": False,
}
FAITHFULNESS_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "supported": {"type": "boolean"},
                    "passage": {"type": "integer"},
                },
                "required": ["claim", "supported", "passage"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["claims"],
    "additionalProperties": False,
}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[\w$€₴+#.]+", text.lower()))


# --- retrieval --------------------------------------------------------------------------


def relevant(chunk, gold: list[dict]) -> bool:
    text = _norm(chunk.indexed)
    return any(chunk.doc_id == g["doc_id"] and _norm(g["quote"]) in text for g in gold)


def retrieval_run(retriever: Retriever, questions: list[dict], mode: str) -> dict:
    ranks = {}
    for q in questions:
        hits = retriever.search(
            q["question"], mode=mode, k=10, filters=Filters(**q.get("filters", {}))
        )
        ranks[q["id"]] = next(
            (i for i, h in enumerate(hits, 1) if relevant(h.chunk, q["gold"])), None
        )
    found = list(ranks.values())
    return {
        "recall": {
            k: statistics.mean(r is not None and r <= k for r in found) for k in (1, 3, 5, 10)
        },
        "mrr": statistics.mean(1 / r if r else 0.0 for r in found),
        "ranks": ranks,
    }


def retrieval_markdown(runs: dict[str, dict[str, dict]]) -> str:
    """runs[chunking][mode]"""
    lines = [
        "| Chunking | Search | recall@1 | recall@3 | recall@5 | recall@10 | MRR |",
        "|---|---|--:|--:|--:|--:|--:|",
    ]
    for chunking, modes in runs.items():
        for mode, run in modes.items():
            r = run["recall"]
            lines.append(
                f"| {chunking} | {mode} | {r[1]:.2f} | {r[3]:.2f} | {r[5]:.2f} | {r[10]:.2f}"
                f" | {run['mrr']:.2f} |"
            )
    return "\n".join(lines) + "\n"


# --- answers ----------------------------------------------------------------------------


@dataclass
class Scored:
    id: str
    type: str
    question: str
    expected: str
    answer: str
    abstained: bool
    reason: str
    sources: list[str]
    passages: list[str]  # chunk ids the model was given
    best_score: float | None
    latency_s: float
    abstention_ok: bool
    source_ok: bool | None  # None for unanswerable questions
    key_facts: float | None
    verdict: str | None = None
    judge_reason: str = ""
    faithfulness: float | None = None
    claims: list[dict] = field(default_factory=list)

    @property
    def answer_sha(self) -> str:
        return hashlib.sha256(self.answer.encode("utf-8")).hexdigest()[:12]


def score_answer(item: dict, answer: Answer) -> Scored:
    answerable = item["type"] != "unanswerable"
    text = _norm(answer.text)
    facts = item.get("key_facts") or []
    found = [any(_norm(alt) in text for alt in fact) for fact in facts]
    cited = set(answer.sources)
    return Scored(
        id=item["id"],
        type=item["type"],
        question=item["question"],
        expected=item["expected"],
        answer=answer.text,
        abstained=answer.abstained,
        reason=answer.reason,
        sources=answer.sources,
        passages=[p.chunk.chunk_id for p in answer.passages],
        best_score=answer.best_score,
        latency_s=answer.latency_s,
        abstention_ok=answer.abstained != answerable,
        source_ok=(
            bool(cited & set(item["sources"]))
            and not cited & set(item.get("forbidden_sources", []))
            if answerable
            else None
        ),
        key_facts=(statistics.mean(found) if found else None) if answerable else None,
    )


class Judge:
    def __init__(self, config: RagConfig, client: OpenRouter) -> None:
        self.model, self.client = config.models.judge, client
        self.verdict_prompt = load_prompt("judge", config.prompts.judge)
        self.faithfulness_prompt = load_prompt("faithfulness", config.prompts.faithfulness)

    def verdict(self, question: str, expected: str, answer: str) -> dict:
        user = self.verdict_prompt.render(question=question, expected=expected, answer=answer)
        return self.client.chat(
            self.model,
            self.verdict_prompt.system,
            user,
            schema=JUDGE_SCHEMA,
            temperature=None,  # the judge's model takes none
            max_tokens=1000,
        )

    def faithfulness(self, answer: Answer) -> tuple[float | None, list[dict]]:
        if answer.abstained or not answer.passages:
            return None, []
        user = self.faithfulness_prompt.render(passages=render(answer.passages), answer=answer.text)
        result = self.client.chat(
            self.model,
            self.faithfulness_prompt.system,
            user,
            schema=FAITHFULNESS_SCHEMA,
            max_tokens=2500,
            temperature=None,
        )
        claims = result["claims"]
        return (statistics.mean(c["supported"] for c in claims) if claims else None), claims


def answer_run(rag: Rag, judge: Judge | None, items: list[dict]) -> list[Scored]:
    scored = []
    for item in items:
        answer = rag.ask(item["question"], Filters(**item.get("filters", {})))
        result = score_answer(item, answer)
        if judge is not None:
            try:  # a judge that fails leaves this answer unjudged, not the run broken
                verdict = judge.verdict(item["question"], item["expected"], answer.text)
                result.verdict, result.judge_reason = verdict["verdict"], verdict["reason"]
                result.faithfulness, result.claims = judge.faithfulness(answer)
            except (ValueError, KeyError, RuntimeError, openai.OpenAIError) as e:
                log.warning("%s: the judge failed: %s", item["id"], e)
                result.judge_reason = f"judge failed: {e}"
        scored.append(result)
    return scored


def answer_metrics(scored: list[Scored], rag: Rag) -> dict:
    answerable = [s for s in scored if s.type != "unanswerable"]
    unanswerable = [s for s in scored if s.type == "unanswerable"]
    traps = [s for s in scored if s.type == "trap"]

    def mean(values) -> float | None:
        values = [v for v in values if v is not None]
        return statistics.mean(values) if values else None

    latencies = sorted(s.latency_s for s in scored)
    usage = rag.client.usage.get(rag.config.models.answer)
    embed = rag.client.usage.get(rag.config.models.embeddings)
    cost = (usage.cost_usd if usage else 0) + (embed.cost_usd if embed else 0)
    return {
        "questions": len(scored),
        "by_type": dict(Counter(s.type for s in scored)),
        "source_accuracy": mean(s.source_ok for s in answerable),
        "trap_accuracy": mean(s.source_ok for s in traps),
        "abstention": mean(s.abstained for s in unanswerable),
        "false_abstention": mean(s.abstained for s in answerable),
        "key_facts": mean(s.key_facts for s in answerable),
        "judge_correct": mean(VERDICTS[s.verdict] for s in scored if s.verdict),
        "faithfulness": mean(s.faithfulness for s in scored),
        "latency_p50_s": statistics.median(latencies) if latencies else None,
        "latency_p95_s": latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))]
        if latencies
        else None,
        "cost_per_1k_questions_usd": 1000 * cost / len(scored) if scored else None,
    }


def answers_markdown(rows: list[dict], metrics: dict) -> str:
    """The run as Markdown: the metrics, then every answer with its checks."""

    def number(value) -> str:
        return "–" if value is None else f"{value:.2f}" if isinstance(value, float) else str(value)

    names = [
        "source_accuracy", "trap_accuracy", "abstention", "false_abstention", "key_facts",
        "judge_correct", "faithfulness", "latency_p50_s", "latency_p95_s",
        "cost_per_1k_questions_usd", "judge_cost_per_1k_questions_usd",
    ]  # fmt: skip
    lines = ["# Answers", "", "| Metric | Value |", "|---|--:|"]
    lines += [f"| {name} | {number(metrics.get(name))} |" for name in names]
    lines += [
        "",
        "| Id | Type | Abstained | Right source | Key facts | Judge | Faithful | Answer |",
        "|---|---|---|---|--:|---|--:|---|",
    ]
    for row in rows:
        answer = " ".join(row["answer"].split()).replace("|", "/")
        ok = {True: "yes", False: "**no**", None: "–"}
        lines.append(
            f"| {row['id']} | {row['type']} | {'yes' if row['abstained'] else 'no'}"
            f" | {ok[row['source_ok']]} | {number(row['key_facts'])} | {row['verdict'] or '–'}"
            f" | {number(row['faithfulness'])} | {answer[:300]} |"
        )
    return "\n".join(lines) + "\n"


# --- calibration ------------------------------------------------------------------------


def calibration(judge: Judge, grades: list[dict]) -> dict:
    """The judge on the answers a person graded: how often it gives the person's verdict."""
    pairs = []
    for row in grades:
        verdict = judge.verdict(row["question"], row["expected"], row["answer"])["verdict"]
        pairs.append({"id": row["id"], "human": row["verdict"], "judge": verdict})
    if not pairs:
        return {"graded": 0}
    agree = statistics.mean(p["human"] == p["judge"] for p in pairs)
    passed = statistics.mean((p["human"] == "correct") == (p["judge"] == "correct") for p in pairs)
    return {
        "graded": len(pairs),
        "agreement": agree,
        "agreement_correct_or_not": passed,
        "cohen_kappa": _kappa([p["human"] for p in pairs], [p["judge"] for p in pairs]),
        "confusion": dict(Counter(f"{p['human']} -> {p['judge']}" for p in pairs)),
        "pairs": pairs,
    }


def _kappa(a: list[str], b: list[str]) -> float | None:
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[label] * cb[label] for label in set(a) | set(b)) / n**2
    return None if expected == 1 else (observed - expected) / (1 - expected)


# --- reports ----------------------------------------------------------------------------


def write_results(folder: Path, name: str, data: dict | list, markdown: str | None = None) -> None:
    write_file(folder / f"{name}.json", json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    if markdown is not None:
        write_file(folder / f"{name}.md", markdown)


def scored_rows(scored: list[Scored]) -> list[dict]:
    return [{**asdict(s), "answer_sha": s.answer_sha} for s in scored]


def failures(metrics: dict, thresholds: dict[str, float]) -> list[str]:
    return [
        f"{name} {metrics.get(name)} < {floor}"
        for name, floor in thresholds.items()
        if metrics.get(name) is not None and metrics[name] < floor
    ]


EVALS_DIR = EVALS

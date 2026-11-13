"""`python main.py rag <command>`: the RAG's commands. `rag all` is what `make rag` and CI run;
`rag all --offline` is the part that needs no key (CI's first job)."""

import argparse
import json
import logging
import sys
from collections.abc import Callable
from dataclasses import replace
from functools import cache

from rag import config as paths
from rag.answer import Rag
from rag.config import RagConfig, load
from rag.context import Contextualizer
from rag.corpus_files import build, read_chunks
from rag.evaluate import (
    Judge,
    answer_metrics,
    answer_run,
    answers_markdown,
    calibration,
    failures,
    read_jsonl,
    retrieval_markdown,
    retrieval_run,
    scored_rows,
    write_results,
)
from rag.llm import OpenRouter
from rag.prompts import load_prompt
from rag.search import MODES, CrossEncoder, Embeddings, Filters, Retriever

log = logging.getLogger(__name__)
RESULTS = paths.EVALS / "results"
# The indexes retrieval is measured on: each chunking, with and without the chunks' contexts.
INDEXES = {
    "structural + context": ("structural", True),
    "structural": ("structural", False),
    "fixed + context": ("fixed", True),
    "fixed": ("fixed", False),
}


def main(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    if args.command is None:
        args = _parser().parse_args(["all"])
    return args.handler(load(), args)


def retriever(
    config: RagConfig,
    chunking: str = "structural",
    *,
    context: bool | None = None,
    vectors: bool = True,
    client: OpenRouter | None = None,
) -> Retriever:
    """The search over one chunking; with the chunks' contexts as rag.yaml says, unless
    `context` says otherwise."""
    chunks = read_chunks(chunking)
    if not (config.search.context if context is None else context):
        chunks = [replace(chunk, context="") for chunk in chunks]
    embeddings = (
        Embeddings(config.models.embeddings, paths.DATA / "embeddings.jsonl", client)
        if vectors
        else None
    )
    return Retriever(
        chunks,
        embeddings,
        _reranker(config.models.reranker),
        candidates=config.search.candidates,
        rerank_top=config.search.rerank_top,
        rrf_k=config.search.rrf_k,
    )


@cache
def _reranker(model: str) -> CrossEncoder:
    """One cross-encoder for every index: the model loads once."""
    return CrossEncoder(model)


def index_name(config: RagConfig) -> str:
    """The index rag.yaml chooses, as named in the retrieval results."""
    return "structural + context" if config.search.context else "structural"


def contextualizer(config: RagConfig, client: OpenRouter | None = None) -> Contextualizer:
    prompt = load_prompt("context", config.prompts.context)
    return Contextualizer(config.models.context, prompt, paths.DATA / "contexts.jsonl", client)


def _ingest(config: RagConfig, args: argparse.Namespace) -> None:
    manifest = build(contextualize=contextualizer(config))
    summary = {k: v for k, v in manifest.items() if k != "documents"}
    log.info("%s", json.dumps(summary, ensure_ascii=False))


def _filters(args: argparse.Namespace) -> Filters:
    return Filters(
        kind=args.kind, since=args.since, company=args.company, current_only=not args.all_versions
    )


def _search(config: RagConfig, args: argparse.Namespace) -> None:
    found = retriever(config, args.chunking, vectors=args.mode != "bm25")
    for hit in found.search(args.query, mode=args.mode, k=args.k, filters=_filters(args)):
        print(f"{hit.score:7.3f}  {hit.chunk.chunk_id:22} {hit.ranks}  {hit.chunk.header}")


def _ask(config: RagConfig, args: argparse.Namespace) -> None:
    client = OpenRouter()
    answer = Rag(config, retriever(config, client=client), client).ask(
        args.question, _filters(args)
    )
    print(answer.text, "\n")
    for p in answer.passages:
        mark = "*" if p in answer.cited else " "
        print(f" {mark}[{p.number}] {p.score:.3f} {p.chunk.chunk_id}: {p.chunk.header}")


def _eval_retrieval(config: RagConfig, args: argparse.Namespace) -> dict:
    questions = read_jsonl(paths.EVALS / "retrieval.jsonl")
    modes = MODES if args.vectors else ("bm25",)
    runs = {}
    for name, (chunking, context) in INDEXES.items():
        found = retriever(config, chunking, context=context, vectors=args.vectors)
        runs[name] = {mode: retrieval_run(found, questions, mode) for mode in modes}
    write_results(RESULTS, "retrieval", runs, retrieval_markdown(runs))
    log.info("%s", retrieval_markdown(runs))
    return runs


def _eval_answers(config: RagConfig, args: argparse.Namespace) -> dict:
    client = OpenRouter()
    rag = Rag(config, retriever(config, client=client), client)
    judge = None if args.no_judge else Judge(config, client)
    scored = answer_run(rag, judge, read_jsonl(paths.EVALS / "testset.jsonl"))
    metrics = answer_metrics(scored, rag)
    judge_usage = client.usage.get(config.models.judge)
    metrics["judge_cost_per_1k_questions_usd"] = (
        1000 * judge_usage.cost_usd / len(scored) if judge_usage and scored else None
    )
    metrics["prompts"] = {
        "answer": rag.prompt.version,
        "judge": config.prompts.judge,
        "faithfulness": config.prompts.faithfulness,
        "context": config.prompts.context if config.search.context else None,
    }
    rows = scored_rows(scored)
    write_results(RESULTS, "answers", rows, answers_markdown(rows, metrics))
    write_results(RESULTS, "metrics", metrics)
    log.info("%s", json.dumps(metrics, ensure_ascii=False, indent=2))
    return metrics


def _calibrate(config: RagConfig, args: argparse.Namespace) -> dict:
    path = paths.EVALS / "human_grades.jsonl"
    grades = read_jsonl(path) if path.exists() else []
    report = calibration(Judge(config, OpenRouter()), grades)
    write_results(RESULTS, "calibration", report)
    log.info("judge vs person: %s", {k: v for k, v in report.items() if k != "pairs"})
    return report


def _grade(config: RagConfig, args: argparse.Namespace) -> None:
    """Grade the latest run's answers by hand, in the terminal: the judge's calibration."""
    path = paths.EVALS / "human_grades.jsonl"
    done = {row["id"] for row in read_jsonl(path)} if path.exists() else set()
    keys = {"c": "correct", "p": "partial", "i": "incorrect"}
    for row in json.loads((RESULTS / "answers.json").read_text("utf-8")):
        if row["id"] in done:
            continue
        print(f"\n{row['id']} ({row['type']}) {row['question']}")
        print(f"  expected: {row['expected']}\n  answer:   {row['answer']}")
        key = input("  [c]orrect, [p]artial, [i]ncorrect, [s]kip, [q]uit: ").strip().lower()[:1]
        if key == "q":
            break
        if key in keys:
            graded = {k: row[k] for k in ("id", "question", "expected", "answer")}
            with path.open("a", encoding="utf-8") as file:
                file.write(json.dumps({**graded, "verdict": keys[key]}, ensure_ascii=False) + "\n")


def _all(config: RagConfig, args: argparse.Namespace) -> int:
    """Everything, then the thresholds: exits 1 if a metric is below its threshold. Offline,
    only what needs no key: ingestion and retrieval, from the committed caches."""
    _ingest(config, args)
    runs = _eval_retrieval(config, args)
    metrics = {"recall_at_5": runs[index_name(config)][config.search.mode]["recall"][5]}
    if not args.offline:
        metrics = _eval_answers(config, args) | metrics
        metrics["judge_agreement"] = _calibrate(config, args).get("agreement")
        write_results(RESULTS, "metrics", metrics)
    failed = failures(metrics, config.thresholds)
    for line in failed:
        log.error("below the threshold: %s", line)
    log.info("%d metrics checked, %d below their thresholds", len(metrics), len(failed))
    return 1 if failed else 0


def _command(step: Callable[[RagConfig, argparse.Namespace], object]) -> Callable[..., int]:
    """A step as a command: it ran, so it exits 0."""

    def run(config: RagConfig, args: argparse.Namespace) -> int:
        step(config, args)
        return 0

    return run


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python main.py rag", description=__doc__)
    commands = parser.add_subparsers(dest="command", metavar="command")
    commands.add_parser(
        "ingest", help="raw files to documents, chunks with their contexts, and the manifest"
    ).set_defaults(handler=_command(_ingest))
    for name, handler, what in (("search", _search, "query"), ("ask", _ask, "question")):
        sub = commands.add_parser(name, help=f"{name} the corpus")
        sub.add_argument(what)
        sub.add_argument("--kind", choices=["posting", "official"])
        sub.add_argument("--since", help="earliest date, YYYY-MM-DD")
        sub.add_argument("--company")
        sub.add_argument("--all-versions", action="store_true", help="include superseded versions")
        if name == "search":
            sub.add_argument("--mode", choices=MODES, default="rerank")
            sub.add_argument("--k", type=int, default=5)
            sub.add_argument("--chunking", choices=["structural", "fixed"], default="structural")
        sub.set_defaults(handler=_command(handler))
    retrieval = commands.add_parser(
        "eval-retrieval", help="recall@k and MRR: every search mode, chunking and context"
    )
    retrieval.add_argument("--bm25-only", dest="vectors", action="store_false")
    retrieval.set_defaults(handler=_command(_eval_retrieval))
    answers = commands.add_parser("eval", help="answer the test set and score the answers")
    answers.add_argument("--no-judge", action="store_true")
    answers.set_defaults(handler=_command(_eval_answers))
    commands.add_parser("calibrate", help="the judge against the hand grades").set_defaults(
        handler=_command(_calibrate)
    )
    commands.add_parser("grade", help="grade the latest answers by hand").set_defaults(
        handler=_command(_grade)
    )
    every = commands.add_parser("all", help="ingest, evaluate, check the thresholds (CI)")
    every.add_argument(
        "--offline", action="store_true", help="only ingestion and retrieval: no key needed"
    )
    every.set_defaults(handler=_all, vectors=True, no_judge=False)
    return parser


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main(sys.argv[1:]))

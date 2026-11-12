"""`python main.py rag <command>`: the RAG's commands. `rag all` is what `make rag` and CI run."""

import argparse
import json
import logging
import sys

from rag import config as paths
from rag.answer import Rag
from rag.config import RagConfig, load
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
from rag.search import MODES, CrossEncoder, Embeddings, Filters, Retriever

log = logging.getLogger(__name__)
RESULTS = paths.EVALS / "results"


def main(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    if args.command is None:
        args = _parser().parse_args(["all"])
    return args.handler(load(), args)


def retriever(config: RagConfig, chunking: str = "structural", *, vectors: bool = True,
              client: OpenRouter | None = None) -> Retriever:  # fmt: skip
    embeddings = (
        Embeddings(config.models.embeddings, paths.DATA / "embeddings.jsonl", client)
        if vectors
        else None
    )
    return Retriever(
        read_chunks(chunking),
        embeddings,
        CrossEncoder(config.models.reranker),
        candidates=config.search.candidates,
        rerank_top=config.search.rerank_top,
        rrf_k=config.search.rrf_k,
    )


def _ingest(config: RagConfig, args: argparse.Namespace) -> int:
    manifest = build()
    log.info(
        "%s",
        json.dumps({k: v for k, v in manifest.items() if k != "documents"}, ensure_ascii=False),
    )
    return 0


def _filters(args: argparse.Namespace) -> Filters:
    return Filters(
        kind=args.kind, since=args.since, company=args.company, current_only=not args.all_versions
    )


def _search(config: RagConfig, args: argparse.Namespace) -> int:
    found = retriever(config, args.chunking, vectors=args.mode != "bm25")
    for hit in found.search(args.query, mode=args.mode, k=args.k, filters=_filters(args)):
        print(f"{hit.score:7.3f}  {hit.chunk.chunk_id:22} {hit.ranks}  {hit.chunk.header}")
    return 0


def _ask(config: RagConfig, args: argparse.Namespace) -> int:
    client = OpenRouter()
    answer = Rag(config, retriever(config, client=client), client).ask(
        args.question, _filters(args)
    )
    print(answer.text, "\n")
    for p in answer.passages:
        mark = "*" if p in answer.cited else " "
        print(f" {mark}[{p.number}] {p.score:.3f} {p.chunk.chunk_id}: {p.chunk.header}")
    return 0


def _eval_retrieval(config: RagConfig, args: argparse.Namespace) -> dict:
    questions = read_jsonl(paths.EVALS / "retrieval.jsonl")
    modes = MODES if args.vectors else ("bm25",)
    runs = {}
    for chunking in ("structural", "fixed"):
        found = retriever(config, chunking, vectors=args.vectors)
        runs[chunking] = {mode: retrieval_run(found, questions, mode) for mode in modes}
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
    metrics["prompts"] = {"answer": rag.prompt.version, "judge": config.prompts.judge}
    rows = scored_rows(scored)
    write_results(RESULTS, "answers", rows, answers_markdown(rows, metrics))
    write_results(RESULTS, "metrics", metrics)
    log.info("%s", json.dumps(metrics, ensure_ascii=False, indent=2))
    return metrics


def _calibrate(config: RagConfig, args: argparse.Namespace) -> dict:
    grades = (
        read_jsonl(paths.EVALS / "human_grades.jsonl")
        if (paths.EVALS / "human_grades.jsonl").exists()
        else []
    )
    report = calibration(Judge(config, OpenRouter()), grades)
    write_results(RESULTS, "calibration", report)
    log.info("judge vs person: %s", {k: v for k, v in report.items() if k != "pairs"})
    return report


def _grade(config: RagConfig, args: argparse.Namespace) -> int:
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
    return 0


def _all(config: RagConfig, args: argparse.Namespace) -> int:
    _ingest(config, args)
    runs = _eval_retrieval(config, args)
    metrics = _eval_answers(config, args)
    mode = config.search.mode
    metrics["recall_at_5"] = runs["structural"][mode]["recall"][5]
    report = _calibrate(config, args)
    metrics["judge_agreement"] = report.get("agreement")
    write_results(RESULTS, "metrics", metrics)
    failed = failures(metrics, config.thresholds)
    for line in failed:
        log.error("below the threshold: %s", line)
    return 1 if failed else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python main.py rag", description=__doc__)
    commands = parser.add_subparsers(dest="command", metavar="command")
    commands.add_parser(
        "ingest", help="raw files to documents, chunks and the manifest"
    ).set_defaults(handler=_ingest)
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
        sub.set_defaults(handler=handler)
    retrieval = commands.add_parser(
        "eval-retrieval", help="recall@k and MRR, every mode and chunking"
    )
    retrieval.add_argument("--bm25-only", dest="vectors", action="store_false")
    retrieval.set_defaults(handler=lambda c, a: (_eval_retrieval(c, a), 0)[1])
    answers = commands.add_parser("eval", help="answer the test set and score the answers")
    answers.add_argument("--no-judge", action="store_true")
    answers.set_defaults(handler=lambda c, a: (_eval_answers(c, a), 0)[1])
    commands.add_parser("calibrate", help="the judge against the hand grades").set_defaults(
        handler=lambda c, a: (_calibrate(c, a), 0)[1]
    )
    commands.add_parser("grade", help="grade the latest answers by hand").set_defaults(
        handler=_grade
    )
    every = commands.add_parser("all", help="ingest, evaluate, check the thresholds (CI)")
    every.set_defaults(handler=_all, vectors=True, no_judge=False)
    return parser


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main(sys.argv[1:]))

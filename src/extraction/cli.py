"""Command line. `python main.py` with no command runs the whole experiment (= `run`)."""

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from extraction.collect.djinni_archive import FIRST_YEAR, captures, crawl_archive
from extraction.collect.djinni_ids import FIRST_2025, crawl_ids, listed
from extraction.collect.djinni_jobs import crawl_jobs, discover
from extraction.collect.polite import FetchError, PoliteClient
from extraction.collect.postings import build_postings
from extraction.config import Config, load_config
from extraction.data import golden_paths, load_documents
from extraction.evaluate import evaluate, render_markdown
from extraction.labelling import DEFAULT_PORT, LabelStore, serve
from extraction.pipeline import extract
from extraction.prompts import load_prompt
from extraction.providers import ProviderError, create_provider
from extraction.runner import plan, run_all
from extraction.schemas import SCHEMAS

log = logging.getLogger("extraction")

MIN_TEXTS, MIN_GOLDEN = 30, 10  # the homework's minimum, across doc types


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # otherwise a line per HTTP request
    parser = _parser()
    argv = sys.argv[1:] if argv is None else argv
    args = parser.parse_args(argv)
    if args.command is None:
        args = parser.parse_args([*argv, "run"])
    try:
        config = load_config(Path(args.config))
        return args.handler(config, args)
    except (ValidationError, ValueError, FileNotFoundError) as e:
        log.error("error: %s", e)
        return 2


def _run(config: Config, args: argparse.Namespace) -> int:
    runs = plan(
        config,
        doc_types=args.doc_types,
        models=args.models,
        prompts=args.prompts,
        sampling=args.sampling,
    )
    all_done = run_all(config, runs, limit=args.limit, force=args.force)
    if not args.no_eval:
        _eval(config, args)
    return 0 if all_done else 1


def _eval(config: Config, args: argparse.Namespace) -> int:
    metrics = evaluate(config)
    if not metrics:
        log.warning("no results in %s yet - run `python main.py run`", config.results_dir / "runs")
        return 1
    print(render_markdown(metrics))
    log.info("wrote results/metrics.md, results/metrics.json, results/mismatches.csv")
    return 0


def _extract(config: Config, args: argparse.Namespace) -> int:
    path = Path(args.path)
    doc_type = args.doc_type or path.parent.name
    if doc_type not in SCHEMAS:
        log.error("can't tell the doc type from %s; pass --doc-type", path)
        return 2
    model_name = args.model or config.experiment.models[0]
    sampling_name = args.sampling or config.experiment.sampling[0]
    if model_name not in config.models or sampling_name not in config.sampling:
        log.error("unknown model %r or sampling %r", model_name, sampling_name)
        return 2
    prompt = load_prompt(config.prompts_dir, doc_type, args.prompt or config.experiment.prompts[-1])
    try:
        provider = create_provider(config.models[model_name])
        provider.warm_up()
        outcome = extract(
            path.read_text(encoding="utf-8"),
            provider=provider,
            prompt=prompt,
            schema_model=SCHEMAS[doc_type],
            sampling=config.sampling[sampling_name].params(),
            retry=config.retry,
        )
    except ProviderError as e:
        log.error("%s", e)
        return 1
    for number, attempt in enumerate(outcome.attempts, 1):
        log.info(
            "attempt %d: %.1fs, %d tokens in, %d out, cost %s",
            *(number, attempt.latency_ms / 1000, attempt.input_tokens, attempt.output_tokens),
            attempt.cost_usd,
        )
        for error in attempt.errors:
            log.info("  invalid: %s", error)
    log.info("%s / %s / prompt %s: %s", model_name, sampling_name, prompt.version, outcome.status)
    if outcome.output is not None:
        print(json.dumps(outcome.output, indent=2, ensure_ascii=False))
        return 0
    print(outcome.attempts[-1].raw_output if outcome.attempts else outcome.error)
    return 1


def _check(config: Config, args: argparse.Namespace) -> int:
    problems = []
    total_texts = total_golden = 0
    for doc_type, schema in SCHEMAS.items():
        texts = {doc.doc_id for doc in load_documents(config.data_dir, doc_type)}
        golden = golden_paths(config.data_dir, doc_type)
        for path in golden:
            try:
                schema.model_validate_json(path.read_bytes())
            except ValidationError as e:
                problems.append(f"{path.relative_to(config.data_dir)}: {e}")
            if path.stem not in texts:
                problems.append(f"{path.relative_to(config.data_dir)}: no matching text")
        versions = sorted(path.stem for path in (config.prompts_dir / doc_type).glob("*.yaml"))
        log.info(
            "%-4s %3d texts, %3d golden, prompts: %s",
            *(doc_type, len(texts), len(golden), ", ".join(versions) or "none"),
        )
        total_texts += len(texts)
        total_golden += len(golden)
    if total_texts < MIN_TEXTS or total_golden < MIN_GOLDEN:
        log.info(
            "homework minimum is %d texts with %d golden; have %d with %d",
            *(MIN_TEXTS, MIN_GOLDEN, total_texts, total_golden),
        )
    for problem in problems:
        log.error("%s", problem)
    return 1 if problems else 0


def _label(config: Config, args: argparse.Namespace) -> int:
    store = LabelStore(config.data_dir)
    if not store.order:
        log.error("no texts to label in data/texts/job/")
        return 1
    serve(store, port=args.port, open_browser=not args.no_browser)
    return 0


def _crawl_jobs(config: Config, args: argparse.Namespace) -> int:
    try:
        saved = crawl_jobs(
            config.data_dir, count=args.count, keywords=args.keywords, delay_s=args.delay
        )
    except FetchError as e:
        log.error("crawl stopped: %s", e)
        return 1
    log.info("saved %d new postings: data/texts/job/ and data/scraped/job/", saved)
    return 0


def _crawl_archive(config: Config, args: argparse.Namespace) -> int:
    try:
        postings, fetched = crawl_archive(
            config.data_dir.parent / ".cache" / "wayback",
            years=args.years or range(FIRST_YEAR, date.today().year + 1),
            keyword=args.keyword,
            limit=args.limit,
            delay_s=args.delay,
        )
    except FetchError as e:
        log.error("crawl stopped: %s", e)
        return 1
    log.info(
        "fetched %d pages into .cache/wayback/pages/ (%d postings in the archive)",
        fetched,
        postings,
    )
    return 0


def _crawl_djinni(config: Config, args: argparse.Namespace) -> int:
    first, last = args.ids
    urls: dict[int, str] = {}
    try:
        with PoliteClient(delay_s=args.delay) as client:
            if last is None:  # up to the newest posting
                last = max(int(item.job_id) for item in discover(client))
            if args.keyword:  # the open postings Djinni lists, and the ones the archive has
                urls = _archived_urls(config, args.keyword) | listed(client, args.keyword)
        ids = range(first, last + 1)
        if args.keyword:
            ids = sorted(job_id for job_id in urls if first <= job_id <= last)
            log.info(
                "%d %s postings to look at, from Djinni's list and the archive",
                len(ids),
                args.keyword,
            )
        fetched = crawl_ids(
            config.data_dir.parent / ".cache" / "djinni",
            ids,
            urls=urls,
            workers=args.workers,
            delay_s=args.delay,
            limit=args.limit,
        )
    except FetchError as e:
        log.error("crawl stopped: %s", e)
        return 1
    log.info("fetched %d pages into .cache/djinni/pages/ (ids %d to %d)", fetched, first, last)
    return 0


def _archived_urls(config: Config, keyword: str) -> dict[int, str]:
    """Postings with the keyword in their slug that the archive's index lists (crawl-archive
    --keyword), at their djinni.co URLs."""
    cache = config.data_dir.parent / ".cache" / "wayback"
    lines = [
        line
        for path in cache.glob(f"{keyword.lower()}-*.txt")
        for line in path.read_text().splitlines()
    ]
    return {job_id: group[0].url.split("?")[0] for job_id, group in captures(lines).items()}


def _build_postings(config: Config, args: argparse.Namespace) -> int:
    years = build_postings(
        config.data_dir.parent / ".cache" / "wayback",
        config.data_dir.parent / ".cache" / "djinni",
        config.data_dir / "scraped" / "job",
        config.data_dir / "postings",
    )
    counts = sorted(years.items(), key=lambda item: item[0] or 0)
    log.info("postings: %s", ", ".join(f"{year or 'undated'} {count}" for year, count in counts))
    log.info("%d in data/postings/<year>.jsonl", sum(years.values()))
    return 0


def _names(value: str) -> list[str]:
    return [name.strip() for name in value.split(",") if name.strip()]


def _id_range(value: str) -> tuple[int, int | None]:
    """ "700000-854901", or "700000-" for up to the newest posting."""
    first, _, last = value.partition("-")
    return int(first), int(last) if last else None


def _years(value: str) -> range:
    """ "2019-2026" or "2021"."""
    first, _, last = value.partition("-")
    return range(int(first), int(last or first) + 1)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="Structured extraction from Djinni job postings and CVs.",
    )
    parser.add_argument("--config", default="config.yaml", help="default: %(default)s")
    commands = parser.add_subparsers(dest="command", metavar="command")

    run = commands.add_parser("run", help="run every experiment in the config, then score them")
    run.add_argument("--doc-types", type=_names, help="comma-separated subset, e.g. job")
    run.add_argument("--models", type=_names, help="comma-separated model names from the config")
    run.add_argument("--prompts", type=_names, help="comma-separated prompt versions")
    run.add_argument("--sampling", type=_names, help="comma-separated sampling profiles")
    run.add_argument("--limit", type=int, help="only the first N texts per doc type")
    run.add_argument("--force", action="store_true", help="ignore stored results, call again")
    run.add_argument("--no-eval", action="store_true", help="don't score after running")
    run.set_defaults(handler=_run)

    evaluate_ = commands.add_parser("eval", help="score stored results (no model calls)")
    evaluate_.set_defaults(handler=_eval)

    one = commands.add_parser("extract", help="extract one text file and print the JSON")
    one.add_argument("path")
    one.add_argument("--doc-type", choices=sorted(SCHEMAS), help="default: the folder's name")
    one.add_argument("--model", help="default: the first of experiment.models")
    one.add_argument("--prompt", help="default: the last of experiment.prompts")
    one.add_argument("--sampling", help="default: the first of experiment.sampling")
    one.set_defaults(handler=_extract)

    check = commands.add_parser("check", help="count texts and labels, validate the golden set")
    check.set_defaults(handler=_check)

    label = commands.add_parser("label", help="write the golden labels in a local web page")
    label.add_argument("--port", type=int, default=DEFAULT_PORT, help="(default: %(default)s)")
    label.add_argument("--no-browser", action="store_true", help="don't open the page")
    label.set_defaults(handler=_label)

    jobs = commands.add_parser("crawl-jobs", help="collect public job postings from djinni.co")
    jobs.add_argument("--count", type=int, default=20, help="new postings to save (%(default)s)")
    jobs.add_argument(
        "--keywords", type=_names, help="Djinni categories, e.g. 'Python,QA Automation'"
    )
    jobs.add_argument(
        "--delay", type=float, default=3.0, help="seconds between requests (%(default)s)"
    )
    jobs.set_defaults(handler=_crawl_jobs)

    archive = commands.add_parser(
        "crawl-archive", help="collect past years' postings from the Wayback Machine"
    )
    archive.add_argument("--keyword", help="only URLs with it in the slug, e.g. python")
    archive.add_argument(
        "--years", type=_years, help=f"a range or one year (default: {FIRST_YEAR} to this year)"
    )
    archive.add_argument("--limit", type=int, help="stop after this many new postings")
    archive.add_argument(
        "--delay", type=float, default=5.0, help="seconds between requests (%(default)s)"
    )
    archive.set_defaults(handler=_crawl_archive)

    djinni = commands.add_parser(
        "crawl-djinni", help="fetch every posting in a range of job ids from djinni.co"
    )
    djinni.add_argument(
        "--ids",
        type=_id_range,
        default=f"{FIRST_2025}-",
        help="first-last job id; first- for up to the newest (default: %(default)s, 2025 on)",
    )
    djinni.add_argument("--workers", type=int, default=1, help="requests at a time (%(default)s)")
    djinni.add_argument(
        "--delay",
        type=float,
        default=3.0,
        help="seconds between a worker's requests (%(default)s); Djinni blocks IPs that rush",
    )
    djinni.add_argument(
        "--keyword", help="only these postings, e.g. Python: Djinni's list and the archive's"
    )
    djinni.add_argument("--limit", type=int, help="stop after this many ids")
    djinni.set_defaults(handler=_crawl_djinni)

    postings = commands.add_parser(
        "build-postings", help="every collected posting in one format: data/postings/<year>.jsonl"
    )
    postings.set_defaults(handler=_build_postings)
    return parser

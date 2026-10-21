"""Runs the experiment matrix and keeps one stored result per document and run.

A run is one (doc type, model, prompt version, sampling) combination and owns
results/runs/<doc_type>__<model>__<prompt>__<sampling>.jsonl. A stored result is reused when
it came from the same text, prompt file, schema, model and sampling, so adding a prompt
version or a few documents only calls the models for what is new. Provider errors are never
reused, and `--force` ignores stored results altogether.
"""

import hashlib
import json
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from extraction.config import Config, ModelConfig, Sampling
from extraction.data import Document, load_documents
from extraction.pipeline import extract
from extraction.prompts import Prompt, load_prompt
from extraction.providers import Provider, ProviderError, create_provider
from extraction.results import ExtractionResult, read_results, write_results
from extraction.schemas import SCHEMAS, json_schema

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Run:
    doc_type: str
    model_name: str
    model: ModelConfig
    prompt: Prompt
    sampling_name: str
    sampling: Sampling

    @property
    def name(self) -> str:
        return f"{self.doc_type}__{self.model_name}__{self.prompt.version}__{self.sampling_name}"


def plan(
    config: Config,
    *,
    doc_types: list[str] | None = None,
    models: list[str] | None = None,
    prompts: list[str] | None = None,
    sampling: list[str] | None = None,
) -> list[Run]:
    """Every combination of the given names; each list defaults to config.yaml's experiment."""
    experiment = config.experiment
    doc_types = _known(doc_types or experiment.doc_types, list(SCHEMAS), "doc type")
    models = _known(models or experiment.models, list(config.models), "model")
    sampling = _known(sampling or experiment.sampling, list(config.sampling), "sampling")
    runs = []
    for doc_type in doc_types:
        for version in prompts or experiment.prompts:
            prompt = load_prompt(config.prompts_dir, doc_type, version)
            for model_name in models:
                for sampling_name in sampling:
                    model, profile = config.models[model_name], config.sampling[sampling_name]
                    runs.append(Run(doc_type, model_name, model, prompt, sampling_name, profile))
    return runs


def run_all(
    config: Config, runs: list[Run], *, limit: int | None = None, force: bool = False
) -> bool:
    """Execute the runs in order. Returns False if any of them was skipped or stopped."""
    providers: dict[str, Provider | ProviderError] = {}
    all_done = True
    for run in runs:
        if run.model_name not in providers:
            providers[run.model_name] = _start(run.model)
            if isinstance(providers[run.model_name], ProviderError):
                log.error("%s is unavailable: %s", run.model_name, providers[run.model_name])
        provider = providers[run.model_name]
        if isinstance(provider, ProviderError):
            log.error("%s: skipped", run.name)
            all_done = False
            continue
        try:
            _execute(config, run, provider, limit=limit, force=force)
        except ProviderError as e:
            log.error("%s: stopped - %s", run.name, e)
            all_done = False
    return all_done


def _known(names: list[str], known: list[str], what: str) -> list[str]:
    unknown = [name for name in names if name not in known]
    if unknown:
        raise ValueError(f"unknown {what}: {', '.join(unknown)} (known: {', '.join(known)})")
    return names


def _start(model: ModelConfig) -> Provider | ProviderError:
    try:
        provider = create_provider(model)
        provider.warm_up()
    except ProviderError as e:
        return e
    return provider


def _execute(
    config: Config, run: Run, provider: Provider, *, limit: int | None, force: bool
) -> None:
    corpus = load_documents(config.data_dir, run.doc_type)
    if not corpus:
        log.warning("%s: no texts in data/texts/%s/", run.name, run.doc_type)
        return
    path = config.results_dir / "runs" / f"{run.name}.jsonl"
    schema_model = SCHEMAS[run.doc_type]
    schema_sha = _sha(json.dumps(json_schema(schema_model), sort_keys=True))
    in_corpus = {doc.doc_id for doc in corpus}
    stored = {} if force else read_results(path)
    results = {doc_id: result for doc_id, result in stored.items() if doc_id in in_corpus}
    todo = corpus[:limit]
    counts: Counter[str] = Counter()
    log.info("%s (%d docs)", run.name, len(todo))
    for number, doc in enumerate(todo, 1):
        previous = results.get(doc.doc_id)
        if previous and _reusable(previous, run, doc, schema_sha):
            counts["reused"] += 1
            continue
        outcome = extract(
            doc.text,
            provider=provider,
            prompt=run.prompt,
            schema_model=schema_model,
            sampling=run.sampling.params(),
            retry=config.retry,
        )
        result = ExtractionResult(
            run=run.name,
            doc_id=doc.doc_id,
            doc_type=run.doc_type,
            model=run.model_name,
            provider=run.model.provider,
            model_id=run.model.model,
            prompt_version=run.prompt.version,
            prompt_sha=run.prompt.sha,
            schema_sha=schema_sha,
            text_sha=doc.sha,
            sampling_name=run.sampling_name,
            sampling=run.sampling.params(),
            status=outcome.status,
            output=outcome.output,
            error=outcome.error,
            attempts=outcome.attempts,
            created_at=datetime.now(UTC),
        )
        results[doc.doc_id] = result
        counts[result.status] += 1
        log.info(
            "  %3d/%d  %-28s %-8s %5.1fs",
            *(number, len(todo), doc.doc_id, result.status, result.latency_ms / 1000),
        )
        _save(path, corpus, results)  # after every document, so an interrupted run resumes
    _save(path, corpus, results)
    summary = ", ".join(f"{status} {count}" for status, count in sorted(counts.items()))
    log.info("  -> %s", summary or "nothing to do")


def _save(path: Path, corpus: list[Document], results: dict[str, ExtractionResult]) -> None:
    write_results(path, [results[doc.doc_id] for doc in corpus if doc.doc_id in results])


def _reusable(result: ExtractionResult, run: Run, doc: Document, schema_sha: str) -> bool:
    return (
        result.status != "error"
        and result.text_sha == doc.sha
        and result.prompt_sha == run.prompt.sha
        and result.schema_sha == schema_sha
        and result.model_id == run.model.model
        and result.sampling == run.sampling.params()
    )


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]

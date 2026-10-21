"""Stored results: results/runs/<run>.jsonl, one ExtractionResult per line."""

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, computed_field

from extraction.pipeline import Attempt, Status


class ExtractionResult(BaseModel):
    """One document through one run, with what's needed to audit and reproduce it: model,
    prompt version and file hash, sampling parameters, and every raw answer."""

    run: str
    doc_id: str
    doc_type: str
    model: str  # name in config.yaml
    provider: str
    model_id: str  # the provider's name for it
    prompt_version: str
    prompt_sha: str
    schema_sha: str
    text_sha: str
    sampling_name: str
    sampling: dict[str, Any]
    status: Status
    output: dict[str, Any] | None
    error: str | None
    attempts: list[Attempt]
    created_at: datetime

    @computed_field
    @property
    def latency_ms(self) -> float:
        return round(sum(attempt.latency_ms for attempt in self.attempts), 1)

    @computed_field
    @property
    def input_tokens(self) -> int:
        return sum(attempt.input_tokens for attempt in self.attempts)

    @computed_field
    @property
    def output_tokens(self) -> int:
        return sum(attempt.output_tokens for attempt in self.attempts)

    @computed_field
    @property
    def cost_usd(self) -> float | None:
        costs = [attempt.cost_usd for attempt in self.attempts]
        return None if None in costs else sum(costs)


def read_results(path: Path) -> dict[str, ExtractionResult]:
    """Results by doc id; empty if the run hasn't been executed yet."""
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8").splitlines()
    results = (ExtractionResult.model_validate_json(line) for line in lines if line.strip())
    return {result.doc_id: result for result in results}


def write_results(path: Path, results: list[ExtractionResult]) -> None:
    """Replace the file in one step, so an interrupted run never leaves half a line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(result.model_dump_json() + "\n" for result in results), "utf-8")
    tmp.replace(path)

"""Scores stored results: validity, field accuracy on the golden set, latency and cost.

Every leaf field of the schema gets a score from 0 to 1 per golden document:
  - enums and numbers: exact match; null == null is a hit ("not stated" is an answer too);
  - free text: F1 over words ("Senior Python Developer" vs "Python Developer" = 0.8);
  - lists: F1 over normalised items ("Node.js" == "nodejs"; order doesn't matter);
  - nested objects are flattened ("salary.max_amount"); a null object has null leaves.
An answer that failed validation scores 0 on every field. A provider error (no answer at
all) is left out of accuracy and counted in the error rate instead.
"""

import csv
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from statistics import mean
from types import NoneType, UnionType
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel

from extraction.config import Config
from extraction.data import load_golden
from extraction.results import ExtractionResult, read_results
from extraction.schemas import SCHEMAS

Kind = Literal["exact", "text", "list"]


@dataclass
class RunMetrics:
    run: str
    doc_type: str
    model: str
    model_id: str
    prompt_version: str
    sampling_name: str
    sampling: dict[str, Any]
    docs: int
    valid: float  # schema-valid answer, first try or after the repair call
    first_pass: float  # valid without the repair call
    failed: float  # still invalid after the repair call
    errors: float  # the provider kept failing, no answer to judge
    golden_docs: int
    accuracy: float | None  # mean of the field accuracies
    field_accuracy: dict[str, float]
    latency_p50_s: float | None
    latency_p95_s: float | None
    cost_per_1k_docs_usd: float | None


@dataclass
class Mismatch:
    run: str
    doc_id: str
    field: str
    score: float
    expected: Any
    predicted: Any


def evaluate(config: Config) -> list[RunMetrics]:
    """Score every results/runs/*.jsonl; write metrics.md, metrics.json and mismatches.csv."""
    metrics: list[RunMetrics] = []
    mismatches: list[Mismatch] = []
    golden: dict[str, dict[str, BaseModel]] = {}
    for path in sorted((config.results_dir / "runs").glob("*.jsonl")):
        results = list(read_results(path).values())
        if not results:
            continue
        doc_type = results[0].doc_type
        if doc_type not in golden:
            golden[doc_type] = load_golden(config.data_dir, doc_type)
        run_metrics, run_mismatches = score_run(results, golden[doc_type], SCHEMAS[doc_type])
        metrics.append(run_metrics)
        mismatches += run_mismatches
    if metrics:
        _write_reports(config, metrics, mismatches)
    return metrics


def score_run(
    results: list[ExtractionResult],
    golden: dict[str, BaseModel],
    schema_model: type[BaseModel],
) -> tuple[RunMetrics, list[Mismatch]]:
    first = results[0]
    statuses = Counter(result.status for result in results)
    answered = [result for result in results if result.status != "error"]
    scored = [result for result in answered if result.doc_id in golden]
    fields = leaf_fields(schema_model)
    field_scores: dict[str, list[float]] = {path: [] for path, _ in fields}
    mismatches = []
    for result in scored:
        expected = golden[result.doc_id].model_dump(mode="json")
        if result.output is None:
            errors = "; ".join(result.attempts[-1].errors[:3])
            mismatches.append(
                Mismatch(result.run, result.doc_id, "*", 0.0, None, f"<{result.status}> {errors}")
            )
        for path, kind in fields:
            want, got = lookup(expected, path), lookup(result.output, path)
            value = score(kind, want, got) if result.output is not None else 0.0
            field_scores[path].append(value)
            if value < 1 and result.output is not None:
                mismatches.append(
                    Mismatch(result.run, result.doc_id, path, round(value, 2), want, got)
                )
    field_accuracy = {path: mean(values) for path, values in field_scores.items() if values}
    latencies = [result.latency_ms / 1000 for result in answered]
    costs = [result.cost_usd for result in answered]
    metrics = RunMetrics(
        run=first.run,
        doc_type=first.doc_type,
        model=first.model,
        model_id=first.model_id,
        prompt_version=first.prompt_version,
        sampling_name=first.sampling_name,
        sampling=first.sampling,
        docs=len(results),
        valid=(statuses["ok"] + statuses["repaired"]) / len(results),
        first_pass=statuses["ok"] / len(results),
        failed=statuses["failed"] / len(results),
        errors=statuses["error"] / len(results),
        golden_docs=len(scored),
        accuracy=mean(field_accuracy.values()) if field_accuracy else None,
        field_accuracy=field_accuracy,
        latency_p50_s=percentile(latencies, 50),
        latency_p95_s=percentile(latencies, 95),
        cost_per_1k_docs_usd=1000 * mean(costs) if costs and None not in costs else None,
    )
    return metrics, mismatches


def leaf_fields(model: type[BaseModel], prefix: str = "") -> list[tuple[str, Kind]]:
    """Dotted paths of the schema's leaf fields and how each one is scored."""
    fields: list[tuple[str, Kind]] = []
    for name, info in model.model_fields.items():
        annotation = _without_none(info.annotation)
        path = prefix + name
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            fields += leaf_fields(annotation, f"{path}.")
        elif get_origin(annotation) is list:
            fields.append((path, "list"))
        elif annotation is str:
            fields.append((path, "text"))
        else:
            fields.append((path, "exact"))
    return fields


def lookup(data: dict[str, Any] | None, path: str) -> Any:
    for key in path.split("."):
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def score(kind: Kind, expected: Any, predicted: Any) -> float:
    if kind == "list":
        return f1({_item(x) for x in expected or []}, {_item(x) for x in predicted or []})
    if kind == "text" and expected is not None and predicted is not None:
        return f1(set(_words(expected)), set(_words(predicted)))
    return float(expected == predicted)


def f1(expected: set[str], predicted: set[str]) -> float:
    if not expected and not predicted:
        return 1.0
    hits = len(expected & predicted)
    if not hits:
        return 0.0
    precision, recall = hits / len(predicted), hits / len(expected)
    return 2 * precision * recall / (precision + recall)


def percentile(values: list[float], q: float) -> float | None:
    """Linear interpolation between the closest ranks, like numpy's default."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def render_markdown(metrics: list[RunMetrics]) -> str:
    lines = [
        "# Metrics",
        "",
        "Generated by `python main.py eval` from `results/runs/` and `data/golden/`."
        " Definitions: README.md, section Metrics.",
    ]
    for doc_type in sorted({m.doc_type for m in metrics}):
        runs = [m for m in metrics if m.doc_type == doc_type]
        lines += [
            "",
            f"## {doc_type}",
            "",
            "| Model | Prompt | Sampling | Docs | Valid | 1st pass | Failed | Errors | Golden"
            " | Accuracy | p50, s | p95, s | $ / 1k docs |",
            "|---|---|---|" + "--:|" * 10,
        ]
        lines += [
            f"| {m.model} | {m.prompt_version} | {m.sampling_name} | {m.docs} | {_pct(m.valid)}"
            f" | {_pct(m.first_pass)} | {_pct(m.failed)} | {_pct(m.errors)} | {m.golden_docs}"
            f" | {_num(m.accuracy, 3)} | {_num(m.latency_p50_s, 1)} | {_num(m.latency_p95_s, 1)}"
            f" | {_num(m.cost_per_1k_docs_usd, 3)} |"
            for m in runs
        ]
        fields = list(dict.fromkeys(field for m in runs for field in m.field_accuracy))
        if fields:
            header = " | ".join(f"{m.model} {m.prompt_version} {m.sampling_name}" for m in runs)
            lines += ["", f"### Field accuracy: {doc_type}", "", f"| Field | {header} |"]
            lines.append("|---|" + "--:|" * len(runs))
            lines += [
                f"| {field} | "
                + " | ".join(_num(m.field_accuracy.get(field), 2) for m in runs)
                + " |"
                for field in fields
            ]
    return "\n".join(lines) + "\n"


def _write_reports(config: Config, metrics: list[RunMetrics], mismatches: list[Mismatch]) -> None:
    out = config.results_dir
    (out / "metrics.md").write_text(render_markdown(metrics), encoding="utf-8")
    report = json.dumps([asdict(m) for m in metrics], indent=2, ensure_ascii=False)
    (out / "metrics.json").write_text(report + "\n", encoding="utf-8")
    with (out / "mismatches.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["run", "doc_id", "field", "score", "expected", "predicted"])
        for m in mismatches:
            expected = json.dumps(m.expected, ensure_ascii=False)
            predicted = json.dumps(m.predicted, ensure_ascii=False)
            writer.writerow([m.run, m.doc_id, m.field, m.score, expected, predicted])


def _without_none(annotation: Any) -> Any:
    if get_origin(annotation) in (Union, UnionType):
        args = [arg for arg in get_args(annotation) if arg is not NoneType]
        if len(args) == 1:
            return args[0]
    return annotation


def _item(value: Any) -> str:
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return re.sub(r"[^\w+#]", "", str(value).casefold())


def _words(text: str) -> list[str]:
    return re.findall(r"[\w+#]+", text.casefold())


def _pct(value: float) -> str:
    return f"{value:.0%}"


def _num(value: float | None, digits: int) -> str:
    return "–" if value is None else f"{value:.{digits}f}"

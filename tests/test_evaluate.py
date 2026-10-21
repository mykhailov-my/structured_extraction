from datetime import UTC, datetime

import pytest

from extraction.evaluate import leaf_fields, percentile, score, score_run
from extraction.pipeline import Attempt
from extraction.results import ExtractionResult
from extraction.schemas import JobPosting

LABEL = {
    "title": "Python Developer",
    "seniority": "middle",
    "company_type": None,
    "domain": "fintech",
    "work_formats": ["remote"],
    "locations": ["Kyiv"],
    "min_experience_years": 3.0,
    "english_level": "b1",
    "salary": {"min_amount": 3000, "max_amount": None, "currency": "USD", "period": "month"},
    "must_have_skills": ["Python", "Django"],
    "nice_to_have_skills": [],
}


def _result(doc_id, status, output):
    attempt = Attempt(
        raw_output="",
        errors=[] if output else ["(root): Invalid JSON"],
        latency_ms=1000.0,
        retries=0,
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.0002,
        finish_reason="stop",
        served_by="test",
    )
    return ExtractionResult(
        run="job__m__v1__greedy",
        doc_id=doc_id,
        doc_type="job",
        model="m",
        provider="openrouter",
        model_id="vendor/m",
        prompt_version="v1",
        prompt_sha="p",
        schema_sha="s",
        text_sha="t",
        sampling_name="greedy",
        sampling={"temperature": 0.0},
        status=status,
        output=output,
        error=None,
        attempts=[attempt],
        created_at=datetime.now(UTC),
    )


def test_leaf_fields_flatten_nested_models():
    kinds = dict(leaf_fields(JobPosting))
    assert kinds["salary.max_amount"] == "exact"
    assert kinds["title"] == "text"
    assert kinds["must_have_skills"] == "list"
    assert "salary" not in kinds


def test_null_counts_as_an_answer():
    assert score("exact", None, None) == 1.0
    assert score("exact", "b2", None) == 0.0


def test_text_scores_word_overlap():
    assert score("text", "Senior Python Developer", "Python Developer") == pytest.approx(0.8)


def test_lists_ignore_case_punctuation_and_order():
    assert score("list", ["Node.js", "PostgreSQL"], ["postgresql", "NodeJS"]) == 1.0
    assert score("list", [], []) == 1.0
    assert score("list", ["C++"], ["C#"]) == 0.0


def test_percentile_interpolates():
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([5], 95) == 5
    assert percentile([], 95) is None


def test_failures_score_zero_and_provider_errors_are_left_out():
    golden = {doc_id: JobPosting.model_validate(LABEL) for doc_id in ("a", "b", "c")}
    results = [_result("a", "ok", LABEL), _result("b", "failed", None), _result("c", "error", None)]
    metrics, mismatches = score_run(results, golden, JobPosting)
    assert metrics.valid == pytest.approx(1 / 3)
    assert metrics.errors == pytest.approx(1 / 3)
    assert metrics.golden_docs == 2
    assert metrics.accuracy == pytest.approx(0.5)
    assert metrics.cost_per_1k_docs_usd == pytest.approx(0.2)
    assert [mismatch.field for mismatch in mismatches] == ["*"]

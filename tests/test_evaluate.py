from datetime import UTC, datetime

import pytest

from extraction.evaluate import (
    leaf_fields,
    match_records,
    percentile,
    score,
    score_document,
    score_run,
)
from extraction.pipeline import Attempt
from extraction.results import ExtractionResult
from extraction.schemas import JobPosting


def skill(skill, name=None, level="middle", years=None, must_have=True):
    return {
        "skill": skill,
        "name": name or skill,
        "level": level,
        "years": years,
        "must_have": must_have,
    }


LABEL = {
    "title": "Python Developer",
    "seniority": "middle",
    "company_type": None,
    "domain": "fintech",
    "employment": "full_time",
    "work_formats": ["remote"],
    "candidate_location": "ukraine",
    "candidate_countries": [],
    "office_cities": ["Kyiv"],
    "min_experience_years": 3.0,
    "salary": {"min_amount": 3000, "max_amount": None, "currency": "USD", "period": "month"},
    "languages": [{"language": "english", "level": "b1", "must_have": True}],
    "hard_skills": [
        skill("python", "Python", years=3.0),
        skill("django", "Django", level="junior"),
        skill("other", "Telegram bots"),
    ],
    "soft_skills": [
        {"skill": "communication", "name": "Communication", "level": "middle", "must_have": True}
    ],
    "domain_experience": [{"domain": "fintech", "years": 1.0, "must_have": False}],
    "legal": [{"condition": "military_registration", "detail": None, "must_have": True}],
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
    assert kinds["work_formats"] == "list"
    assert "salary" not in kinds


def test_a_list_of_objects_is_scored_by_id_then_on_the_pairs():
    kinds = dict(leaf_fields(JobPosting))
    assert kinds["hard_skills"] == "records"
    assert (kinds["hard_skills.level"], kinds["hard_skills.years"]) == ("exact", "exact")
    assert "hard_skills.skill" not in kinds  # what the pairs are made by
    assert "hard_skills.name" not in kinds  # free text only names the skill
    assert kinds["legal.must_have"] == "exact" and "legal.detail" not in kinds


def test_records_pair_by_id_and_other_records_by_their_words():
    expected = [skill("python"), skill("other", "Telegram bots"), skill("other", "Svelte")]
    predicted = [
        skill("other", "Telegram bots API"),
        skill("python", "Python 3"),
        skill("other", "Vue"),
    ]
    pairs = match_records(expected, predicted)
    assert [(want["name"], got["name"]) for want, got in pairs] == [
        ("python", "Python 3"),
        ("Telegram bots", "Telegram bots API"),
    ]
    # An `other` named after a listed skill is a miss: the answer should have used the id.
    assert match_records([skill("python")], [skill("other", "Python")]) == []


def test_score_document_scores_requirements_and_reports_the_misses():
    predicted = {
        **LABEL,
        "hard_skills": [
            skill("python", "Python", level="senior", years=3.0),  # a level too high
            skill("other", "telegram bots"),
            skill("kubernetes", "K8s"),  # not asked for
        ],
    }
    scores, misses = score_document(leaf_fields(JobPosting), LABEL, predicted)
    assert scores["hard_skills"] == pytest.approx(2 / 3)  # 2 pairs among 3 skills and 3
    assert scores["hard_skills.level"] == 0.5
    assert scores["hard_skills.years"] == 1.0
    assert scores["languages"] == scores["legal.must_have"] == scores["title"] == 1.0
    assert sorted(misses, key=lambda miss: miss[0]) == [
        ("hard_skills", pytest.approx(2 / 3), ["django"], ["kubernetes"]),
        (
            "hard_skills.level",
            0.0,
            {"name": "python", "level": "middle"},
            {"name": "python", "level": "senior"},
        ),
    ]


def test_requirement_fields_go_unscored_when_nothing_pairs():
    scores, _ = score_document(
        leaf_fields(JobPosting), LABEL, {**LABEL, "hard_skills": [skill("go")]}
    )
    assert scores["hard_skills"] == 0.0
    assert "hard_skills.level" not in scores


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

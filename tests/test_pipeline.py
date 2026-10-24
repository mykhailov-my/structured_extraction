import json

import pytest

from extraction.config import Retry
from extraction.pipeline import extract, validate
from extraction.prompts import Prompt
from extraction.providers import Completion, ProviderError, TransientError
from extraction.schemas import JobPosting

PROMPT = Prompt(
    doc_type="job",
    version="test",
    sha="0",
    system="Schema: {schema}",
    user="<posting>{document}</posting>",
    repair="Fix these:\n{errors}",
)
NO_WAIT = Retry(max_retries=2, backoff_s=0)
VALID = {
    "title": "Python Developer",
    "seniority": "middle",
    "company_type": None,
    "domain": None,
    "employment": None,
    "work_formats": ["remote"],
    "candidate_location": None,
    "candidate_countries": [],
    "office_cities": [],
    "min_experience_years": 3,
    "salary": None,
    "languages": [{"language": "english", "level": "b1", "must_have": True}],
    "hard_skills": [
        {"skill": "python", "name": "Python", "level": "middle", "years": None, "must_have": True}
    ],
    "soft_skills": [],
    "domain_experience": [],
    "legal": [],
}


class ScriptedProvider:
    """Answers with the given replies in order; an exception among them is raised instead."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def warm_up(self):
        pass

    def complete(self, *, system, messages, schema, sampling):
        self.requests.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Completion(text=reply, input_tokens=100, output_tokens=20, cost_usd=0.001)


def run(provider):
    return extract(
        "a posting",
        provider=provider,
        prompt=PROMPT,
        schema_model=JobPosting,
        sampling={},
        retry=NO_WAIT,
    )


def test_a_valid_first_answer_is_ok():
    outcome = run(ScriptedProvider(json.dumps(VALID)))
    assert outcome.status == "ok"
    assert outcome.output["title"] == "Python Developer"
    assert len(outcome.attempts) == 1


def test_an_invalid_answer_gets_one_repair_that_shows_the_errors():
    broken = json.dumps({**VALID, "seniority": "rockstar"})
    provider = ScriptedProvider(broken, json.dumps(VALID))
    outcome = run(provider)
    assert outcome.status == "repaired"
    assert [bool(attempt.errors) for attempt in outcome.attempts] == [True, False]
    *_, answer, repair = provider.requests[1]
    assert answer == {"role": "assistant", "content": broken}
    assert repair["role"] == "user" and "seniority" in repair["content"]


def test_still_invalid_after_the_repair_is_failed():
    outcome = run(ScriptedProvider("not json", "{}"))
    assert outcome.status == "failed"
    assert outcome.output is None
    assert len(outcome.attempts) == 2


def test_transient_errors_are_retried():
    outcome = run(ScriptedProvider(TransientError("timeout"), json.dumps(VALID)))
    assert outcome.status == "ok"
    assert outcome.attempts[0].retries == 1


def test_a_provider_that_keeps_failing_gives_an_error_result():
    outcome = run(ScriptedProvider(*[TransientError("503")] * 3))
    assert outcome.status == "error"
    assert "503" in outcome.error


def test_a_fatal_provider_error_propagates():
    with pytest.raises(ProviderError):
        run(ScriptedProvider(ProviderError("401")))


def test_validation_errors_name_the_field():
    salary = {"min_amount": 9000, "max_amount": 100, "currency": "USD", "period": "month"}
    output, errors = validate(json.dumps({**VALID, "salary": salary}), JobPosting)
    assert output is None
    assert errors[0].startswith("salary:")

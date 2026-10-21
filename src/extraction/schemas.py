"""What we extract: a Djinni job posting and a candidate CV.

Both schemas share one vocabulary (seniority, English level, work format, salary) so that
jobs and candidates can be compared later. Personal data (names, contacts, links, employer
names) is deliberately left out.
"""

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Seniority(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MIDDLE = "middle"
    SENIOR = "senior"
    LEAD = "lead"


class EnglishLevel(StrEnum):
    """CEFR level. Djinni labels: Beginner/Elementary = a1/a2, Pre-Intermediate = a2,
    Intermediate = b1, Upper-Intermediate = b2, Advanced/Fluent = c1, Proficient/Native = c2."""

    A1 = "a1"
    A2 = "a2"
    B1 = "b1"
    B2 = "b2"
    C1 = "c1"
    C2 = "c2"


class WorkFormat(StrEnum):
    REMOTE = "remote"
    OFFICE = "office"
    HYBRID = "hybrid"


class CompanyType(StrEnum):
    PRODUCT = "product"
    OUTSOURCE = "outsource"
    OUTSTAFF = "outstaff"
    STARTUP = "startup"
    AGENCY = "agency"


class Currency(StrEnum):
    USD = "USD"
    EUR = "EUR"
    UAH = "UAH"


class SalaryPeriod(StrEnum):
    MONTH = "month"
    YEAR = "year"
    HOUR = "hour"


class _Schema(BaseModel):
    # Unknown keys fail validation, and every object in the JSON schema gets
    # `additionalProperties: false`, which strict structured-output modes require.
    model_config = ConfigDict(extra="forbid")


class Salary(_Schema):
    min_amount: int | None = Field(
        gt=0, description="Lower bound; null if only an upper bound is given."
    )
    max_amount: int | None = Field(
        gt=0, description="Upper bound; null if only a lower bound is given."
    )
    currency: Currency
    period: SalaryPeriod = Field(description="Djinni amounts are monthly unless stated otherwise.")

    @model_validator(mode="after")
    def _check_bounds(self) -> Self:
        if self.min_amount is None and self.max_amount is None:
            raise ValueError("needs min_amount or max_amount; with no amount, salary is null")
        if self.min_amount and self.max_amount and self.min_amount > self.max_amount:
            raise ValueError("min_amount is greater than max_amount")
        return self


class JobPosting(_Schema):
    """A job posting from Djinni."""

    title: str = Field(
        description="Job title in English as the posting gives it, e.g. 'Senior Python Developer'."
    )
    seniority: Seniority | None = Field(description="Level the posting asks for.")
    company_type: CompanyType | None
    domain: str | None = Field(description="Business domain, lowercase, e.g. 'fintech', 'gamedev'.")
    work_formats: list[WorkFormat] = Field(description="Every work format the posting allows.")
    locations: list[str] = Field(
        description="Cities or countries in English where the office is"
        " or where candidates may be based."
    )
    min_experience_years: float | None = Field(
        ge=0, description="Minimum years of experience required."
    )
    english_level: EnglishLevel | None = Field(description="Minimum English level required.")
    salary: Salary | None = Field(description="Salary offered.")
    must_have_skills: list[str] = Field(
        description="Required technologies, tools and programming languages, one per item,"
        " under their usual names, e.g. 'PostgreSQL'."
    )
    nice_to_have_skills: list[str] = Field(
        description="Technologies listed as optional or 'a plus'."
    )


class CandidateProfile(_Schema):
    """A candidate's CV (profile) from Djinni."""

    title: str = Field(
        description="Position the candidate is looking for, in English, e.g. 'Python Developer'."
    )
    seniority: Seniority | None = Field(
        description="Level the candidate states; don't infer it from years of experience."
    )
    experience_years: float | None = Field(
        ge=0, description="Total years of commercial experience."
    )
    english_level: EnglishLevel | None
    salary_expectation: Salary | None
    work_formats: list[WorkFormat] = Field(description="Work formats the candidate accepts.")
    locations: list[str] = Field(
        description="Cities or countries in English where the candidate lives"
        " or is willing to work."
    )
    skills: list[str] = Field(
        description="Technologies, tools and programming languages, one per item,"
        " under their usual names."
    )
    domains: list[str] = Field(
        description="Business domains of past work, lowercase, e.g. 'e-commerce'."
    )
    excluded_domains: list[str] = Field(
        description="Domains the candidate refuses to work in, lowercase, e.g. 'gambling'."
    )


SCHEMAS: dict[str, type[BaseModel]] = {"job": JobPosting, "cv": CandidateProfile}
"""Doc type -> schema. A doc type is also a folder name under data/ and prompts/."""

# Keywords that strict structured-output modes (OpenAI-style APIs, Ollama's grammars) often
# reject. They are dropped from the schema sent to the model; Pydantic still enforces the
# constraints when the answer is validated.
_UNPORTABLE = frozenset(
    {
        "title",
        "default",
        "examples",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
    }
)


def json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON schema in the subset structured-output APIs agree on.

    `$ref`s are inlined, unportable keywords dropped, and every object is closed
    (`additionalProperties: false`) with all of its properties required.
    """
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})
    return _portable(schema, definitions)


def _portable(node: Any, definitions: dict[str, Any]) -> Any:
    if isinstance(node, list):
        return [_portable(item, definitions) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        target = definitions[node["$ref"].rsplit("/", 1)[-1]]
        siblings = {key: value for key, value in node.items() if key != "$ref"}
        if "description" in siblings and "description" in target:
            siblings["description"] = f"{siblings['description']} {target['description']}"
        return _portable({**target, **siblings}, definitions)
    portable = {}
    for key, value in node.items():
        if key in _UNPORTABLE:
            continue
        if key == "properties":  # keys here are field names, not schema keywords
            portable[key] = {name: _portable(sub, definitions) for name, sub in value.items()}
        else:
            portable[key] = _portable(value, definitions)
    if portable.get("type") == "object":
        portable["additionalProperties"] = False
        portable["required"] = list(portable.get("properties", {}))
    return portable

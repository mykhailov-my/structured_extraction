"""What we extract: a Djinni job posting and a candidate CV.

The posting schema follows what Djinni itself records. Company types, domains, candidate
locations, countries, work formats, employment and language levels take Djinni's own values,
from its job filters and the fact lines of the 1,051 postings of 2025–2026. Requirements are
split by kind: hard skills, soft skills, spoken languages, domain experience and legal
conditions. A skill is graded by the level it's needed at, from basic to expert, with the years
when the posting gives them, and hard skills come from a fixed list (`extraction.skills`).
Personal data (names, contacts, links, employer names) is deliberately left out.
"""

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from extraction.skills import MERGED, HardSkill


class Seniority(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MIDDLE = "middle"
    SENIOR = "senior"
    LEAD = "lead"


class SkillLevel(StrEnum):
    """How well a skill must be known, on the seniority scale."""

    BASIC = "basic"
    JUNIOR = "junior"
    MIDDLE = "middle"
    SENIOR = "senior"
    EXPERT = "expert"


class LanguageLevel(StrEnum):
    """CEFR, as Djinni labels it: A1 Початківець (Beginner), A2 Елементарний (Elementary), B1
    Середній (Intermediate), B2 Вище середнього (Upper-Intermediate), C1 Просунутий (Advanced),
    C2 Вільний (Fluent); native is Носій мови."""

    A1 = "a1"
    A2 = "a2"
    B1 = "b1"
    B2 = "b2"
    C1 = "c1"
    C2 = "c2"
    NATIVE = "native"


class Language(StrEnum):
    ENGLISH = "english"
    UKRAINIAN = "ukrainian"
    POLISH = "polish"
    GERMAN = "german"
    FRENCH = "french"
    SPANISH = "spanish"
    ITALIAN = "italian"
    DUTCH = "dutch"
    PORTUGUESE = "portuguese"
    CZECH = "czech"
    ROMANIAN = "romanian"
    RUSSIAN = "russian"
    HEBREW = "hebrew"
    OTHER = "other"


class WorkFormat(StrEnum):
    REMOTE = "remote"
    OFFICE = "office"
    HYBRID = "hybrid"


class Employment(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"


class CompanyType(StrEnum):
    """Djinni's company types."""

    PRODUCT = "product"
    OUTSOURCE = "outsource"
    OUTSTAFF = "outstaff"
    STARTUP = "startup"
    AGENCY = "agency"
    MIXED = "mixed"
    INHOUSE_IT = "inhouse_it"
    GOVERNMENT = "government"


class Domain(StrEnum):
    """Djinni's domains, as its job filter names them."""

    ADVERTISING = "advertising"
    ADULT = "adult"
    AGRICULTURE = "agriculture"
    AUTOMOTIVE = "automotive"
    CRYPTO = "crypto"
    DATING = "dating"
    ECOMMERCE = "ecommerce"
    EDUTECH = "edutech"
    ENERGY = "energy"
    ENTERTAINMENT = "entertainment"
    FINTECH = "fintech"
    GAMBLING = "gambling"
    GAMEDEV = "gamedev"
    GOVTECH = "govtech"
    HARDWARE = "hardware"
    HEALTHCARE = "healthcare"
    HRTECH = "hrtech"
    LEGALTECH = "legaltech"
    LOGISTICS = "logistics"
    MANUFACTURING = "manufacturing"
    MEDIA = "media"
    MILTECH = "miltech"
    ML = "ml"
    MOBILE = "mobile"
    PROPTECH = "proptech"
    SAAS = "saas"
    SECURITY = "security"
    SPORTS_FITNESS = "sports_fitness"
    TELECOM = "telecom"
    TRAVEL = "travel"
    OTHER = "other"


class CandidateLocation(StrEnum):
    """Djinni's choices for where candidates may be."""

    UKRAINE = "ukraine"
    EUROPE_AND_UKRAINE = "europe_and_ukraine"
    EU = "eu"
    WORLDWIDE = "worldwide"
    COUNTRIES = "countries"


# The countries Djinni's job filter offers, as ISO 3166 alpha-3 codes.
# fmt: off
_COUNTRIES = (
    "UKR", "POL", "CYP", "ROU", "CZE", "ESP", "SVK", "GEO", "ARM", "MDA", "USA", "DEU", "PRT",
    "BGR", "LTU", "CAN", "AZE", "HRV", "MNE", "GBR", "EST", "IRL", "SWE", "LVA", "ARE", "ISR",
    "MLT", "SRB", "ARG", "ALB", "AUT", "DNK", "NOR", "BRA", "KAZ", "UZB", "MEX", "BEL", "FRA",
    "HUN", "ISL", "ITA", "NLD", "SVN", "TUR", "KGZ", "IND", "PAN", "COL", "AND", "BIH", "FIN",
    "GRC", "LIE", "LUX", "MCO", "MKD", "SMR", "CHE", "ZAF",
)
# fmt: on
Country = StrEnum("Country", [(code, code) for code in _COUNTRIES])  # type: ignore[misc]


class Currency(StrEnum):
    USD = "USD"
    EUR = "EUR"
    UAH = "UAH"


class SalaryPeriod(StrEnum):
    MONTH = "month"
    YEAR = "year"
    HOUR = "hour"


class SoftSkill(StrEnum):
    COMMUNICATION = "communication"
    TEAMWORK = "teamwork"
    OWNERSHIP = "ownership"
    PROBLEM_SOLVING = "problem_solving"
    ANALYTICAL_THINKING = "analytical_thinking"
    CRITICAL_THINKING = "critical_thinking"
    SELF_LEARNING = "self_learning"
    ATTENTION_TO_DETAIL = "attention_to_detail"
    TIME_MANAGEMENT = "time_management"
    PROACTIVITY = "proactivity"
    RESULT_ORIENTATION = "result_orientation"
    LEADERSHIP = "leadership"
    MENTORING = "mentoring"
    ADAPTABILITY = "adaptability"
    STRESS_RESISTANCE = "stress_resistance"
    CUSTOMER_FOCUS = "customer_focus"
    OTHER = "other"


class LegalCondition(StrEnum):
    TIME_ZONE = "time_zone"
    WORK_PERMIT = "work_permit"
    CITIZENSHIP = "citizenship"
    MILITARY_REGISTRATION = "military_registration"
    CONTRACT_TYPE = "contract_type"
    AGE = "age"
    BACKGROUND_CHECK = "background_check"
    RELOCATION = "relocation"
    BUSINESS_TRAVEL = "business_travel"
    OTHER = "other"


class _Schema(BaseModel):
    # Unknown keys fail validation, and every object in the JSON schema gets
    # `additionalProperties: false`, which strict structured-output modes require.
    model_config = ConfigDict(extra="forbid")


_MUST_HAVE = "false if the posting calls it optional, a plus or nice to have."
_LEVEL = (
    "The level it's needed at: basic (knows the basics), junior (has used it, with help), middle"
    " (works with it on their own), senior (knows it in depth, designs with it), expert (an"
    " authority). Judge from the wording ('basic', 'strong', 'expert'), the years asked for"
    " (1: junior, 2-4: middle, 5+: senior) and the role's level."
)
_MERGED = "; ".join(f"{skill}: {', '.join(names[1:6])}" for skill, names in MERGED.items())


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


class LanguageRequirement(_Schema):
    language: Language
    level: LanguageLevel | None = Field(
        description="The lowest level accepted: 'B2 / C1' is b2. null if no level is given."
    )
    must_have: bool = Field(description=_MUST_HAVE)


class HardSkillRequirement(_Schema):
    skill: HardSkill = Field(
        description="The skill's id. One id covers all the ways of saying it: "
        f"{_MERGED}. other for anything not listed."
    )
    name: str = Field(
        description="The skill as the posting names it, in English: 'Django REST Framework',"
        " 'AWS Lambda', 'unit tests'."
    )
    level: SkillLevel = Field(description=_LEVEL)
    years: float | None = Field(
        ge=0,
        description="Years of experience asked for in this skill; null unless the posting"
        " gives them, as in Djinni's 'Python: 6 років' or '3+ years of Django'.",
    )
    must_have: bool = Field(description=_MUST_HAVE)


class SoftSkillRequirement(_Schema):
    skill: SoftSkill = Field(
        description="The quality's id: ownership covers responsibility and autonomy, attention"
        " to detail covers diligence and accuracy. other for anything not listed."
    )
    name: str = Field(description="The quality as the posting words it, in English.")
    level: SkillLevel = Field(description=_LEVEL)
    must_have: bool = Field(description=_MUST_HAVE)


class DomainExperience(_Schema):
    domain: Domain
    years: float | None = Field(
        ge=0, description="Years asked for, as in Djinni's 'Fintech: 3 роки'; null if not given."
    )
    must_have: bool = Field(description=_MUST_HAVE)


class LegalRequirement(_Schema):
    condition: LegalCondition = Field(
        description="time_zone: working hours that overlap a time zone. work_permit: the right"
        " to work in a country. military_registration: military registration documents or a"
        " deferment. contract_type: an FOP, B2B or employment contract. relocation: moving"
        " to the job's city or country. business_travel: trips for work."
    )
    detail: str | None = Field(
        description="What the posting specifies, in English: 'EST', 'FOP', '18+'."
    )
    must_have: bool = Field(description=_MUST_HAVE)


class JobPosting(_Schema):
    """A job posting from Djinni."""

    title: str = Field(
        description="Job title in English as the posting gives it, e.g. 'Senior Python Developer'."
    )
    seniority: Seniority | None = Field(
        description="Level the posting asks for, from the title or the text; the lower one if"
        " it names two. null if it names none: don't infer it from years of experience."
    )
    company_type: CompanyType | None = Field(
        description="Djinni's company line: Продуктова (Product) is product; Сервісна,"
        " Аутсорсингова (Outsource) is outsource; Аутстафінгова is outstaff; Змішана"
        " (сервісно-продуктова) is mixed."
    )
    domain: Domain | None = Field(
        description="Djinni's 'Домен:' line: Machine Learning / Big Data is ml, DefTech is"
        " miltech, Education is edutech, Blockchain / Crypto is crypto, Hardware / IoT is"
        " hardware, Healthcare / MedTech is healthcare, Other is other."
    )
    employment: Employment | None = Field(
        description="Djinni's 'Зайнятість:' line: Fulltime is full_time; Неповна / Парт-тайм is"
        " part_time."
    )
    work_formats: list[WorkFormat] = Field(
        description="Every format the posting allows: 'Тільки віддалено' (Full Remote) is"
        " [remote], 'Тільки офіс' is [office], 'Офіс або віддалено' is [office, remote],"
        " 'Гібридний формат роботи' is [hybrid]."
    )
    candidate_location: CandidateLocation | None = Field(
        description="Where candidates may be: Djinni's line above 'Країни, де розглядаємо"
        " кандидатів' (Countries where we consider candidates). Україна is ukraine, Країни"
        " Європи та Україна is europe_and_ukraine, Країни ЄС is eu, Весь світ (Worldwide) is"
        " worldwide, and a list of countries is countries."
    )
    candidate_countries: list[Country] = Field(
        description="ISO 3166 alpha-3 codes of the listed countries when candidate_location is"
        " countries: 'Польща, Румунія' is [POL, ROU]. Otherwise []."
    )
    office_cities: list[str] = Field(
        description="Cities with the office, in English: 'Офіс: Україна (Київ)' is ['Kyiv']."
    )
    min_experience_years: float | None = Field(
        ge=0,
        description="The fewest years of experience accepted: 'від 5 років, також розглядаємо"
        " з досвідом 3 роки' is 3; 'Без досвіду' is 0.",
    )
    salary: Salary | None = Field(description="Salary offered.")
    languages: list[LanguageRequirement] = Field(
        description="Spoken languages asked for, English included."
    )
    hard_skills: list[HardSkillRequirement] = Field(
        description="Technologies, tools, programming languages and practices the posting asks"
        " the candidate to know, required or nice to have, one item each. Not the job's"
        " duties, nor what the company offers."
    )
    soft_skills: list[SoftSkillRequirement] = Field(
        description="How the candidate must work with people and tasks."
    )
    domain_experience: list[DomainExperience] = Field(
        description="Experience asked for in a business domain."
    )
    legal: list[LegalRequirement] = Field(
        description="Conditions on the candidate rather than abilities. Where candidates may"
        " be is candidate_location, not a condition here."
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
    english_level: LanguageLevel | None
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

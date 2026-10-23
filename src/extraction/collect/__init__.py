"""Collecting job postings. A collector parses each page into a `JobPage`, the posting's parts
as the page shows them, and keeps it as a `Posting`: the parts plus where and when the page was
found, in one format whatever the source. Everything is scrubbed of contact details on the way
in.

For the experiment a posting is stored twice: the text the model reads,
data/texts/job/<doc_id>.txt, and its record, data/scraped/job/<doc_id>.json.
`extraction.collect.postings` writes every posting, live and archived, to
data/postings/<year>.jsonl.
"""

import json
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any

from extraction.collect.scrub import scrub


class ParseError(Exception):
    """The page doesn't look like a Djinni posting: the layout changed, or we were blocked."""


@dataclass(frozen=True)
class JobPage:
    """A posting as the page shows it, before any interpretation."""

    title: str
    category: str  # Djinni's category, from the breadcrumb: "Python", "QA Automation"
    company: str
    salary: str  # empty when the page only ranks the salary ("$$$")
    skills: list[str]
    languages: list[str]
    facts: list[str]  # the sidebar: experience, work format, countries, domain, company type
    description: str

    def text(self) -> str:
        """The page as plain text, under Djinni's own (Ukrainian) section headings."""
        header = [line for line in (self.title, self.company, self.salary) if line]
        details = []
        if self.skills:
            details += ["Необхідні навички", ", ".join(self.skills)]
        if self.languages:
            details += ["Вимоги до володіння мовами", *self.languages]
        sections = [header, self.description.splitlines(), details, self.facts]
        return "\n\n".join("\n".join(section) for section in sections if section) + "\n"


@dataclass(frozen=True)
class Posting:
    """A posting in the one format every source is kept in."""

    job_id: int
    url: str
    source: str  # "djinni.co" (crawled live) or "web.archive.org"
    snapshot: str | None  # the archived page
    captured_at: str  # when the page was fetched, or archived
    posted: str | None  # the posting date the page shows
    date: str | None  # `posted`, or else estimated from the job id
    year: int | None
    active: bool  # False when the page marks the posting closed
    layout: str  # "v1" to "v4", see the README; djinni.co today is "v4"
    page: JobPage

    @property
    def doc_id(self) -> str:
        return f"djinni-{self.job_id}"

    def to_json(self) -> dict[str, Any]:
        record = {"doc_id": self.doc_id, **asdict(self)}
        page = record.pop("page")
        return record | page

    @classmethod
    def from_json(cls, record: dict[str, Any]) -> "Posting":
        page = JobPage(**{field.name: record[field.name] for field in fields(JobPage)})
        own = {field.name: record[field.name] for field in fields(cls) if field.name != "page"}
        return cls(**own, page=page)


def existing_ids(data_dir: Path, doc_type: str) -> set[str]:
    return {path.stem for path in (data_dir / "texts" / doc_type).glob("*.txt")}


def scrubbed(page: JobPage) -> JobPage:
    """The page without contact details."""
    return JobPage(**_scrubbed(asdict(page)))


def save_posting(data_dir: Path, posting: Posting) -> None:
    """Store a posting for the experiment, scrubbed: its text and its record."""
    page = scrubbed(posting.page)
    write_file(data_dir / "texts" / "job" / f"{posting.doc_id}.txt", page.text())
    record_json = json.dumps(replace(posting, page=page).to_json(), ensure_ascii=False, indent=2)
    record_json += "\n"
    write_file(data_dir / "scraped" / "job" / f"{posting.doc_id}.json", record_json)


def write_file(path: Path, content: str) -> None:
    """Write `content` whole: an interrupted write leaves the old file, not half a new one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.tmp")
    partial.write_text(content, encoding="utf-8")
    partial.replace(path)


def _scrubbed(value: Any) -> Any:
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, list):
        return [_scrubbed(item) for item in value]
    if isinstance(value, dict):
        return {key: _scrubbed(item) for key, item in value.items()}
    return value

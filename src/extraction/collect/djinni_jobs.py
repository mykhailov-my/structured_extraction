"""Public job postings from djinni.co.

Postings are found through the RSS feed (the newest 100, from all categories or one feed per
`primary_keyword`). Each posting page is parsed into its parts: title, company, salary,
required skills, language requirements, the facts sidebar and the description, in the page's
own mix of Ukrainian and English. Page chrome (navigation, apply form, view counts, the salary
hint for "similar vacancies") is left out. The parts are stored as JSON and rendered as the
plain text the model reads.

robots.txt allows /jobs/. Candidate profiles (/developers) are disallowed there, and Djinni's
terms forbid collecting candidates' data by scraping, so they are never fetched.
"""

import logging
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlencode
from xml.etree import ElementTree

from bs4 import BeautifulSoup, Tag

from extraction.collect import existing_ids, save
from extraction.collect.html import fragment_lines, one_line, rich_lines
from extraction.collect.polite import FetchError, PoliteClient

log = logging.getLogger(__name__)

FEED_URL = "https://djinni.co/jobs/rss/"
_JOB_ID = re.compile(r"/jobs/(\d+)-")
# An amount of money: "$$$" without digits only ranks the job, and "Room 8" is a company.
_SALARY = re.compile(r"[$€₴]\s*\d|\d\s*[$€₴]")
_CHROME = ", ".join(
    [
        "button",
        "form",
        "script",
        "style",
        "svg",
        ".badge",  # "Неактивна" in the title, "Швидко відповідає" next to the company
        "h1 .text-danger",  # "(offline)" in the title, in 2024
        ".js-fold-toggle",  # "+ ще 3"
        ".js-inbox-action-btns",  # apply buttons
        "#job-publication-info",  # date, views, applications
        "#applicant_insights",
    ]
)


class ParseError(Exception):
    """The page doesn't look like a Djinni posting: the layout changed, or we were blocked."""


@dataclass(frozen=True)
class Posting:
    job_id: str
    url: str
    title: str
    category: str
    published: str

    @property
    def doc_id(self) -> str:
        return f"djinni-{self.job_id}"


@dataclass(frozen=True)
class JobPage:
    """A posting as the page shows it, before any interpretation."""

    title: str
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


def crawl_jobs(
    data_dir: Path, *, count: int, keywords: list[str] | None = None, delay_s: float = 3.0
) -> int:
    """Save up to `count` postings that aren't in data/texts/job/ yet; returns how many."""
    with PoliteClient(delay_s=delay_s) as client:
        postings = pick(discover(client, keywords), count=count, skip=existing_ids(data_dir, "job"))
        categories = len({posting.category for posting in postings})
        log.info("collecting %d postings from %d categories", len(postings), categories)
        saved = failures = 0
        for number, posting in enumerate(postings, 1):
            try:
                page = parse_job(client.get(posting.url).text)
            except (FetchError, ParseError) as e:
                log.warning("  %s: %s", posting.url, e)
                failures += 1
                if failures == 3:
                    raise FetchError("three pages in a row failed; stopping") from e
                continue
            failures = 0
            source = {
                "url": posting.url,
                "category": posting.category,
                "published": posting.published,
            }
            save(
                data_dir,
                "job",
                posting.doc_id,
                text=page.text(),
                fields=asdict(page),
                source=source,
            )
            saved += 1
            log.info(
                "  %2d/%d  %-16s %-20s %s",
                *(number, len(postings), posting.doc_id, posting.category[:20], posting.title[:60]),
            )
    return saved


def discover(client: PoliteClient, keywords: list[str] | None = None) -> list[Posting]:
    """Postings in the RSS feed: all categories, or one feed per Djinni keyword."""
    if keywords:
        feeds = [f"{FEED_URL}?{urlencode({'primary_keyword': keyword})}" for keyword in keywords]
    else:
        feeds = [FEED_URL]
    postings: dict[str, Posting] = {}
    for feed in feeds:
        for item in ElementTree.fromstring(client.get(feed).content).iter("item"):
            url = (item.findtext("link") or "").strip()
            match = _JOB_ID.search(url)
            if not match or match.group(1) in postings:
                continue
            categories = [
                c.text.strip() for c in item.findall("category") if (c.text or "").strip()
            ]
            postings[match.group(1)] = Posting(
                job_id=match.group(1),
                url=url,
                title=(item.findtext("title") or "").strip(),
                category=categories[0] if categories else "Other",
                published=(item.findtext("pubDate") or "").strip(),
            )
    return list(postings.values())


def pick(postings: list[Posting], *, count: int, skip: set[str]) -> list[Posting]:
    """Round-robin over categories, so even a small sample spans many kinds of jobs."""
    by_category: dict[str, list[Posting]] = defaultdict(list)
    for posting in postings:
        if posting.doc_id not in skip:
            by_category[posting.category].append(posting)
    picked: list[Posting] = []
    for round_number in range(max(map(len, by_category.values()), default=0)):
        for group in by_category.values():
            if len(picked) == count:
                return picked
            if round_number < len(group):
                picked.append(group[round_number])
    return picked


def parse_job(html: str) -> JobPage:
    page = BeautifulSoup(html, "html.parser").select_one(".job-post-page")
    title = page.select_one("h1") if page else None
    description = page.select_one(".job-post__description") if page else None
    if page is None or title is None or description is None:
        raise ParseError("no posting title or description on the page")
    for element in page.select(_CHROME):
        element.decompose()
    # The first link is the logo. Until 2025 they were /jobs/?company=<slug>.
    company_links = page.select('header a[href*="/jobs/company-"], header a[href*="?company="]')
    # Until 2025 the salary was in the title: "Python Developer <span>to $1500</span>".
    in_title = title.select(".public-salary-item, .text-success")
    salaries = [one_line(tag) for tag in in_title + page.select("header .col-auto")]
    for tag in in_title:
        tag.decompose()
    card = page.select_one("aside .card")
    fact_lists = card.find_all("ul", recursive=False) if card else []
    return JobPage(
        title=one_line(title),
        company=next((name for link in company_links if (name := one_line(link))), ""),
        salary=next((text for text in salaries if _SALARY.search(text)), ""),
        skills=_skills(description),
        languages=[_label_value(row) for row in description.parent.select(".detail-rows__line")],
        facts=[line for fact_list in fact_lists for line in fragment_lines(fact_list)],
        description="\n".join(rich_lines(description)),
    )


def _skills(description: Tag) -> list[str]:
    """The comma-separated tags under the heading that follows the description."""
    heading = description.find_next_sibling("h2")
    block = heading.find_next_sibling() if heading else None
    fragments = block.stripped_strings if block else []
    return [
        skill.strip() for fragment in fragments for skill in fragment.split(",") if skill.strip()
    ]


def _label_value(row: Tag) -> str:
    parts = [one_line(part) for part in row.find_all(recursive=False)]
    return ": ".join(part for part in parts if part)

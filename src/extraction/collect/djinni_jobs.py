"""Public job postings from djinni.co.

Postings are found through the RSS feed (the newest 100, from all categories or one feed per
`primary_keyword`). Each posting page is parsed into its parts: title, category, company,
salary, required skills, language requirements, the facts sidebar and the description, in
the page's own mix of Ukrainian and English. Page chrome (navigation, apply form, view counts,
the salary hint for "similar vacancies") is left out. The parts are stored as a `Posting`
and rendered as the plain text the model reads.

robots.txt allows /jobs/. Candidate profiles (/developers) are disallowed there, and Djinni's
terms forbid collecting candidates' data by scraping, so they are never fetched.
"""

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode
from xml.etree import ElementTree

from bs4 import BeautifulSoup, Tag

from extraction.collect import JobPage, ParseError, Posting, existing_ids, save_posting
from extraction.collect.html import fragment_lines, one_line, rich_lines
from extraction.collect.polite import FetchError, PoliteClient

log = logging.getLogger(__name__)

FEED_URL = "https://djinni.co/jobs/rss/"
_JOB_ID = re.compile(r"/jobs/(\d+)-")
# A category's postings; a city's link adds "&location=" or "/kyiv/" to it.
_CATEGORY_LINK = re.compile(r"primary_keyword=|/jobs/keyword-[^/]+/?$")
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
        "#job_extra_info table",  # the skills' years again, in the sidebar
        ".js-inbox-action-btns",  # apply buttons
        "#job-publication-info",  # date, views, applications
        "#applicant_insights",
    ]
)


@dataclass(frozen=True)
class FeedItem:
    """A posting as the RSS feed lists it."""

    job_id: str
    url: str
    title: str
    category: str
    published: str

    @property
    def doc_id(self) -> str:
        return f"djinni-{self.job_id}"


def crawl_jobs(
    data_dir: Path, *, count: int, keywords: list[str] | None = None, delay_s: float = 3.0
) -> int:
    """Save up to `count` postings that aren't in data/texts/job/ yet; returns how many."""
    with PoliteClient(delay_s=delay_s) as client:
        items = pick(discover(client, keywords), count=count, skip=existing_ids(data_dir, "job"))
        categories = len({item.category for item in items})
        log.info("collecting %d postings from %d categories", len(items), categories)
        saved = failures = 0
        for number, item in enumerate(items, 1):
            try:
                page = parse_job(client.get(item.url).text)
            except (FetchError, ParseError) as e:
                log.warning("  %s: %s", item.url, e)
                failures += 1
                if failures == 3:
                    raise FetchError("three pages in a row failed; stopping") from e
                continue
            failures = 0
            posted = feed_date(item.published)
            posting = Posting(
                job_id=int(item.job_id),
                url=item.url,
                source="djinni.co",
                snapshot=None,
                captured_at=datetime.now(UTC).isoformat(timespec="seconds"),
                posted=posted,
                date=posted,
                year=int(posted[:4]) if posted else None,
                active=True,  # the feed lists open postings
                layout="v4",
                page=replace(page, category=page.category or item.category),
            )
            save_posting(data_dir, posting)
            saved += 1
            log.info(
                "  %2d/%d  %-16s %-20s %s",
                *(number, len(items), item.doc_id, item.category[:20], item.title[:60]),
            )
    return saved


def discover(client: PoliteClient, keywords: list[str] | None = None) -> list[FeedItem]:
    """Postings in the RSS feed: all categories, or one feed per Djinni keyword."""
    if keywords:
        feeds = [f"{FEED_URL}?{urlencode({'primary_keyword': keyword})}" for keyword in keywords]
    else:
        feeds = [FEED_URL]
    postings: dict[str, FeedItem] = {}
    for feed in feeds:
        for item in ElementTree.fromstring(client.get(feed).content).iter("item"):
            url = (item.findtext("link") or "").strip()
            match = _JOB_ID.search(url)
            if not match or match.group(1) in postings:
                continue
            categories = [
                c.text.strip() for c in item.findall("category") if (c.text or "").strip()
            ]
            postings[match.group(1)] = FeedItem(
                job_id=match.group(1),
                url=url,
                title=(item.findtext("title") or "").strip(),
                category=categories[0] if categories else "Other",
                published=(item.findtext("pubDate") or "").strip(),
            )
    return list(postings.values())


def pick(items: list[FeedItem], *, count: int, skip: set[str]) -> list[FeedItem]:
    """Round-robin over categories, so even a small sample spans many kinds of jobs."""
    by_category: dict[str, list[FeedItem]] = defaultdict(list)
    for item in items:
        if item.doc_id not in skip:
            by_category[item.category].append(item)
    picked: list[FeedItem] = []
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
    skills = _skills(description)  # takes the skills' rows out, leaving the languages' rows
    return JobPage(
        title=one_line(title),
        category=breadcrumb_category(page),
        company=next((name for link in company_links if (name := one_line(link))), ""),
        salary=next((text for text in salaries if _SALARY.search(text)), ""),
        skills=skills,
        languages=[_label_value(row) for row in description.parent.select(".detail-rows__line")],
        facts=[line for fact_list in fact_lists for line in fragment_lines(fact_list)],
        description="\n".join(rich_lines(description)),
    )


def breadcrumb_category(page: Tag) -> str:
    """The posting's category: the breadcrumb's last link to a category's postings."""
    links = page.select(".breadcrumb a[href]")
    names = [
        one_line(link)
        for link in links
        if _CATEGORY_LINK.search(link["href"]) and "location=" not in link["href"]
    ]
    return names[-1] if names else ""


def feed_date(published: str) -> str | None:
    """The feed's "Wed, 21 Oct 2026 17:02:43 +0300" as "2026-10-21"."""
    try:
        return parsedate_to_datetime(published).date().isoformat()
    except (TypeError, ValueError):
        return None


def _skills(description: Tag) -> list[str]:
    """The skills under the heading that follows the description: first those asked for with
    years of experience, as rows ("Django: 3 роки"), then the comma-separated tags. The rows
    are removed from the page, as the language requirements below are rows of the same kind."""
    heading = description.find_next_sibling("h2")
    block = heading.find_next_sibling() if heading else None
    if block is None:
        return []
    with_years = []
    for row in block.select(".detail-rows__line"):
        with_years.append(_label_value(row))
        row.decompose()
    tags = [
        skill.strip()
        for fragment in block.stripped_strings
        for skill in fragment.split(",")
        if skill.strip()
    ]
    return with_years + tags


def _label_value(row: Tag) -> str:
    parts = [one_line(part) for part in row.find_all(recursive=False)]
    return ": ".join(part for part in parts if part)

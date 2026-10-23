"""Djinni job postings from past years, through the Wayback Machine (web.archive.org).

Djinni keeps old postings online, but a closed posting shows no date and nothing lists them.
The Wayback Machine has tens of thousands of posting pages since 2017, each with a capture
time:

1. The archive's CDX index lists the captures of djinni.co/jobs/<id>-<slug>/ pages, one query
   per year, optionally only slugs with a keyword. The index is slow, so answers are cached.
2. Each posting's oldest capture is fetched as archived (`id_`, without the archive's toolbar)
   into a cache of gzipped pages. When it is an error page instead of the posting (Djinni at
   times blocked the archive's crawler), a later capture stands in. Postings are fetched in a
   fixed random order, so a crawl stopped halfway leaves a random sample.
3. Djinni's markup changed several times. `parse_snapshot` reads every layout seen since 2019
   and drops recruiter names, profile links and photos, which older pages show.

`extraction.collect.postings` turns the cached pages into dated records.
"""

import gzip
import logging
import random
import re
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from extraction.collect import JobPage, ParseError
from extraction.collect.djinni_jobs import breadcrumb_category, parse_job
from extraction.collect.html import fragment_lines, one_line, rich_lines
from extraction.collect.polite import FetchError, PoliteClient

log = logging.getLogger(__name__)

FIRST_YEAR = 2017  # the archive's first captures of Djinni postings
CDX_URL = "https://web.archive.org/cdx/search/cdx"
SNAPSHOT_URL = "https://web.archive.org/web/{timestamp}id_/{url}"
_ATTEMPTS = 3  # captures of one posting tried before giving up on it
_JOB_ID = re.compile(r"/jobs/(\d+)-")
_RECRUITER_LINK = re.compile(r"(?:^|djinni\.co)/r/")
_CLOSED = {"offline", "(offline)", "inactive", "неактивна", "неактивная"}
_OLD_CHROME = ", ".join(
    [
        "script",
        "style",
        "svg",
        "form",
        "button",
        "nav",
        "footer",
        ".alert",
        ".hintbox-wrapper",  # "Similar jobs"
        ".salaries-info-link",  # the salary hint for similar jobs
        ".material-icons",  # icon names written as text: "home_work"
        ".picture",  # recruiter photo
        "user-picture",
        ".job-details--recruiter-name",
        ".text-danger",  # "(offline)"
        ".badge",
        ".public-salary-item",
        ".profile-page-section.text-small",  # posting date, views, applications
        ":has(> .bi-pencil-square)",  # the same from 2023, after a pencil icon
    ]
)
_POSTED_ON = re.compile(r"\b(?:posted on|published|опубліковано|опубликовано|опубликована)", re.I)
_POSTED = re.compile(_POSTED_ON.pattern + r"\s+(\d{1,2})\s+([^\W\d_]+)(?:\s+(\d{4}))?", re.I)
_MONTHS = {
    name: number
    for names in (
        "january february march april may june july august september october november december",
        "січня лютого березня квітня травня червня липня серпня вересня жовтня листопада грудня",
        "января февраля марта апреля мая июня июля августа сентября октября ноября декабря",
    )
    for number, name in enumerate(names.split(), 1)
}


@dataclass(frozen=True)
class Capture:
    job_id: int
    timestamp: str  # yyyymmddhhmmss
    url: str  # the archived URL exactly as captured; the archive finds nothing for a variant

    @property
    def key(self) -> str:
        return f"{self.timestamp}-{self.job_id}"

    @property
    def captured_at(self) -> datetime:
        return datetime.strptime(self.timestamp, "%Y%m%d%H%M%S")

    @property
    def snapshot(self) -> str:
        """The archived page as people see it, with the archive's toolbar."""
        return f"https://web.archive.org/web/{self.timestamp}/{self.url}"


@dataclass(frozen=True)
class Snapshot:
    page: JobPage
    layout: str  # "v1" (until mid-2022) to "v4" (since autumn 2024); see the README
    active: bool  # False when the page marks the posting as closed
    posted: date | None  # the posting date, when the page shows one


def crawl_archive(
    cache_dir: Path,
    *,
    years: range,
    keyword: str | None = None,
    limit: int | None = None,
    delay_s: float = 5.0,
) -> tuple[int, int]:
    """Fetch the page of every posting captured in `years` (only slugs with `keyword`, if
    given) into the cache, at most `limit` new ones; returns how many postings the archive has
    and how many pages were fetched."""
    with PoliteClient(delay_s=delay_s, timeout_s=300, max_retries=5) as client:
        lines: list[str] = []
        missing = []
        for year in years:
            try:
                lines += index(client, year, cache_dir, keyword)
            except FetchError as e:
                log.warning("archive index for %d unavailable: %s", year, e)
                missing.append(year)
        if missing:  # a posting would be dated by a later capture than its first
            raise FetchError(f"no archive index for {missing}; run again, the rest is cached")
        jobs = captures(lines)
        return len(jobs), fetch_pages(client, jobs, cache_dir, limit=limit)


def index(
    client: PoliteClient, year: int, cache_dir: Path, keyword: str | None = None
) -> list[str]:
    """Index lines "timestamp url": the oldest capture in `year` of each posting URL, only
    slugs with `keyword` if given. A year the archive can't answer in one go is asked for
    month by month."""
    keyword = keyword.lower() if keyword else None
    path = cache_dir / f"{keyword or 'all'}-{year}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").splitlines()
    slug = f"[^/?]*{re.escape(keyword)}.*" if keyword else ".*"
    try:
        lines = _index_query(client, str(year), slug)
    except FetchError as e:
        log.warning("archive index for %d in one go failed (%s); asking month by month", year, e)
        lines = [
            line
            for month in range(1, 13)
            for line in _index_query(client, f"{year}{month:02d}", slug)
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return lines


def _index_query(client: PoliteClient, period: str, slug: str) -> list[str]:
    """One CDX query: captures of posting pages in `period` (yyyy or yyyymm)."""
    query = [
        ("url", "djinni.co/jobs/"),
        ("matchType", "prefix"),
        ("from", period),
        ("to", period),
        ("filter", "statuscode:200"),
        ("filter", f"original:.*/jobs/[0-9]+-{slug}"),
        ("collapse", "urlkey"),
        ("fl", "timestamp,original"),
    ]
    return client.get(f"{CDX_URL}?{urlencode(query)}").text.splitlines()


def captures(lines: Iterable[str]) -> dict[int, list[Capture]]:
    """Each posting's captures, oldest first: one per URL variant (?from=..., a new slug) and
    year."""
    found: dict[int, list[Capture]] = defaultdict(list)
    for line in lines:
        parts = line.split()
        match = _JOB_ID.search(parts[1]) if len(parts) == 2 else None
        if match:
            job_id = int(match.group(1))
            found[job_id].append(Capture(job_id, parts[0], parts[1]))
    return {job_id: sorted(group, key=lambda c: c.timestamp) for job_id, group in found.items()}


def fetch_pages(
    client: PoliteClient,
    jobs: dict[int, list[Capture]],
    cache_dir: Path,
    *,
    limit: int | None = None,
) -> int:
    """Fetch a page for every posting that has none in the cache, at most `limit`, in a fixed
    random order so that any part of the crawl is a random sample; returns how many."""
    pages = {path.name.removesuffix(".html.gz") for path in (cache_dir / "pages").glob("*.gz")}
    failed = _failed(cache_dir)
    order = random.Random(0).sample(sorted(jobs), len(jobs))
    todo = [
        [capture for capture in jobs[job] if capture.key not in failed][:_ATTEMPTS]
        for job in order
        if not any(capture.key in pages for capture in jobs[job])
    ]
    todo = [candidates for candidates in todo if candidates]
    log.info("%d postings, %d to fetch", len(jobs), len(todo))
    todo = todo[:limit] if limit is not None else todo
    fetched = trouble = 0
    started = time.monotonic()
    for number, candidates in enumerate(todo, 1):
        for capture in candidates:  # a later capture stands in for an error page
            try:
                html = _snapshot_html(client, capture, cache_dir)
            except FetchError as e:
                if e.status is None or e.status == 429 or e.status >= 500:  # struggling
                    log.warning("  %s: %s", capture.snapshot, e)
                    trouble += 1
                    if trouble == 10:
                        raise FetchError("the archive keeps failing; run again later") from e
                    continue
                _remember_failure(cache_dir, capture, f"HTTP {e.status}")
                continue
            trouble = 0
            if html is None:
                _remember_failure(cache_dir, capture, "error page")
                continue
            fetched += 1
            _log_page(f"{number}/{len(todo)}", capture, html)
            break
        if number % 100 == 0:
            left = (time.monotonic() - started) / number * (len(todo) - number)
            log.info(
                "%d of %d done; about %s left", number, len(todo), timedelta(seconds=round(left))
            )
    return fetched


def parse_snapshot(html: str, captured: date) -> Snapshot:
    """A posting from an archived page in any of Djinni's layouts since 2019."""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("h1")
    if title is None:
        raise ParseError("no title on the page")
    closed = bool(title.select(".text-danger")) or any(
        one_line(badge).lower() in _CLOSED for badge in title.select(".badge")
    )
    # Only the element with the date: a year-less one ("Опубліковано 21 жовтня") has the view
    # count in the next element, and "2015 переглядів" isn't a year.
    labels = soup.find_all(string=_POSTED_ON)
    posted = next(filter(None, (_posted(one_line(tag.parent), captured) for tag in labels)), None)
    if soup.select_one(".job-post__description"):
        page = parse_job(html)
        if not page.company:  # some closed postings name it only in <title>
            page = replace(page, company=_title_company(soup))
        return Snapshot(page, "v4", not closed, posted)
    if soup.select_one(".job-post-description"):
        layout = "v3"
    elif soup.select_one(".job-details--main-info, .job-additional-info"):
        layout = "v2"
    else:
        layout = "v1"
    return Snapshot(_parse_old(soup), layout, not closed, posted)


def _snapshot_html(client: PoliteClient, capture: Capture, cache_dir: Path) -> str | None:
    """The archived page, kept gzipped in the cache: a better parser reads it again without
    asking the archive, which is slow. None for an error page instead of the posting."""
    path = cache_dir / "pages" / f"{capture.key}.html.gz"
    if path.exists():
        return gzip.decompress(path.read_bytes()).decode("utf-8")
    html = client.get(SNAPSHOT_URL.format(timestamp=capture.timestamp, url=capture.url)).text
    if "<h1" not in html:  # "Your IP address, ..., has been blocked": every posting has a title
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".tmp")  # an interrupted write leaves no broken page behind
    partial.write_bytes(gzip.compress(html.encode("utf-8")))
    partial.replace(path)
    return html


def _failed(cache_dir: Path) -> set[str]:
    """Captures that were missing or error pages; the archive won't change its mind."""
    path = cache_dir / "failed.txt"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return {line.split()[0] for line in lines if line}


def _remember_failure(cache_dir: Path, capture: Capture, reason: str) -> None:
    log.info("  %s: %s", capture.snapshot, reason)
    cache_dir.mkdir(parents=True, exist_ok=True)
    with (cache_dir / "failed.txt").open("a", encoding="utf-8") as failed:
        failed.write(f"{capture.key} {reason}\n")


def _log_page(progress: str, capture: Capture, html: str) -> None:
    try:
        snapshot = parse_snapshot(html, capture.captured_at.date())
    except ParseError as e:  # an unknown layout: the page stays cached for a better parser
        log.warning("%s  djinni-%d  %s: %s", progress, capture.job_id, capture.snapshot, e)
        return
    page = snapshot.page
    log.info(
        "%s  djinni-%-7d %s  %s  %s",
        *(progress, capture.job_id, capture.timestamp[:8], snapshot.layout, page.title[:60]),
    )


def _parse_old(soup: BeautifulSoup) -> JobPage:
    title = soup.find("h1")
    salary_tag = title.select_one(".public-salary-item")
    salary = one_line(salary_tag) if salary_tag else ""
    category = breadcrumb_category(soup)  # before the chrome goes: some sit in a <nav>
    for link in soup.find_all("a", href=True):
        if _RECRUITER_LINK.search(link["href"]):
            link.decompose()
    for element in soup.select(_OLD_CHROME):
        element.decompose()
    sections = (
        soup.select(".job-post-description")  # v3
        or soup.select(".profile-page-section")  # v1, and v2 until mid-2023
        or soup.select(".row-mobile-order-2 > .mb-4")  # mid-2023 to spring 2024
    )
    if not sections:
        raise ParseError("no description on the page")
    return JobPage(
        title=one_line(title),
        category=category,
        company=_old_company(soup),
        salary=salary if any(char.isdigit() for char in salary) else "",
        skills=[],
        languages=[],
        facts=_old_facts(soup),
        description="\n".join(line for section in sections for line in rich_lines(section)),
    )


def _old_company(soup: BeautifulSoup) -> str:
    """The company link or header; else the "About Company" heading over the company's blurb or
    the recruiter's job ("HRM at Company"), which is all that 2019 pages have; else <title>."""
    nodes = [
        *soup.select('a[href*="/jobs/company-"]'),  # v1
        soup.select_one(".job-details--main-info > div"),  # v2, v3
        soup.select_one(".detail--title-wrapper .d-flex"),  # v3
    ]
    for node in nodes:
        if name := one_line(node):
            return name
    headings = (one_line(heading) for heading in soup.find_all(["h2", "h3", "h4"]))
    if about := next((text for text in headings if text.startswith("About ")), ""):
        return about.removeprefix("About ")
    details = soup.select_one(".list-jobs__details")  # the recruiter's link is gone by now
    jobs = (re.match(r",.* at (.+)", line) for line in fragment_lines(details)) if details else []
    return next((job.group(1) for job in jobs if job), "") or _title_company(soup)


def _title_company(soup: BeautifulSoup) -> str:
    """The company in <title>: "Python Developer at Company – Djinni", "в Company" in Ukrainian.
    The last one counts, as job titles have them too ("developer в команду Джина")."""
    title = " ".join(soup.title.get_text().split()) if soup.title else ""
    match = re.search(r".* (?:at|в) (.+?) [–-] Djinni", title)
    return match.group(1) if match else ""


def _old_facts(soup: BeautifulSoup) -> list[str]:
    """The details line under the title (v1), then the sidebar."""
    # The details line (v1): ", HRM at Company", the company's link, places, experience.
    line = soup.select_one(".list-jobs__details")
    texts = (text for text in line.find_all(string=True) if text.parent.name != "a") if line else []
    details = [" ".join(text.split()).strip("· ") for text in texts]
    items = soup.select(".job-additional-info--item-text")  # "Category: <span>Python</span>"
    sidebars = soup.select(".inbox-candidate-details--body")
    card = soup.select_one("aside .card")
    sidebars += card.find_all("ul", recursive=False) if card else []
    facts = [
        *(text for text in details if not text.startswith(",")),
        *(one_line(item) for item in items),
        *(line for sidebar in sidebars for line in fragment_lines(sidebar)),
    ]
    return list(dict.fromkeys(fact for fact in facts if fact))


def _posted(text: str, captured: date) -> date | None:
    """The posting date in a text from the page; a date without a year is the latest one up to
    the capture ("21 жовтня" captured in January is last year's)."""
    match = _POSTED.search(text)
    if match is None or match.group(2).lower() not in _MONTHS:
        return None
    day, month = int(match.group(1)), _MONTHS[match.group(2).lower()]
    year = int(match.group(3)) if match.group(3) else captured.year
    try:
        posted = date(year, month, day)
        if match.group(3) is None and posted > captured:
            posted = date(year - 1, month, day)
    except ValueError:  # 29 February in a non-leap year, or a mangled date
        return None
    return posted

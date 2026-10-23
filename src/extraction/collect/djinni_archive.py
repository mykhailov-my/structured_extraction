"""Djinni job postings from past years, through the Wayback Machine (web.archive.org).

Djinni keeps old postings online, but a closed posting shows no date. The Wayback Machine has
snapshots of thousands of posting pages a year since 2019, each with a capture time:

1. The archive's CDX index lists the captures of djinni.co/jobs/<id>-<slug>/ pages whose slug
   contains a keyword, one query per year. The index is slow, so answers are cached.
2. A posting belongs to the year of its first capture, if its id is above every id captured
   in earlier years. Ids are sequential, so a lower one is an older posting archived late.
   A page that shows its posting date must also show that year.
3. Each year's postings are picked evenly across the year, and their first snapshots fetched
   as archived (`id_`, without the archive's toolbar). The pages are cached too, gzipped, so
   a better parser can read them again without asking the archive.
4. Djinni's markup changed several times. `parse_snapshot` reads every layout seen since 2019
   and drops recruiter names, profile links and photos, which older pages show.
"""

import gzip
import logging
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from extraction.collect import existing_ids, save
from extraction.collect.djinni_jobs import JobPage, ParseError, parse_job
from extraction.collect.html import fragment_lines, one_line, rich_lines
from extraction.collect.polite import FetchError, PoliteClient

log = logging.getLogger(__name__)

CDX_URL = "https://web.archive.org/cdx/search/cdx"
SNAPSHOT_URL = "https://web.archive.org/web/{timestamp}id_/{url}"
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
    def year(self) -> int:
        return int(self.timestamp[:4])

    @property
    def doc_id(self) -> str:
        return f"wayback-{self.year}-{self.job_id}"


@dataclass(frozen=True)
class Snapshot:
    page: JobPage
    layout: str  # "v1" (until mid-2022) to "v4" (since autumn 2024); see the README
    active: bool  # False when the page marks the posting as closed
    posted: date | None  # the posting date, when the page shows one


def crawl_archive(
    data_dir: Path,
    *,
    keyword: str,
    years: range,
    per_year: int,
    cache_dir: Path,
    delay_s: float = 5.0,
) -> dict[int, int]:
    """Save up to `per_year` postings per year; returns how many each year has now."""
    keyword = keyword.lower()
    have = existing_ids(data_dir, "job")
    saved: dict[int, int] = {}
    with PoliteClient(delay_s=delay_s, timeout_s=90, max_retries=5) as client:
        lines: list[str] = []
        missing = []
        for year in range(years.start - 2, years.stop):  # the two years before set the id floor
            try:
                lines += index(client, keyword, year, cache_dir)
            except FetchError as e:
                log.warning("archive index for %d unavailable: %s", year, e)
                missing.append(year)
        if any(year in years for year in missing):  # without it, older postings pass as new
            raise FetchError(f"no archive index for {missing}; run again, the rest is cached")
        new = new_by_year(first_captures(lines).values())
        for year in years:
            candidates = new.get(year, [])
            saved[year] = _crawl_year(client, data_dir, year, candidates, per_year, have, cache_dir)
    return saved


def index(client: PoliteClient, keyword: str, year: int, cache_dir: Path) -> list[str]:
    """Index lines "timestamp url": posting pages captured in `year` with `keyword` in the slug."""
    path = cache_dir / f"{keyword}-{year}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").splitlines()
    query = [
        ("url", "djinni.co/jobs/"),
        ("matchType", "prefix"),
        ("from", str(year)),
        ("to", str(year)),
        ("filter", "statuscode:200"),
        ("filter", f"original:.*/jobs/[0-9]+-[^/?]*{re.escape(keyword)}.*"),
        ("collapse", "urlkey"),
        ("fl", "timestamp,original"),
    ]
    lines = client.get(f"{CDX_URL}?{urlencode(query)}").text.splitlines()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return lines


def first_captures(lines: Iterable[str]) -> dict[int, Capture]:
    """The earliest capture of each posting, over all its URL variants (?from=..., new slugs)."""
    first: dict[int, Capture] = {}
    for line in lines:
        parts = line.split()
        match = _JOB_ID.search(parts[1]) if len(parts) == 2 else None
        if match is None:
            continue
        capture = Capture(int(match.group(1)), parts[0], parts[1])
        if capture.job_id not in first or capture.timestamp < first[capture.job_id].timestamp:
            first[capture.job_id] = capture
    return first


def new_by_year(captures: Iterable[Capture]) -> dict[int, list[Capture]]:
    """Postings by the year of their first capture, in time order, without those whose id is
    below an id captured in an earlier year: that posting already existed back then."""
    by_year: dict[int, list[Capture]] = defaultdict(list)
    for capture in captures:
        by_year[capture.year].append(capture)
    new: dict[int, list[Capture]] = {}
    floor = 0
    for year in sorted(by_year):
        group = by_year[year]
        new[year] = sorted((c for c in group if c.job_id > floor), key=lambda c: c.timestamp)
        floor = max([floor, *(capture.job_id for capture in group)])
    return new


def spread(captures: list[Capture], count: int) -> list[Capture]:
    """`count` captures evenly spaced through the list, which is in time order: the picks
    follow the archive through the year instead of all coming from its first weeks."""
    if len(captures) <= count:
        return list(captures)
    step = (len(captures) - 1) / (count - 1) if count > 1 else 0
    return [captures[round(number * step)] for number in range(count)]


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


def _crawl_year(
    client: PoliteClient,
    data_dir: Path,
    year: int,
    candidates: list[Capture],
    per_year: int,
    have: set[str],
    cache_dir: Path,
) -> int:
    done = sum(1 for doc_id in have if doc_id.startswith(f"wayback-{year}-"))
    log.info("%d: %d new postings in the archive, %d saved before", year, len(candidates), done)
    picks = spread(candidates, per_year)
    chosen = set(picks)
    failures = 0
    for capture in picks + [c for c in candidates if c not in chosen]:  # the rest stand in
        if done >= per_year:
            break
        if capture.doc_id in have:
            continue
        captured = datetime.strptime(capture.timestamp, "%Y%m%d%H%M%S")
        try:
            snapshot = parse_snapshot(_snapshot_html(client, capture, cache_dir), captured.date())
        except (FetchError, ParseError) as e:
            log.warning("  %s: %s", capture.url, e)
            failures += 1
            if failures == 10:
                raise FetchError("ten snapshots in a row failed; stopping") from e
            continue
        failures = 0
        if snapshot.posted and snapshot.posted.year != year:  # archived late, the floor missed it
            log.info("  %s: posted %s, not in %d", capture.url, snapshot.posted, year)
            continue
        source = {
            "url": capture.url,
            "snapshot": f"https://web.archive.org/web/{capture.timestamp}/{capture.url}",
            "captured_at": captured.isoformat(),
            "posted": snapshot.posted.isoformat() if snapshot.posted else None,
            "year": year,
            "active": snapshot.active,
            "layout": snapshot.layout,
        }
        page = snapshot.page
        save(data_dir, "job", capture.doc_id, text=page.text(), fields=asdict(page), source=source)
        have.add(capture.doc_id)
        done += 1
        log.info("  %2d  %-22s %s  %s", done, capture.doc_id, snapshot.layout, page.title[:60])
    return done


def _snapshot_html(client: PoliteClient, capture: Capture, cache_dir: Path) -> str:
    """The archived page, kept gzipped in the cache: a better parser reads it again without
    asking the archive, which is slow."""
    path = cache_dir / "pages" / f"{capture.timestamp}-{capture.job_id}.html.gz"
    if path.exists():
        return gzip.decompress(path.read_bytes()).decode("utf-8")
    html = client.get(SNAPSHOT_URL.format(timestamp=capture.timestamp, url=capture.url)).text
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".tmp")  # an interrupted write leaves no broken page behind
    partial.write_bytes(gzip.compress(html.encode("utf-8")))
    partial.replace(path)
    return html


def _parse_old(soup: BeautifulSoup) -> JobPage:
    title = soup.find("h1")
    salary_tag = title.select_one(".public-salary-item")
    salary = one_line(salary_tag) if salary_tag else ""
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
    """Breadcrumb (category, city), the details line and the sidebar, in that order."""
    crumbs = [one_line(item) for item in soup.select(".breadcrumb li")][1:]  # not "All jobs"
    # The details line (v1): ", HRM at Company", the company's link, places, experience.
    line = soup.select_one(".list-jobs__details")
    texts = (text for text in line.find_all(string=True) if text.parent.name != "a") if line else []
    details = [" ".join(text.split()).strip("· ") for text in texts]
    items = soup.select(".job-additional-info--item-text")  # "Category: <span>Python</span>"
    sidebars = soup.select(".inbox-candidate-details--body")
    card = soup.select_one("aside .card")
    sidebars += card.find_all("ul", recursive=False) if card else []
    facts = [
        *crumbs,
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

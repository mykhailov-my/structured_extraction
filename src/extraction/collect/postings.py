"""Every collected posting in one format: data/postings/<year>.jsonl, one `Posting` a line.

`build_postings` reads the pages in the crawl caches, the Wayback Machine's (see
djinni_archive) and djinni.co's (see djinni_ids), and the postings `crawl-jobs` collected
(data/scraped/job/). A posting found in several is kept once, from djinni.co when it is there,
and keeps the date its archived copy showed when Djinni's page, closed by now, shows none. The
files are rebuilt whole each time, so a parser fix reaches every posting without downloading
anything again.

Dates: `posted` is the date a page shows, when it shows one; closed postings and the pages
from May 2024 to early 2025 show none. Djinni hands out job ids in order, so `date` is
`posted`, or else the median date of the dated postings nearest in id. A posting older or newer
than every dated one stays undated.
"""

import bisect
import json
import logging
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from datetime import date
from pathlib import Path

from extraction.collect import ParseError, Posting, scrubbed, write_file
from extraction.collect.djinni_archive import Capture, captures, parse_snapshot
from extraction.collect.pagecache import read_page

log = logging.getLogger(__name__)

_NEIGHBOURS = 50  # dated postings on each side whose median dates an undated one
ARCHIVE, DJINNI = "web.archive.org", "djinni.co"


def build_postings(
    archive_dir: Path, djinni_dir: Path, scraped_dir: Path, out_dir: Path
) -> Counter[int | None]:
    """Write every posting to `out_dir`/<year>.jsonl (undated.jsonl for the rest); returns how
    many each year has."""
    live = [
        Posting.from_json(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(scraped_dir.glob("djinni-*.json"))
    ]
    by_job: dict[int, Posting] = {}
    # The more trusted source last: an archived copy, then Djinni's page, then the feed crawl.
    for posting in [*_cached(archive_dir, ARCHIVE), *_cached(djinni_dir, DJINNI), *live]:
        earlier = by_job.get(posting.job_id)
        if earlier is not None and earlier.posted and not posting.posted:
            posting = replace(posting, posted=earlier.posted)
        by_job[posting.job_id] = posting
    years: dict[int | None, list[Posting]] = defaultdict(list)
    for posting in dated(by_job.values()):
        years[posting.year].append(posting)
    for old in out_dir.glob("*.jsonl"):  # a year that has no postings any more
        old.unlink()
    for year, group in years.items():
        lines = (json.dumps(posting.to_json(), ensure_ascii=False) + "\n" for posting in group)
        write_file(out_dir / f"{year or 'undated'}.jsonl", "".join(lines))
    return Counter({year: len(group) for year, group in years.items()})


def dated(postings: Iterable[Posting]) -> list[Posting]:
    """The postings in job id order, each with `date` and `year`."""
    ordered = sorted(postings, key=lambda posting: posting.job_id)
    known = [(p.job_id, date.fromisoformat(p.posted).toordinal()) for p in ordered if p.posted]
    ids = [job_id for job_id, _ in known]
    result = []
    for posting in ordered:
        day = posting.posted
        at = bisect.bisect(ids, posting.job_id)
        if day is None and 0 < at < len(ids):  # between dated postings
            near = [ordinal for _, ordinal in known[max(0, at - _NEIGHBOURS) : at + _NEIGHBOURS]]
            day = date.fromordinal(statistics.median_low(near)).isoformat()
        result.append(replace(posting, date=day, year=int(day[:4]) if day else None))
    return result


def _cached(cache_dir: Path, source: str) -> list[Posting]:
    """A posting from each page in a crawl cache, parsed in parallel; the oldest capture of a
    posting when there are several."""
    lines = [
        line
        for path in sorted(cache_dir.glob("*.txt"))  # "timestamp url": all-2021.txt, index.txt
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    known = {capture.key: capture for group in captures(lines).values() for capture in group}
    pages = sorted((cache_dir / "pages").glob("*.html.gz"))
    tasks = [(path, known[key], source) for path in pages if (key := path.name[:-8]) in known]
    if len(tasks) < len(pages):
        log.warning("%d cached pages aren't in the index; skipped", len(pages) - len(tasks))
    found: dict[int, Posting] = {}
    failures: Counter[str] = Counter()
    with ProcessPoolExecutor() as pool:
        for result in pool.map(_read_page, tasks, chunksize=64):
            if isinstance(result, str):
                failures[result] += 1
                continue
            older = found.get(result.job_id)
            if older is None or result.captured_at < older.captured_at:
                found[result.job_id] = result
    for reason, count in failures.most_common():
        log.warning("%d pages unreadable: %s", count, reason)
    return list(found.values())


def _read_page(task: tuple[Path, Capture, str]) -> Posting | str:
    """The posting on a cached page, or why there is none."""
    path, capture, source = task
    html = read_page(path)
    try:
        snapshot = parse_snapshot(html, capture.captured_at.date())
    except ParseError as e:
        return str(e)
    posted = snapshot.posted.isoformat() if snapshot.posted else None
    return Posting(
        job_id=capture.job_id,
        url=capture.url,
        source=source,
        snapshot=capture.snapshot if source == ARCHIVE else None,
        captured_at=capture.captured_at.isoformat(),
        posted=posted,
        date=None,
        year=None,
        active=snapshot.active,
        layout=snapshot.layout,
        page=scrubbed(snapshot.page),
    )

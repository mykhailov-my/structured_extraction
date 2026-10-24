"""Every posting on djinni.co in a range of job ids.

Djinni keeps closed postings online and hands out job ids in order, so a range of ids is every
posting of a stretch of time: 2025 starts at about 700,000, and October 2026 ends near 855,000.
A posting loads by its id whatever the slug, as /jobs/<id>-x/ redirects to its URL. The pages
go to a cache like the Wayback Machine's (see `extraction.collect.pagecache`), with the URL each
was found at in <cache>/index.txt, and `extraction.collect.postings` turns them into records.

Postings are fetched in a fixed random order, so a crawl stopped at any point leaves a random
sample, `workers` at a time, each waiting `delay_s` between its requests. Djinni blocks IPs that
ask too much ("Your IP address ... has been blocked"): 8 workers at 0.5 s were blocked within
10 seconds on 23 October 2026, so the defaults are one worker at 3 s. The crawl stops at the
first sign of a block (the block page, HTTP 403, a 429 that outlasts the retries), and running
it again carries on.
"""

import logging
import random
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import UTC, datetime, timedelta
from itertools import count, islice
from pathlib import Path
from urllib.parse import urlencode

from extraction.collect.pagecache import cached_keys, failed, remember_failure, write_page
from extraction.collect.polite import FetchError, PoliteClient

log = logging.getLogger(__name__)

FIRST_2025 = 700_000  # the newest posting the archive had seen by 31 December 2024: 703,003
POSTING_URL = "https://djinni.co/jobs/{job_id}-x/"  # any slug redirects to the posting
LISTING_URL = "https://djinni.co/jobs/"  # open postings, 15 a page
_POSTING_LINK = re.compile(r'href="(/jobs/(\d+)-[^"/]+/)"')
_INDEX_LOCK = threading.Lock()  # workers append to <cache>/index.txt


def crawl_ids(
    cache_dir: Path,
    ids: Sequence[int],
    *,
    urls: Mapping[int, str] | None = None,
    workers: int = 1,
    delay_s: float = 3.0,
    limit: int | None = None,
    client: Callable[[], PoliteClient] | None = None,
) -> int:
    """Fetch the page of every posting in `ids` that isn't in the cache, at most `limit`;
    returns how many were fetched. A posting in `urls` is asked for at its own URL, saving
    Djinni the redirect. `client` makes each worker's HTTP client."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    done = {int(key.split("-")[-1]) for key in cached_keys(cache_dir)}
    done |= {int(key) for key in failed(cache_dir) if key.isdigit()}
    todo = [job_id for job_id in random.Random(0).sample(ids, len(ids)) if job_id not in done]
    log.info("%d ids, %d to fetch, %d at a time", len(ids), len(todo), workers)
    todo = todo[:limit] if limit is not None else todo
    make_client = client or (lambda: PoliteClient(delay_s=delay_s, timeout_s=30))
    local = threading.local()
    opened: list[PoliteClient] = []

    def fetch(job_id: int) -> tuple[str, int, str]:
        if not hasattr(local, "client"):
            local.client = make_client()
            opened.append(local.client)
        url = (urls or {}).get(job_id) or POSTING_URL.format(job_id=job_id)
        return _fetch(local.client, cache_dir, job_id, url)

    fetched = processed = trouble = 0
    started = time.monotonic()
    pool = ThreadPoolExecutor(max_workers=workers)
    queue = iter(todo)
    running = {pool.submit(fetch, job_id) for job_id in islice(queue, workers * 2)}
    try:
        while running:
            finished, running = wait(running, return_when=FIRST_COMPLETED)
            for future in finished:
                outcome, job_id, detail = future.result()
                processed += 1
                if outcome == "blocked":
                    raise FetchError(
                        f"djinni.co stopped answering the crawler ({detail}); wait a while,"
                        " then run again with fewer workers or a longer delay"
                    )
                if outcome == "trouble":
                    log.warning("  djinni-%d: %s", job_id, detail)
                    trouble += 1
                    if trouble == 10:
                        raise FetchError("djinni.co keeps failing; run again later")
                    continue
                trouble = 0
                if outcome == "missing":
                    remember_failure(cache_dir, str(job_id), detail)
                    continue
                fetched += 1
                log.info("%d/%d  djinni-%d  %s", processed, len(todo), job_id, detail.split()[1])
            running |= {pool.submit(fetch, job_id) for job_id in islice(queue, len(finished))}
            if processed % 1000 < len(finished):
                left = (time.monotonic() - started) / processed * (len(todo) - processed)
                log.info(
                    "%d of %d done, %d pages; about %s left",
                    *(processed, len(todo), fetched, timedelta(seconds=round(left))),
                )
    finally:
        pool.shutdown(cancel_futures=True)
        for opened_client in opened:
            opened_client.close()
    return fetched


def listed(client: PoliteClient, keyword: str) -> dict[int, str]:
    """The open postings Djinni lists for a keyword ("Python"), with their URLs."""
    found: dict[int, str] = {}
    for page in count(1):
        query = urlencode({"primary_keyword": keyword, "page": page})
        html = client.get(f"{LISTING_URL}?{query}").text
        new = {
            int(job_id): f"https://djinni.co{path}" for path, job_id in _POSTING_LINK.findall(html)
        }
        if not new.keys() - found.keys():  # past the last page
            return found
        found |= new
    raise AssertionError("unreachable")


def _fetch(client: PoliteClient, cache_dir: Path, job_id: int, url: str) -> tuple[str, int, str]:
    """("page", id, "<timestamp> <url>"), or "missing", "blocked" or "trouble" with why."""
    try:
        response = client.get(url)
    except FetchError as e:
        if e.status in (404, 410):
            return "missing", job_id, f"HTTP {e.status}"
        if e.status in (403, 429):  # the client has already waited out what 429s it could
            return "blocked", job_id, f"HTTP {e.status}"
        return "trouble", job_id, str(e)
    html = response.text
    if "<h1" not in html and "has been blocked" in html:
        return "blocked", job_id, " ".join(html.split())[:120]
    if f"/jobs/{job_id}-" not in str(response.url) or "<h1" not in html:
        return "missing", job_id, f"no posting at {response.url}"
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    # The URL first: a page cached without it would never be read, while a URL without its
    # page is only fetched again.
    with _INDEX_LOCK, (cache_dir / "index.txt").open("a", encoding="utf-8") as index:
        index.write(f"{timestamp} {response.url}\n")
    write_page(cache_dir, f"{timestamp}-{job_id}", html)
    return "page", job_id, f"{timestamp} {response.url}"

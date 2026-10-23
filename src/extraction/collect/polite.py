"""An HTTP client that behaves: it says who it is, obeys robots.txt, waits between requests to
the same host, and backs off on 429 and 5xx instead of hammering."""

import logging
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

log = logging.getLogger(__name__)

USER_AGENT = (
    "structured-extraction/0.1 (course project;"
    " +https://github.com/mykhailov-my/structured_extraction)"
)
RETRY_STATUSES = {429, 500, 502, 503, 504}


class FetchError(Exception):
    """robots.txt forbids the URL, or the server keeps failing."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status  # the HTTP status, when the server answered


class PoliteClient:
    def __init__(self, *, delay_s: float, timeout_s: float = 20, max_retries: int = 3) -> None:
        self._http = httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=timeout_s, follow_redirects=True
        )
        self._delay_s = delay_s
        self._max_retries = max_retries
        self._robots: dict[str, RobotFileParser] = {}
        self._last_request: dict[str, float] = {}

    def __enter__(self) -> "PoliteClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._http.close()

    def get(self, url: str) -> httpx.Response:
        if not self._robots_for(url).can_fetch(USER_AGENT, url):
            raise FetchError(f"robots.txt disallows {url}")
        response = self._request(url)
        if response.status_code >= 400:
            raise FetchError(f"{url}: HTTP {response.status_code}", response.status_code)
        return response

    def _robots_for(self, url: str) -> RobotFileParser:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            response = self._request(f"{origin}/robots.txt")
            rules = RobotFileParser()
            if response.status_code < 400:
                rules.parse(response.text.splitlines())
            elif response.status_code in (401, 403) or response.status_code >= 500:
                rules.disallow_all = True  # the rules exist but can't be read: assume "no"
            else:
                rules.allow_all = True  # no robots.txt: nothing is off limits
            self._robots[origin] = rules
        return self._robots[origin]

    def _request(self, url: str) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            self._wait_turn(url)
            try:
                response = self._http.get(url)
            except httpx.TransportError as e:  # timeouts, refused or dropped connections
                if attempt == self._max_retries:
                    raise FetchError(f"{url}: {e!r}") from e
                wait = self._delay_s * 2 ** (attempt + 1)
            else:
                if response.status_code not in RETRY_STATUSES or attempt == self._max_retries:
                    return response
                wait = _retry_after(response) or self._delay_s * 2 ** (attempt + 1)
            log.warning("  %s - retrying in %.0fs", url, wait)
            time.sleep(wait)
        raise AssertionError("unreachable")

    def _wait_turn(self, url: str) -> None:
        host = urlsplit(url).netloc
        elapsed = time.monotonic() - self._last_request.get(host, float("-inf"))
        if elapsed < self._delay_s:
            time.sleep(self._delay_s - elapsed)
        self._last_request[host] = time.monotonic()


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After", "")
    return min(float(value), 60.0) if value.isdigit() else None

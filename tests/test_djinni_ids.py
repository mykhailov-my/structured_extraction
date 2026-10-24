from pathlib import Path
from types import SimpleNamespace

import pytest

from extraction.collect.djinni_ids import crawl_ids, listed
from extraction.collect.polite import FetchError

PAGE = (Path(__file__).parent / "fixtures" / "djinni_job.html").read_text(encoding="utf-8")
BLOCKED = "Your IP address, 1.2.3.4, has been blocked. Please contact us at magic@djinni.co."


class FakeDjinni:
    """Answers by job id, from the posting's own URL unless an answer says where it ended up."""

    def __init__(self, answers):
        self.answers = answers
        self.urls = []
        self.closed = False

    def get(self, url):
        self.urls.append(url)
        job_id = int(url.split("/jobs/")[1].split("-")[0])
        answer = self.answers.get(job_id, PAGE)
        if isinstance(answer, Exception):
            raise answer
        html, final_url = answer if isinstance(answer, tuple) else (answer, None)
        return SimpleNamespace(text=html, url=final_url or f"https://djinni.co/jobs/{job_id}-go/")

    def close(self):
        self.closed = True


def cached_ids(cache_dir):
    return sorted(int(path.name[:-8].split("-")[1]) for path in (cache_dir / "pages").iterdir())


def test_crawl_ids_caches_postings_and_remembers_what_isnt_there(tmp_path):
    djinni = FakeDjinni(
        {
            2: FetchError("HTTP 404", status=404),
            3: (PAGE, "https://djinni.co/jobs/"),  # redirected away: no such posting
        }
    )
    cache = tmp_path / "cache"  # not there yet
    assert crawl_ids(cache, range(1, 5), workers=2, client=lambda: djinni) == 2
    assert cached_ids(cache) == [1, 4]
    urls = sorted(line.split()[1] for line in (cache / "index.txt").read_text().splitlines())
    assert urls == ["https://djinni.co/jobs/1-go/", "https://djinni.co/jobs/4-go/"]
    failed = sorted((cache / "failed.txt").read_text(encoding="utf-8").splitlines())
    assert failed == ["2 HTTP 404", "3 no posting at https://djinni.co/jobs/"]
    assert djinni.closed

    djinni.urls.clear()  # a second run asks for nothing
    assert crawl_ids(cache, range(1, 5), client=lambda: djinni) == 0
    assert djinni.urls == []


def test_crawl_ids_takes_a_random_sample_up_to_the_limit(tmp_path):
    assert crawl_ids(tmp_path, range(1, 21), limit=3, client=lambda: FakeDjinni({})) == 3
    assert len(cached_ids(tmp_path)) == 3 and cached_ids(tmp_path) != [1, 2, 3]


@pytest.mark.parametrize(
    "answer",
    [BLOCKED, FetchError("HTTP 403", status=403), FetchError("HTTP 429", status=429)],
)
def test_crawl_ids_stops_when_djinni_pushes_back(tmp_path, answer):
    djinni = FakeDjinni(dict.fromkeys(range(1, 50), answer))
    with pytest.raises(FetchError, match="stopped answering"):
        crawl_ids(tmp_path, range(1, 50), workers=4, client=lambda: djinni)
    assert len(djinni.urls) <= 8  # the requests already under way, and no more
    assert not (tmp_path / "failed.txt").exists()


def test_crawl_ids_asks_for_a_known_url_without_the_redirect(tmp_path):
    djinni = FakeDjinni({})
    known = {7: "https://djinni.co/jobs/7-python-developer/"}
    assert crawl_ids(tmp_path, [7, 8], urls=known, client=lambda: djinni) == 2
    assert sorted(djinni.urls) == [
        "https://djinni.co/jobs/7-python-developer/",
        "https://djinni.co/jobs/8-x/",
    ]


def test_listed_reads_the_pages_until_nothing_new():
    page = '<a href="/jobs/{0}-python-developer/">'
    pages = {
        "page=1": page.format(1) + page.format(2),
        "page=2": page.format(3),
        "page=3": page.format(3),
    }
    client = SimpleNamespace(
        get=lambda url: SimpleNamespace(
            text=next(text for key, text in pages.items() if key in url)
        )
    )
    assert listed(client, "Python") == {
        job_id: f"https://djinni.co/jobs/{job_id}-python-developer/" for job_id in (1, 2, 3)
    }

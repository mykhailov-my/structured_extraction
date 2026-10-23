from collections import defaultdict
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from extraction.collect.djinni_archive import (
    Capture,
    _posted,
    captures,
    fetch_pages,
    index,
    parse_snapshot,
)
from extraction.collect.polite import FetchError

FIXTURES = Path(__file__).parent / "fixtures"
OLD_PAGES = {
    layout: (FIXTURES / f"djinni_job_{layout}.html").read_text(encoding="utf-8")
    for layout in ("v1", "v2", "v2_late", "v3")
}
CURRENT_PAGE = (FIXTURES / "djinni_job.html").read_text(encoding="utf-8")


class FakeArchive:
    """Answers with the first answer whose key is in the URL; an exception is raised."""

    def __init__(self, answers):
        self.answers = answers
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        answer = next(answer for key, answer in self.answers.items() if key in url)
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(text=answer)


def postings(*captured):
    """{job id: its captures} from (job id, timestamp) pairs."""
    jobs = defaultdict(list)
    for job_id, timestamp in captured:
        url = f"https://djinni.co/jobs/{job_id}-python-developer/"
        jobs[job_id].append(Capture(job_id, timestamp, url))
    return dict(jobs)


def test_index_asks_once_per_year_and_keyword(tmp_path):
    line = "20210509101318 https://djinni.co/jobs/230930-python-developer/"
    archive = FakeArchive({"cdx": f"{line}\n"})
    assert index(archive, 2021, tmp_path, "Python") == [line]
    assert index(archive, 2021, tmp_path, "python") == [line]
    assert len(archive.urls) == 1
    query = parse_qs(urlsplit(archive.urls[0]).query)
    assert (query["from"], query["to"]) == (["2021"], ["2021"])
    assert "original:.*/jobs/[0-9]+-[^/?]*python.*" in query["filter"]


def test_index_without_a_keyword_lists_every_posting(tmp_path):
    archive = FakeArchive({"cdx": ""})
    assert index(archive, 2021, tmp_path) == []
    assert "original:.*/jobs/[0-9]+-.*" in parse_qs(urlsplit(archive.urls[0]).query)["filter"]
    assert (tmp_path / "all-2021.txt").exists()


def test_index_asks_month_by_month_when_the_year_is_too_much(tmp_path):
    line = "20210509101318 https://djinni.co/jobs/230930-python-developer/"
    archive = FakeArchive(
        {
            "from=2021&": FetchError("HTTP 503", status=503),
            "from=202105&": f"{line}\n",
            "cdx": "",
        }
    )
    assert index(archive, 2021, tmp_path) == [line]
    assert len(archive.urls) == 13
    assert (tmp_path / "all-2021.txt").read_text(encoding="utf-8") == f"{line}\n"


def test_captures_lists_every_capture_of_a_posting_oldest_first():
    found = captures(
        [
            "20210509101318 https://djinni.co/jobs/230930-python-developer/",
            "20210301000000 https://djinni.co/jobs/230930-python-developer/?from=similar_jobs5",
            "20210601000000 https://djinni.co/jobs/230931-senior-python-engineer/",
            "20210101000000 https://djinni.co/jobs/keyword-python/",
            "not an index line",
        ]
    )
    assert sorted(found) == [230930, 230931]
    assert [capture.timestamp for capture in found[230930]] == ["20210301000000", "20210509101318"]


def test_fetch_pages_stands_in_a_later_capture_and_remembers_failures(tmp_path):
    jobs = postings(
        (100, "20190105000000"),
        (100, "20190301000000"),
        (101, "20190601000000"),
        (102, "20191201000000"),
    )
    archive = FakeArchive(
        {
            "20190105000000id_": "Your IP address, 1.2.3.4, has been blocked.",
            "20190601000000id_": FetchError("HTTP 404", status=404),
            "/jobs/": OLD_PAGES["v1"],
        }
    )
    assert fetch_pages(archive, jobs, tmp_path) == 2
    cached = sorted(path.name for path in (tmp_path / "pages").iterdir())
    assert cached == ["20190301000000-100.html.gz", "20191201000000-102.html.gz"]
    failed = (tmp_path / "failed.txt").read_text(encoding="utf-8").splitlines()
    assert sorted(failed) == ["20190105000000-100 error page", "20190601000000-101 HTTP 404"]

    archive.urls.clear()  # a second run asks for nothing: pages are cached, failures remembered
    assert fetch_pages(archive, jobs, tmp_path) == 0
    assert archive.urls == []


def test_fetch_pages_takes_a_random_sample_up_to_the_limit(tmp_path):
    jobs = postings(*((job_id, "20200101000000") for job_id in range(1, 21)))
    assert fetch_pages(FakeArchive({"/jobs/": OLD_PAGES["v1"]}), jobs, tmp_path, limit=3) == 3
    cached = sorted(int(path.name[15:-8]) for path in (tmp_path / "pages").iterdir())
    assert len(cached) == 3 and cached != [1, 2, 3]


def test_fetch_pages_stops_when_the_archive_keeps_failing(tmp_path):
    jobs = postings(*((job_id, "20200101000000") for job_id in range(1, 21)))
    archive = FakeArchive({"/jobs/": FetchError("HTTP 503", status=503)})
    with pytest.raises(FetchError, match="keeps failing"):
        fetch_pages(archive, jobs, tmp_path)
    assert len(archive.urls) == 10
    assert not (tmp_path / "failed.txt").exists()  # a struggling archive says nothing of a page


def test_posted_reads_dates_in_english_ukrainian_and_russian():
    captured = date(2026, 1, 10)
    assert _posted("Job posted on 12 July 2019", captured) == date(2019, 7, 12)
    assert _posted("Опубліковано 5 січня", captured) == date(2026, 1, 5)
    assert _posted("Опубліковано 21 жовтня", captured) == date(2025, 10, 21)  # not yet in 2026
    assert _posted("Опубликована 3 марта 2021", captured) == date(2021, 3, 3)
    assert _posted("Published 30 February", captured) is None
    assert _posted("Posted on 12 Smarch", captured) is None
    assert _posted("Unpublished 11 August 2023", captured) is None


def test_parse_snapshot_reads_layout_v1():
    snapshot = parse_snapshot(OLD_PAGES["v1"], date(2019, 7, 16))
    assert (snapshot.layout, snapshot.active, snapshot.posted) == ("v1", True, date(2019, 7, 12))
    page = snapshot.page
    assert (page.title, page.company, page.salary) == (
        "Python Developer",
        "Example Co",
        "$2500-3500",
    )
    assert page.category == "Python"
    assert page.facts == ["Kyiv", "3 years of experience", "English Upper-Intermediate"]
    assert page.description == (
        "We build trading systems.\nWrite to jobs@example.com or call +380 44 123 4567.\n"
        "- Python 3, Django\n- PostgreSQL\nAbout Example Co\nA product company in Kyiv."
    )


def test_parse_snapshot_finds_the_company_in_the_recruiters_job():
    html = OLD_PAGES["v1"].replace("<h4>About Example Co</h4>", "")
    page = parse_snapshot(html, date(2019, 7, 16)).page
    assert page.company == "Example Co"
    assert "Jane" not in f"{page}"


def test_parse_snapshot_reads_layout_v2():
    snapshot = parse_snapshot(OLD_PAGES["v2"], date(2023, 3, 31))
    assert (snapshot.layout, snapshot.active, snapshot.posted) == ("v2", True, date(2023, 3, 15))
    page = snapshot.page
    assert (page.title, page.company, page.salary) == ("Python Engineer", "Example Co", "")
    assert page.category == "Python"
    assert page.facts == [
        "Category: Python",
        "English: Upper-Intermediate",
        "3 years of experience",
        "Full Remote",
    ]
    assert page.description == "Async services in FastAPI.\nRemote-first team."


def test_parse_snapshot_reads_layout_v2_from_mid_2023():
    snapshot = parse_snapshot(OLD_PAGES["v2_late"], date(2023, 12, 2))
    assert (snapshot.layout, snapshot.active, snapshot.posted) == ("v2", True, date(2023, 11, 21))
    page = snapshot.page
    assert (page.title, page.company, page.salary) == (
        "Senior Python Developer",
        "Example Co",
        "$3000-5000",
    )
    assert page.category == "Python"
    assert page.facts == ["Category: Python", "English: Intermediate", "Full Remote"]
    assert page.description == (
        "Remote work in a worldwide team.\nRequirements:\n- Python 3.10+\n- Celery, Redis\n"
        "About Example Co\nAn e-commerce platform."
    )


def test_parse_snapshot_reads_layout_v3():
    snapshot = parse_snapshot(OLD_PAGES["v3"], date(2024, 7, 25))
    assert (snapshot.layout, snapshot.active, snapshot.posted) == ("v3", False, None)
    page = snapshot.page
    assert (page.title, page.company) == ("Python Developer", "Example Co")
    assert page.category == "Python"
    assert page.facts == [
        "from Upper-Intermediate",
        "Only from 2 years of experience",
        "Countries of Europe",
        "Python",
        "Domain: Fintech",
    ]
    assert page.description == "Tasks\n- Build data pipelines in Airflow"


def test_parse_snapshot_reads_layout_v4_the_current_one():
    snapshot = parse_snapshot(CURRENT_PAGE, date(2026, 10, 22))
    assert (snapshot.layout, snapshot.active, snapshot.posted) == ("v4", False, date(2026, 10, 21))
    assert snapshot.page.title == "Senior Go Engineer"


def test_parse_snapshot_falls_back_to_the_title_for_the_company():
    html = CURRENT_PAGE.replace(">Example Co</a>", "></a>")  # "Senior Go Engineer в Example Co"
    assert parse_snapshot(html, date(2026, 10, 22)).page.company == "Example Co"


@pytest.mark.parametrize("layout", ["v1", "v2", "v2_late"])
def test_parse_snapshot_leaves_out_the_recruiter(layout):
    page = parse_snapshot(OLD_PAGES[layout], date(2023, 12, 31)).page
    assert "Jane" not in f"{page}{page.text()}"

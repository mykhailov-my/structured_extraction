import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from extraction.collect import existing_ids
from extraction.collect.djinni_archive import (
    Capture,
    _crawl_year,
    _posted,
    first_captures,
    index,
    new_by_year,
    parse_snapshot,
    spread,
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


def test_index_asks_once_per_year_and_keyword(tmp_path):
    line = "20210509101318 https://djinni.co/jobs/230930-python-developer/"
    archive = FakeArchive({"cdx": f"{line}\n"})
    assert index(archive, "python", 2021, tmp_path) == [line]
    assert index(archive, "python", 2021, tmp_path) == [line]
    assert len(archive.urls) == 1
    query = parse_qs(urlsplit(archive.urls[0]).query)
    assert (query["from"], query["to"]) == (["2021"], ["2021"])
    assert "original:.*/jobs/[0-9]+-[^/?]*python.*" in query["filter"]


def test_first_captures_keeps_the_earliest_capture_of_each_posting():
    lines = [
        "20210509101318 https://djinni.co/jobs/230930-python-developer/",
        "20210301000000 https://djinni.co/jobs/230930-python-developer/?from=similar_jobs5",
        "20210601000000 https://djinni.co/jobs/230931-senior-python-engineer/",
        "20210101000000 https://djinni.co/jobs/keyword-python/",
        "not an index line",
    ]
    assert first_captures(lines) == {
        230930: Capture(
            230930,
            "20210301000000",
            "https://djinni.co/jobs/230930-python-developer/?from=similar_jobs5",
        ),
        230931: Capture(
            230931, "20210601000000", "https://djinni.co/jobs/230931-senior-python-engineer/"
        ),
    }


def test_new_by_year_drops_postings_older_than_last_years():
    captures = [
        Capture(500, "20190601000000", "/jobs/500-a/"),
        Capture(900, "20191101000000", "/jobs/900-b/"),
        Capture(950, "20200301000000", "/jobs/950-c/"),
        Capture(700, "20200201000000", "/jobs/700-d/"),  # posted before 900, first archived later
        Capture(990, "20200101000000", "/jobs/990-e/"),
    ]
    new = new_by_year(captures)
    assert [capture.job_id for capture in new[2019]] == [500, 900]
    assert [capture.job_id for capture in new[2020]] == [990, 950]  # in time order


def test_spread_picks_evenly_across_the_year():
    captures = [Capture(month, f"2021{month:02d}01000000", "") for month in range(1, 13)]
    assert [capture.job_id for capture in spread(captures, 4)] == [1, 5, 8, 12]
    assert [capture.job_id for capture in spread(captures, 1)] == [1]
    assert spread(captures, 20) == captures


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
    assert page.facts == ["Python", "Kyiv", "3 years of experience", "English Upper-Intermediate"]
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
    assert page.facts == [
        "Python",
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
    assert page.facts == ["Python", "Category: Python", "English: Intermediate", "Full Remote"]
    assert page.description == (
        "Remote work in a worldwide team.\nRequirements:\n- Python 3.10+\n- Celery, Redis\n"
        "About Example Co\nAn e-commerce platform."
    )


def test_parse_snapshot_reads_layout_v3():
    snapshot = parse_snapshot(OLD_PAGES["v3"], date(2024, 7, 25))
    assert (snapshot.layout, snapshot.active, snapshot.posted) == ("v3", False, None)
    page = snapshot.page
    assert (page.title, page.company) == ("Python Developer", "Example Co")
    assert page.facts == [
        "Python",
        "from Upper-Intermediate",
        "Only from 2 years of experience",
        "Countries of Europe",
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


def test_crawl_year_replaces_late_and_failed_picks_and_resumes(tmp_path):
    url = "https://djinni.co/jobs/{}-python-developer/"
    captures = [
        Capture(100, "20190105000000", url.format(100)),
        Capture(101, "20190301000000", url.format(101)),
        Capture(102, "20190601000000", url.format(102) + "?from=list"),
        Capture(103, "20191201000000", url.format(103)),
    ]
    archive = FakeArchive(
        {
            "/100-": OLD_PAGES["v1"].replace("12 July 2019", "3 December 2018"),
            "/103-": FetchError("HTTP 404"),
            "/jobs/": OLD_PAGES["v1"],
        }
    )
    cache = tmp_path / "cache"
    # spread() picks 100 and 103: one was posted in 2018, the other fails; 101 and 102 stand in
    assert _crawl_year(archive, tmp_path, 2019, captures, 2, have=set(), cache_dir=cache) == 2
    assert existing_ids(tmp_path, "job") == {"wayback-2019-101", "wayback-2019-102"}
    assert archive.urls[-1] == (
        "https://web.archive.org/web/20190601000000id_/"
        "https://djinni.co/jobs/102-python-developer/?from=list"
    )
    record = json.loads((tmp_path / "scraped" / "job" / "wayback-2019-102.json").read_text())
    assert record["snapshot"] == (
        "https://web.archive.org/web/20190601000000/"
        "https://djinni.co/jobs/102-python-developer/?from=list"
    )
    assert (record["year"], record["posted"], record["active"], record["layout"]) == (
        2019,
        "2019-07-12",
        True,
        "v1",
    )
    text = (tmp_path / "texts" / "job" / "wayback-2019-102.txt").read_text(encoding="utf-8")
    assert "Write to [email] or call [phone]." in text
    assert "Jane" not in text

    # Saved postings are skipped. A deleted one is parsed again from the cached page; only the
    # page that failed is asked for again.
    (tmp_path / "texts" / "job" / "wayback-2019-101.txt").unlink()
    archive.urls.clear()
    have = existing_ids(tmp_path, "job")
    assert _crawl_year(archive, tmp_path, 2019, captures, 2, have=have, cache_dir=cache) == 2
    assert existing_ids(tmp_path, "job") == {"wayback-2019-101", "wayback-2019-102"}
    assert archive.urls == [
        "https://web.archive.org/web/20191201000000id_/https://djinni.co/jobs/103-python-developer/"
    ]

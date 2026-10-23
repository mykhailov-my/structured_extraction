import gzip
import json
from collections import Counter
from pathlib import Path

from extraction.collect import JobPage, Posting, save_posting
from extraction.collect import postings as postings_module
from extraction.collect.postings import build_postings, dated

FIXTURES = Path(__file__).parent / "fixtures"
V1_PAGE = (FIXTURES / "djinni_job_v1.html").read_text(encoding="utf-8")  # posted 12 July 2019
V3_PAGE = (FIXTURES / "djinni_job_v3.html").read_text(encoding="utf-8")  # closed, no date
PAGE = JobPage("Go Engineer", "Golang", "Example Co", "", [], [], [], "Go services.")


def posting(job_id, posted=None, source="web.archive.org"):
    url = f"https://djinni.co/jobs/{job_id}-python-developer/"
    return Posting(
        job_id, url, source, None, "2020-01-01T00:00:00", posted, None, None, True, "v1", PAGE
    )


def test_dated_takes_the_page_date_or_the_median_of_the_nearest_dated_ids(monkeypatch):
    monkeypatch.setattr(postings_module, "_NEIGHBOURS", 1)  # one dated posting on each side
    found = dated(
        [
            posting(40),
            posting(30, "2020-02-10"),
            posting(25),
            posting(20, "2020-01-10"),
            posting(10, "2019-06-01"),
            posting(5),
        ]
    )
    assert [(p.job_id, p.date, p.year) for p in found] == [
        (5, None, None),  # older than every dated posting
        (10, "2019-06-01", 2019),
        (20, "2020-01-10", 2020),
        (25, "2020-01-10", 2020),  # between 20 and 30; 10 is too far away to count
        (30, "2020-02-10", 2020),
        (40, None, None),  # newer than every dated posting
    ]


def test_build_postings_merges_the_archive_and_the_live_crawl(tmp_path):
    cache, data, out = tmp_path / ".cache", tmp_path / "data", tmp_path / "data" / "postings"
    archived = {
        "20190716000000-98": V1_PAGE,
        "20190717000000-100": V1_PAGE,  # crawled live too: that copy is kept
        "20240725000000-101": V3_PAGE,  # newer than every dated posting
        "20240726000000-102": "<html><h1>Python Developer</h1></html>",  # no description
    }
    (cache / "pages").mkdir(parents=True)
    index = []
    for key, html in archived.items():
        (cache / "pages" / f"{key}.html.gz").write_bytes(gzip.compress(html.encode("utf-8")))
        timestamp, job_id = key.split("-")
        index.append(f"{timestamp} https://djinni.co/jobs/{job_id}-python-developer/\n")
    (cache / "all-2019.txt").write_text("".join(index), encoding="utf-8")
    save_posting(data, posting(100, "2019-07-20", source="djinni.co"))
    out.mkdir()
    (out / "2018.jsonl").write_text("from an earlier build\n", encoding="utf-8")

    assert build_postings(cache, data / "scraped" / "job", out) == Counter({2019: 2, None: 1})
    assert sorted(path.name for path in out.iterdir()) == ["2019.jsonl", "undated.jsonl"]
    lines = (out / "2019.jsonl").read_text(encoding="utf-8").splitlines()
    in_2019 = [json.loads(line) for line in lines]
    assert [(r["doc_id"], r["source"], r["date"]) for r in in_2019] == [
        ("djinni-98", "web.archive.org", "2019-07-12"),
        ("djinni-100", "djinni.co", "2019-07-20"),
    ]
    assert "Write to [email] or call [phone]." in in_2019[0]["description"]
    undated = json.loads((out / "undated.jsonl").read_text(encoding="utf-8"))
    assert (undated["doc_id"], undated["layout"], undated["active"]) == ("djinni-101", "v3", False)
    assert undated["snapshot"] == (
        "https://web.archive.org/web/20240725000000/https://djinni.co/jobs/101-python-developer/"
    )

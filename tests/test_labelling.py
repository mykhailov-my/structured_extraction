import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from extraction.data import load_golden
from extraction.labelling import LabelStore, dump_label, make_server

LABEL = {
    "title": "Python Developer",
    "seniority": "middle",
    "company_type": "product",
    "domain": "fintech",
    "employment": "full_time",
    "work_formats": ["remote"],
    "candidate_location": "ukraine",
    "candidate_countries": [],
    "office_cities": [],
    "min_experience_years": 2.0,
    "salary": {"min_amount": 3000, "max_amount": 4000, "currency": "USD", "period": "month"},
    "languages": [{"language": "english", "level": "b2", "must_have": True}],
    "hard_skills": [
        {"skill": "python", "name": "Python", "level": "middle", "years": 2.0, "must_have": True}
    ],
    "soft_skills": [],
    "domain_experience": [],
    "legal": [{"condition": "military_registration", "detail": None, "must_have": True}],
}


@pytest.fixture
def page(tmp_path):
    """The labelling server over two texts, and a function that calls it."""
    texts = tmp_path / "texts" / "job"
    texts.mkdir(parents=True)
    for doc_id in ("djinni-1", "djinni-2"):
        (texts / f"{doc_id}.txt").write_text(f"Title of {doc_id}\n\nThe posting.\n", "utf-8")
    server = make_server(LabelStore(tmp_path), port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    root = f"http://127.0.0.1:{server.server_address[1]}"

    def call(path, label=None, host=None):
        data = None if label is None else json.dumps(label).encode()
        request = Request(root + path, data=data, method="GET" if data is None else "PUT")
        if host:
            request.add_header("Host", host)
        try:
            with urlopen(request) as response:
                return response.status, json.loads(response.read())
        except HTTPError as e:
            return e.code, json.loads(e.read())

    yield call, tmp_path
    server.shutdown()
    server.server_close()


def test_the_page_lists_the_postings_by_title_and_shows_one(page):
    call, _ = page
    status, body = call("/api/postings")
    assert status == 200
    assert sorted(p["title"] for p in body["postings"]) == [
        "Title of djinni-1",
        "Title of djinni-2",
    ]
    assert body["options"]["skill_level"] == ["basic", "junior", "middle", "senior", "expert"]
    postgres = next(s for s in body["options"]["hard_skill"] if s["id"] == "postgresql")
    assert (postgres["area"], "Postgres" in postgres["aliases"]) == ("Databases", True)
    status, posting = call("/api/postings/djinni-2")
    assert (status, posting["text"], posting["label"]) == (
        200,
        "Title of djinni-2\n\nThe posting.\n",
        None,
    )


def test_saving_writes_the_label_where_eval_reads_it(page):
    call, data_dir = page
    status, _ = call("/api/postings/djinni-1", LABEL)
    assert status == 200
    assert load_golden(data_dir, "job")["djinni-1"].model_dump(mode="json") == LABEL
    lines = (data_dir / "golden" / "job" / "djinni-1.json").read_text("utf-8").splitlines()
    python = (
        '{"skill": "python", "name": "Python", "level": "middle", "years": 2.0, "must_have": true}'
    )
    assert f"    {python}" in lines  # a requirement a line
    _, body = call("/api/postings")
    assert {p["doc_id"]: p["done"] for p in body["postings"]} == {
        "djinni-1": True,
        "djinni-2": False,
    }


def test_a_label_that_breaks_the_schema_is_refused_with_the_reason(page):
    call, data_dir = page
    inverted = {**LABEL, "salary": {**LABEL["salary"], "min_amount": 5000}}
    status, body = call("/api/postings/djinni-1", inverted)
    assert status == 422
    assert any("greater than max_amount" in error for error in body["errors"])
    assert not (data_dir / "golden" / "job").exists()


def test_a_label_on_disk_is_verified_once_saved_on_the_page(page):
    """Claude writes the golden labels and a person verifies each one by saving it here."""
    call, data_dir = page
    for folder in ("golden/job", "golden/claude/job"):
        (data_dir / folder).mkdir(parents=True, exist_ok=True)
        (data_dir / folder / "djinni-1.json").write_text(dump_label(LABEL), "utf-8")
    _, posting = call("/api/postings/djinni-1")
    assert (posting["label"], posting["verified"], posting["comparison"]) == (LABEL, False, None)
    _, body = call("/api/postings")
    assert not any(p["done"] for p in body["postings"])

    _, body = call("/api/postings/djinni-1", LABEL)  # checked, nothing to change
    assert body["comparison"] == {"agreement": 1.0, "differences": []}
    assert (data_dir / "golden" / "verified.txt").read_text() == "djinni-1\n"
    _, posting = call("/api/postings/djinni-1")
    assert posting["verified"]


def test_claudes_label_shows_only_once_yours_is_saved(page):
    call, data_dir = page
    claude = data_dir / "golden" / "claude" / "job"
    claude.mkdir(parents=True)
    senior_python = {**LABEL["hard_skills"][0], "level": "senior"}
    claudes = {**LABEL, "seniority": "senior", "hard_skills": [senior_python]}
    (claude / "djinni-1.json").write_text(dump_label(claudes), "utf-8")
    _, posting = call("/api/postings/djinni-1")
    assert posting["comparison"] is None  # labelling stays blind

    _, body = call("/api/postings/djinni-1", LABEL)
    differences = {d["field"]: (d["yours"], d["claude"]) for d in body["comparison"]["differences"]}
    assert differences == {
        "seniority": ("middle", "senior"),
        "hard_skills.level": (
            {"name": "python", "level": "middle"},
            {"name": "python", "level": "senior"},
        ),
    }
    assert 0 < body["comparison"]["agreement"] < 1
    assert body["agreement"]["postings"] == 1
    assert body["agreement"]["fields"]["hard_skills.level"] == 0.0


def test_only_the_postings_to_label_can_be_read_or_written(page):
    call, data_dir = page
    assert call("/api/postings/djinni-3")[0] == 404
    assert call("/api/postings/..%2F..%2Fconfig", LABEL)[0] == 404
    assert call("/api/postings", host="evil.example:80")[0] == 403  # a rebound domain
    assert not (data_dir / "golden").exists()


def test_dump_label_reads_back_the_same():
    assert json.loads(dump_label(LABEL)) == LABEL
    assert json.loads(dump_label({**LABEL, "hard_skills": []}))["hard_skills"] == []

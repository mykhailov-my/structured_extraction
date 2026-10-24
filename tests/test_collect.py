import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from extraction.collect import Posting, save_posting
from extraction.collect.djinni_jobs import FeedItem, discover, feed_date, parse_job, pick
from extraction.collect.scrub import scrub

JOB_PAGE = (Path(__file__).parent / "fixtures" / "djinni_job.html").read_text(encoding="utf-8")

RSS = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Latest Job Vacancies at Djinni</title>
<item><title>Go Engineer</title><link>https://djinni.co/jobs/111-go-engineer/</link>
  <pubDate>Wed, 21 Oct 2026 10:00:00 +0300</pubDate><category>Golang</category><category/></item>
<item><title>Not a posting</title><link>https://djinni.co/jobs/</link></item>
</channel></rss>"""


class FeedClient:
    def __init__(self, body):
        self.body = body
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return SimpleNamespace(content=self.body)


def test_parse_job_reads_the_parts_of_the_page():
    page = parse_job(JOB_PAGE)
    assert page.category == "Golang"
    assert (page.title, page.company, page.salary) == (
        "Senior Go Engineer",
        "Example Co",
        "$4000-5500",
    )
    assert page.skills == ["Go", "PostgreSQL", "Kafka", "Kubernetes"]
    assert page.languages == ["Англійська: B2 – Вище середнього"]
    assert page.facts == [
        "Виключно від 5 років досвіду",
        "Офіс або віддалено на вибір",
        "Україна",
        "Країни, де розглядаємо кандидатів",
        "Golang",
        "Домен: Fintech",
        "Продуктова",
    ]
    assert page.description == (
        "About us: we build payment infrastructure.\nWrite to hr@example.com.\n"
        "- 5+ years with Go\n- PostgreSQL, Kafka"
    )


def test_skills_with_years_stay_whole_and_out_of_the_languages():
    """Since 2025 a skill can come with the years of experience asked for in it. Those rows
    look like the language rows, and the sidebar repeats them in a table."""
    rows = "".join(
        f'<div class="detail-rows__line"><span class="detail-rows__name">{name}</span>'
        f'<span class="detail-rows__rule"></span><span class="detail-rows__value">{years}</span>'
        "</div>"
        for name, years in (("Go", "3 роки"), ("Kafka", "6 місяців"))
    )
    html = JOB_PAGE.replace(
        "<div><span>Go, PostgreSQL</span>",
        f'<div class="detail-rows">{rows}</div><div><span>PostgreSQL</span>',
    ).replace(
        '<div class="fw-medium">Golang</div>',
        '<div class="fw-medium">Golang</div><table><tr><td>Go</td><td>3 роки</td></tr></table>',
    )
    page = parse_job(html)
    assert page.skills == ["Go: 3 роки", "Kafka: 6 місяців", "PostgreSQL", "Kafka", "Kubernetes"]
    assert page.languages == ["Англійська: B2 – Вище середнього"]
    assert "3 роки" not in page.facts


@pytest.mark.parametrize(
    "marks",
    [
        '<span class="public-salary-item">to $1500</span><b class="text-danger">(offline)</b>',
        '<span class="text-success text-nowrap">to $1500</span> <span class="badge">Offline</span>',
    ],
)
def test_parse_job_reads_the_title_as_it_was_in_2024(marks):
    """Until early 2025 the title held the salary and "(offline)", and companies were linked as
    /jobs/?company=<slug>."""
    html = (
        JOB_PAGE.replace(
            '<div class="col-auto"><div class="fs-3 fw-bold">$4000-5500</div></div>', ""
        )
        .replace("/jobs/company-example-co/", "/jobs/?company=example-co-1a2b3")
        .replace('<span class="badge fs-5 rounded-1">Неактивна</span>', marks)
    )
    page = parse_job(html)
    assert (page.title, page.company, page.salary) == (
        "Senior Go Engineer",
        "Example Co",
        "to $1500",
    )


def test_the_text_reads_like_the_page():
    text = parse_job(JOB_PAGE).text()
    assert text.startswith("Senior Go Engineer\nExample Co\n$4000-5500\n\nAbout us:")
    assert (
        "\n\nНеобхідні навички\nGo, PostgreSQL, Kafka, Kubernetes\n"
        "Вимоги до володіння мовами\nАнглійська: B2 – Вище середнього\n\n"
    ) in text
    assert text.endswith("Домен: Fintech\nПродуктова\n")


def test_page_chrome_is_left_out():
    text = parse_job(JOB_PAGE).text()
    chrome = ["Відгукнутися", "переглядів", "Опубліковано", "+ ще", "Швидко", "Відповідали"]
    assert not [fragment for fragment in chrome if fragment in text]
    assert "$2000-2800" not in text  # the salary hint for similar vacancies, not this job's


def test_a_salary_level_without_an_amount_is_dropped():
    assert parse_job(JOB_PAGE.replace("$4000-5500", "$$$")).salary == ""


def test_save_posting_scrubs_the_page_but_not_the_source(tmp_path):
    page = parse_job(JOB_PAGE)  # "Write to hr@example.com" in the description
    posting = Posting(
        job_id=1,
        url="https://djinni.co/jobs/1-go/",
        source="djinni.co",
        snapshot=None,
        captured_at="2026-10-22T10:00:00+00:00",
        posted="2026-10-21",
        date="2026-10-21",
        year=2026,
        active=True,
        layout="v4",
        page=page,
    )
    save_posting(tmp_path, posting)
    text = (tmp_path / "texts/job/djinni-1.txt").read_text(encoding="utf-8")
    assert "Write to [email]." in text
    record = json.loads((tmp_path / "scraped/job/djinni-1.json").read_text(encoding="utf-8"))
    assert list(record)[:4] == ["doc_id", "job_id", "url", "source"]
    assert (record["doc_id"], record["url"], record["category"]) == (
        "djinni-1",
        "https://djinni.co/jobs/1-go/",
        "Golang",
    )
    assert "[email]" in record["description"]
    assert Posting.from_json(record).page.text() == text


def test_feed_date_reads_the_rss_date():
    assert feed_date("Wed, 21 Oct 2026 17:02:43 +0300") == "2026-10-21"
    assert feed_date("") is None


def test_scrub_removes_contacts_but_keeps_salaries_and_years():
    text = "Mail hr@example.com, call +380 67 123 45 67, see t.me/hr_bot or @hr_manager."
    assert scrub(text) == "Mail [email], call [phone], see [link] or [handle]."
    untouched = "Pay $3000 - 4500 net; worked 2019-2021 2021-2023."
    assert scrub(untouched) == untouched


def test_scrub_removes_messenger_usernames_and_introduced_names():
    text = "Меня зовут Елена, я рекрутер. Резюме надсилайте в телеграм Ivan_hr."
    assert scrub(text) == "Меня зовут [name], я рекрутер. Резюме надсилайте в телеграм [handle]."
    assert scrub("My name is Anna Smith and") == "My name is [name] and"
    untouched = "Experience in Telegram bots; post in Telegram channels; my name is irrelevant."
    assert scrub(untouched) == untouched


def test_discover_reads_the_feed():
    client = FeedClient(RSS)
    postings = discover(client, ["QA Automation"])
    assert client.urls == ["https://djinni.co/jobs/rss/?primary_keyword=QA+Automation"]
    assert [(p.job_id, p.category, p.title) for p in postings] == [("111", "Golang", "Go Engineer")]


def test_pick_spreads_over_categories_and_skips_what_we_have():
    categories = ["Python", "Python", "Python", "QA", "QA", "Design"]
    items = [FeedItem(str(i), f"/jobs/{i}-x/", "t", c, "") for i, c in enumerate(categories)]
    picked = pick(items, count=4, skip={"djinni-0"})
    assert [item.job_id for item in picked] == ["1", "3", "5", "2"]

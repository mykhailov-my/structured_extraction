"""The RAG's corpus under data/rag/raw/: Djinni postings as pages (djinni/) and official
documents on working in Ukrainian IT as PDF and DOCX files (official/), each folder with a
sources.json saying where every file came from.

The postings are picked by hand (POSTINGS) from the pages the crawlers cached in .cache/ and
copied without what identifies a person: the recruiter's name, link and photo, images, scripts
other than the posting's structured data, HTML comments, and contact details in the text.
Everything else stays, Djinni's navigation and the Wayback Machine's toolbar included, for
ingestion to clean up.

The official documents were downloaded from government sites (sources.json has each URL). The
copies here are redacted (REDACTIONS): the names of the people who signed or prepared a letter
and their direct phones, a presenter's name, and every file's metadata (authors, editors).
Organisations' addresses and switchboard numbers stay.
"""

import json
import re
from pathlib import Path

import pymupdf
from bs4 import BeautifulSoup, Comment
from docx import Document as open_docx

from extraction.collect import write_file
from extraction.collect.pagecache import page_path, read_page
from extraction.collect.scrub import scrub

POSTINGS: dict[str, list[int]] = {
    # The extraction golden set, Python postings of 2025-2026, but for 846467: it was
    # collected as text, so there is no page of it.
    "golden": [
        37050,
        706772,
        712120,
        719228,
        726177,
        727693,
        730269,
        730756,
        730767,
        731104,
        744638,
        762194,
        764691,
        772946,
        780925,
        794469,
        816082,
        819872,
        827023,
        842580,
        842647,
        852050,
        852724,
        854358,
        854360,
        854363,
        854516,
        854534,
        854590,
    ],  # fmt: skip
    # The same text reposted under a new id: RenovateHub's trainee posting (712120) twice,
    # Luxoft's lead posting (816533) once. Ingestion must keep one copy of each.
    "reposts": [709945, 720067, 817680],
    # Earlier and later postings of companies that hire Python developers every year: postings
    # that look alike, and what a company offered in 2019 against what it offers now.
    "same_company": [
        73123,
        816533,  # Luxoft, 2019 and 2026
        71023,
        851569,  # Sigma Software, 2019 and 2026
        155191,
        436718,
        850751,  # GlobalLogic, 2020, 2022 and 2026
        159551,
        712774,
        853661,  # Ajax Systems, 2020, 2025 and 2026
        73202,
        819462,  # DataArt, 2019 and 2026
        163455,
        849435,  # N-iX, 2020 and 2026
        87455,
        750869,  # Intellias, 2019 and 2025
        641579,
        796064,  # Dataforest, 2024 and 2026
    ],  # fmt: skip
}
CACHES = {"djinni.co": "djinni", "web.archive.org": "wayback"}  # a source's folder in .cache/
# Text to black out in the official PDFs, found by reading them: names and direct phones.
REDACTIONS: dict[str, list[str]] = {
    "reservation-average-salary-letter-minekonomiky-2026-08-07.pdf": [
        "Віталій КІНДРАТІВ",
        "Наталія Назарок 200-47-73*39-51",
    ],
    "reservation-reissue-letter-minekonomiky-2023-08-18.pdf": [
        "Ігор ФОМЕНКО",
        "Олег Парфенчук (044) 253 52 91",
    ],
    "reservation-reissue-letter-minekonomiky-2024-01-10.pdf": [
        "Ігор ФОМЕНКО",
        "Олег Парфенчук (044) 253 52 91",
    ],
    "martial-law-labour-relations-supreme-court-2025-12-24.pdf": ["Ольга СТУПАК"],
}
_PERSON = ", ".join(
    [
        "img",
        "picture",
        "[class*=userpic]",
        "[class*=recruiter]",
        'a[href*="/r/"]',  # a recruiter's profile, with their name as the link's text
        "noscript",
        "iframe",
    ]
)


def build_corpus(postings_dir: Path, cache_dir: Path, out_dir: Path) -> list[dict]:
    """Copy each picked posting's page from the crawl cache into out_dir, and list them in
    out_dir/sources.json. Returns that list."""
    records = {
        record["job_id"]: record
        for path in sorted(postings_dir.glob("*.jsonl"))
        for record in map(json.loads, path.read_text(encoding="utf-8").splitlines())
    }
    sources = []
    for group, job_ids in POSTINGS.items():
        for job_id in job_ids:
            record = records[job_id]
            page = _cached_page(cache_dir, record)
            file = f"{record['doc_id']}.html"
            write_file(out_dir / file, without_people(read_page(page)))
            sources.append(
                {
                    "file": file,
                    "doc_id": record["doc_id"],
                    "group": group,
                    "url": record["url"],
                    "source": record["source"],
                    "snapshot": record["snapshot"],
                    "captured_at": record["captured_at"],
                    "posted": record["posted"],
                    "date": record["date"],
                }
            )
    write_file(out_dir / "sources.json", json.dumps(sources, ensure_ascii=False, indent=2) + "\n")
    return sources


def _cached_page(cache_dir: Path, record: dict) -> Path:
    """The cached page the posting's record was read from, or else any page of it."""
    timestamp = re.sub(r"\D", "", record["captured_at"])[:14]
    page = page_path(cache_dir / CACHES[record["source"]], f"{timestamp}-{record['job_id']}")
    if page.exists():
        return page
    pages = sorted(cache_dir.glob(f"*/pages/*-{record['job_id']}.html.gz"))
    if not pages:
        raise FileNotFoundError(f"no cached page of {record['doc_id']}")
    return pages[-1]


def without_people(html: str) -> str:
    """The page without what identifies a person; see the module's docstring."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select(_PERSON):
        tag.decompose()
    for script in soup.find_all("script"):
        if script.get("type") != "application/ld+json":
            script.decompose()
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    for link in soup.find_all("a", href=re.compile(r"^(mailto|tel):")):
        del link["href"]
    for text in soup.find_all(string=True):
        if (clean := scrub(str(text))) != text:
            text.replace_with(clean)
    return str(soup)


def redact_official(folder: Path) -> list[str]:
    """Black out REDACTIONS in the official PDFs and clear every file's metadata, in place.
    Returns what was not found: a redaction that found nothing is a typo or already done."""
    missing = []
    for path in sorted(folder.iterdir()):
        if path.suffix == ".pdf":
            pdf = pymupdf.open(path)
            for phrase in REDACTIONS.get(path.name, []):
                found = False
                for page in pdf:
                    for rect in page.search_for(phrase):
                        page.add_redact_annot(rect, fill=(0, 0, 0))
                        found = True
                    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
                if not found:
                    missing.append(f"{path.name}: {phrase}")
            pdf.set_metadata({})
            pdf.del_xml_metadata()
            partial = path.with_name(f"{path.name}.tmp")
            pdf.save(partial, garbage=4, deflate=True)
            pdf.close()
            partial.replace(path)
        elif path.suffix == ".docx":
            document = open_docx(str(path))
            properties = document.core_properties
            for name in ("author", "last_modified_by", "comments", "category", "keywords"):
                setattr(properties, name, "")
            document.save(str(path))
    return missing

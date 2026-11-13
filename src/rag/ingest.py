"""Ingestion: every raw file under data/rag/raw/ as one clean Markdown document with its
metadata.

- Extraction keeps the structure: headings, list items and tables become Markdown.
  - Djinni pages go through the crawler's parser, which drops the page's chrome (navigation,
    buttons, the archive's toolbar) and keeps the posting: title, company, salary,
    description, skills, languages and Djinni's facts. A short line of the description that
    ends with ":", or that opens a list, is the description's own section title.
  - PDF: PyMuPDF's lines with their font size and weight. Larger or bold short lines are
    headings, bullets and "1)" items are list items, and tables are found and kept as tables.
    A page's blocks are read in layout order (recursive XY-cut), so side-by-side columns,
    such as a flowchart's two branches, are read one after the other, not line by line.
  - DOCX: python-docx's paragraphs with their styles, numbered items and tables.
  - In laws, "Розділ", "Глава" and "Стаття" lines are headings whatever their font.
- Cleaning: Unicode NFC; non-breaking, thin and zero-width spaces and soft hyphens; words
  hyphenated across PDF lines; a PDF's running headers, footers and page numbers (a line at a
  page's top or bottom that repeats on most pages); runs of blank lines. Contact details in
  postings are scrubbed (the corpus is public).
- Deduplication: a SHA-256 of the cleaned text without the posting's date. A second copy is
  marked a duplicate of the newest one and left out of the index. Texts that differ a little
  (word 5-shingles, Jaccard >= 0.85), and the editions of one official document, are all kept,
  and each older one is marked superseded by the newest.
"""

import hashlib
import itertools
import json
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import pymupdf
from docx import Document as open_docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from extraction.collect import JobPage, scrubbed
from extraction.collect.djinni_archive import parse_snapshot

NEAR_DUPLICATE = 0.85  # Jaccard over word 5-shingles
_INVISIBLE = dict.fromkeys(map(ord, "­​‌‍⁠﻿"), None)
_SPACES = re.compile(r"[ \t    ]+")
_BULLET = re.compile(r"^(?:[•▪◦●■□➢✓✔–—-]|\d{1,2}[.)](?=\s)|[а-яіїєa-z]\)(?=\s))\s*")
_LAW_HEADING = re.compile(
    r"^(?:(?P<two>розділ\s+[IVXLC\d]+|глава\s+\d+)|(?P<three>стаття\s+\d+(?:-\d+)?\.?))(?:\s|$)",
    re.IGNORECASE,
)
_PAGE_NUMBER = re.compile(
    r"^(?:[-–—]?\s*\d{1,3}\s*[-–—]?|(?:сторінка|page)\s+\d+(?:\s+(?:з|of)\s+\d+)?)$", re.I
)


@dataclass
class Document:
    doc_id: str  # "djinni-712120", or the official file's name without its extension
    kind: str  # "posting" or "official"
    format: str  # "html", "pdf" or "docx"
    title: str
    source: str  # the posting's URL, or the page the document was downloaded from
    date: str | None  # a posting's date or an official document's edition, YYYY-MM-DD
    language: str  # "uk", "ru", "en" or "mixed"
    company: str | None  # a posting's employer, or the document's publisher
    text: str  # Markdown
    raw_file: str  # relative to data/rag/raw/
    raw_sha256: str
    sha256: str  # of the text without the posting's date line
    status: str = "kept"  # or "duplicate", left out of the index
    duplicate_of: str | None = None
    superseded_by: str | None = None  # the newest version of a text that changed little

    @property
    def current(self) -> bool:
        return self.superseded_by is None


def ingest(raw_dir: Path) -> list[Document]:
    """Every raw document, extracted, cleaned and deduplicated, newest first."""
    documents = [*_postings(raw_dir / "djinni"), *_official(raw_dir / "official")]
    documents.sort(key=lambda doc: (doc.date or "", doc.doc_id), reverse=True)
    deduplicate(documents)
    return documents


def write_documents(documents: list[Document], path: Path) -> None:
    lines = [json.dumps(asdict(doc), ensure_ascii=False) for doc in documents]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_documents(path: Path) -> list[Document]:
    return [Document(**json.loads(line)) for line in path.read_text("utf-8").splitlines()]


# --- Djinni pages -----------------------------------------------------------------------


def _postings(folder: Path) -> list[Document]:
    if not (folder / "sources.json").exists():
        return []
    documents = []
    for source in json.loads((folder / "sources.json").read_text("utf-8")):
        raw = (folder / source["file"]).read_bytes()
        captured = date.fromisoformat(source["captured_at"][:10])
        snapshot = parse_snapshot(raw.decode("utf-8"), captured)
        page = scrubbed(snapshot.page)
        text = posting_markdown(page, source["date"])
        undated = re.sub(r"(?m)^Posted: .*\n", "", text)  # a repost differs only in its date
        documents.append(
            Document(
                doc_id=source["doc_id"],
                kind="posting",
                format="html",
                title=page.title,
                source=source["url"],
                date=source["date"],
                language=language(page.description),
                company=page.company or None,
                text=text,
                raw_file=f"{folder.name}/{source['file']}",
                raw_sha256=hashlib.sha256(raw).hexdigest(),
                sha256=hashlib.sha256(undated.encode("utf-8")).hexdigest(),
            )
        )
    return documents


def posting_markdown(page: JobPage, posted: str | None) -> str:
    """A posting as Markdown: title, company, salary and date, then its sections."""
    lines = [f"# {page.title}", ""]
    lines += [f"Company: {page.company}"] if page.company else []
    lines += [f"Salary: {page.salary}"] if page.salary else []
    lines += [f"Posted: {posted}"] if posted else []
    lines += ["", "## Description", "", *description_markdown(page.description.splitlines())]
    if page.skills:
        lines += ["", "## Skills", "", *(f"- {skill}" for skill in page.skills)]
    if page.languages:
        lines += ["", "## Languages", "", *(f"- {line}" for line in page.languages)]
    if page.facts:
        lines += ["", "## Details", "", *(f"- {fact}" for fact in page.facts)]
    return clean_text("\n".join(lines))


def description_markdown(lines: list[str]) -> list[str]:
    """The description's lines with its own section titles as headings and paragraphs apart;
    list items stay together."""
    out: list[str] = []
    for line, following in itertools.zip_longest(lines, lines[1:]):
        if _section_title(line, following):
            out += ["", f"### {line.rstrip(':').strip()}", ""]
        elif line.startswith("- "):
            out.append(line)
        else:
            out += ["", line, ""] if out and out[-1].startswith("- ") else [line, ""]
    return out


def _section_title(line: str, following: str | None) -> bool:
    if line.startswith("- "):
        return False
    if len(line) <= 80 and line.endswith(":"):
        return True
    opens_list = following is not None and following.startswith("- ")
    return opens_list and len(line) <= 50 and not re.search(r"[.!?,;…]$", line)


# --- official documents -----------------------------------------------------------------


def _official(folder: Path) -> list[Document]:
    if not (folder / "sources.json").exists():
        return []
    documents = []
    for source in json.loads((folder / "sources.json").read_text("utf-8")):
        path = folder / source["file"]
        text = pdf_markdown(path) if path.suffix == ".pdf" else docx_markdown(path)
        text = clean_text(f"# {source['title']}\n\n{text}")
        documents.append(
            Document(
                doc_id=path.stem,
                kind="official",
                format=path.suffix.lstrip("."),
                title=source["title"],
                source=source["url"],
                date=source.get("version_date"),
                language=language(text),
                company=source.get("publisher"),
                text=text,
                raw_file=f"{folder.name}/{source['file']}",
                raw_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                superseded_by=source.get("superseded_by"),
            )
        )
    return documents


@dataclass
class _Line:
    page: int
    block: int
    top: float  # the box, as fractions of the page's height and width
    bottom: float
    left: float
    right: float
    size: float
    bold: bool
    text: str


@dataclass
class _Unit:
    """A PDF page's text block or table: its box, as fractions of the page, and the Markdown
    it becomes."""

    page: int
    top: float
    bottom: float
    left: float
    right: float
    texts: list[str]


# White space that separates rows of a page, and columns of a row, as fractions of the page.
ROW_GAP, COLUMN_GAP = 0.012, 0.02


def pdf_markdown(path: Path) -> str:
    """A PDF's text as Markdown; see the module's docstring."""
    pdf = pymupdf.open(path)
    lines: list[_Line] = []
    tables: list[_Unit] = []
    for page in pdf:
        width, height = page.rect.width, page.rect.height
        found = page.find_tables().tables
        for table in found:
            x0, y0, x1, y1 = table.bbox
            markdown = table.to_markdown(clean=False).strip()
            tables.append(
                _Unit(page.number, y0 / height, y1 / height, x0 / width, x1 / width, [markdown])
            )
        boxes = [pymupdf.Rect(table.bbox) for table in found]
        for number, block in enumerate(page.get_text("dict")["blocks"]):
            if block["type"] != 0 or any(pymupdf.Rect(block["bbox"]).intersects(b) for b in boxes):
                continue
            for line in block["lines"]:
                spans = [span for span in line["spans"] if span["text"].strip()]
                if not spans:
                    continue
                text = "".join(span["text"] for span in line["spans"]).strip()
                x0, y0, x1, y1 = line["bbox"]
                size = round(max(span["size"] for span in spans), 1)
                bold = all(span["flags"] & 16 or "Bold" in span["font"] for span in spans)
                lines.append(
                    _Line(page.number, number, y0 / height, y1 / height, x0 / width, x1 / width,
                          size, bold, text)
                )  # fmt: skip
    lines = _without_running_lines(lines, pdf.page_count)
    return _pdf_blocks(lines, tables)


def _without_running_lines(lines: list[_Line], pages: int) -> list[_Line]:
    """Without page numbers, and without lines at a page's top or bottom that repeat on at
    least half the pages: running headers and footers."""
    shape = lambda line: re.sub(r"\d+", "#", line.text.lower())  # noqa: E731
    edge = [line for line in lines if line.top < 0.08 or line.bottom > 0.92]
    counts = Counter(
        shape(line) for line in {(line.page, shape(line)): line for line in edge}.values()
    )
    running = {text for text, count in counts.items() if pages >= 3 and count >= pages / 2}
    return [
        line
        for line in lines
        if not _PAGE_NUMBER.match(line.text)
        and not ((line.top < 0.08 or line.bottom > 0.92) and shape(line) in running)
    ]


def _pdf_blocks(lines: list[_Line], tables: list[_Unit]) -> str:
    """Lines into headings and paragraphs, one PyMuPDF text block at a time, and the blocks
    and tables of each page in reading order. Headings that follow each other at one level
    are one title wrapped over lines."""
    sizes: Counter[float] = Counter()
    for line in lines:
        sizes[line.size] += len(line.text)
    body = sizes.most_common(1)[0][0] if sizes else 0
    larger = sorted({line.size for line in lines if line.size >= body + 1.5}, reverse=True)
    units = [*tables]
    for _, grouped in itertools.groupby(lines, key=lambda line: (line.page, line.block)):
        block = list(grouped)
        units.append(
            _Unit(block[0].page, min(line.top for line in block),
                  max(line.bottom for line in block), min(line.left for line in block),
                  max(line.right for line in block), _block_markdown(block, larger))
        )  # fmt: skip
    ordered: list[_Unit] = []
    for _, page in itertools.groupby(sorted(units, key=lambda unit: unit.page), lambda u: u.page):
        ordered += _reading_order(list(page))
    return "\n\n".join(_merge_wrapped_headings([text for unit in ordered for text in unit.texts]))


def _block_markdown(block: list[_Line], larger: list[float]) -> list[str]:
    """A text block as a heading or as paragraphs. It is a heading when its font is larger
    than the body's, or when it is short and bold throughout (a bold word inside a paragraph
    is not); a law's "Стаття 5." line is one whatever its font."""
    out = []
    if law := _heading_level(block[0].text, 0):  # the article's text may follow in the block
        out.append(f"{'#' * law} {block[0].text}")
        block = block[1:]
        if not block:
            return out
    text = _join(block)
    size = max(line.size for line in block)
    level = larger.index(size) + 2 if size in larger and len(text) <= 200 else 0
    bold = all(line.bold for line in block) and len(text) <= 150
    if not level and bold and not text.endswith((".", ",", ";", ":")):
        level = 3
    if level:
        return [*out, f"{'#' * min(level, 4)} {text}"]
    paragraph: list[_Line] = []
    for line in block:  # a bullet starts a new paragraph
        if paragraph and _BULLET.match(line.text):
            out.append(_join(paragraph))
            paragraph = []
        paragraph.append(line)
    return [*out, _join(paragraph)]


def _reading_order(units: list[_Unit]) -> list[_Unit]:
    """A page's blocks in reading order, by recursive XY-cut. The page is cut at bands of
    white space across it into rows, read top to bottom, and a row into columns, read left to
    right. Rows one under another that keep a gutter in the same place are one run of
    columns, read a column at a time: a flowchart's two branches, or a two-column page."""
    if len(units) < 2:
        return units
    rows = _join_columns(_cut(units, rows=True))
    if len(rows) > 1:
        return [unit for row in rows for unit in _reading_order(row)]
    columns = _cut(units, rows=False)
    if len(columns) > 1:
        return [unit for column in columns for unit in _reading_order(column)]
    return sorted(units, key=lambda unit: (unit.top, unit.left))


def _cut(units: list[_Unit], *, rows: bool) -> list[list[_Unit]]:
    """Units split at every band of white space at least ROW_GAP (COLUMN_GAP) wide."""
    start = (lambda u: u.top) if rows else (lambda u: u.left)
    end = (lambda u: u.bottom) if rows else (lambda u: u.right)
    gap = ROW_GAP if rows else COLUMN_GAP
    groups: list[list[_Unit]] = []
    reach = 0.0
    for unit in sorted(units, key=start):
        if groups and start(unit) - reach < gap:
            groups[-1].append(unit)
            reach = max(reach, end(unit))
        else:
            groups.append([unit])
            reach = end(unit)
    return groups


def _join_columns(rows: list[list[_Unit]]) -> list[list[_Unit]]:
    """Consecutive rows that are both split into columns, with a gutter in common, as one."""
    joined: list[list[_Unit]] = []
    for row in rows:
        if (
            joined
            and len(_cut(row, rows=False)) > 1
            and len(_cut(joined[-1], rows=False)) > 1
            and len(_cut(joined[-1] + row, rows=False)) > 1
        ):
            joined[-1] = joined[-1] + row
        else:
            joined.append(row)
    return joined


def _merge_wrapped_headings(blocks: list[str]) -> list[str]:
    merged: list[str] = []
    for block in blocks:
        level = len(block) - len(block.lstrip("#"))
        previous = merged[-1] if merged else ""
        before = len(previous) - len(previous.lstrip("#"))
        plain = level and not _LAW_HEADING.match(block.lstrip("# "))
        if plain and before == level and not _LAW_HEADING.match(previous.lstrip("# ")):
            merged[-1] = f"{previous} {block.lstrip('# ')}"
        else:
            merged.append(block)
    return merged


def _heading_level(text: str, by_size: int | bool) -> int:
    if match := _LAW_HEADING.match(text):
        return 2 if match.group("two") else 3
    return int(by_size) + 1 if by_size else 0  # the largest size is "##": "#" is the title


def _join(lines: list[_Line]) -> str:
    """A paragraph's lines as one, words broken with a hyphen joined again. A bulleted
    paragraph becomes a list item; numbered ones ("1)", "а)") keep their numbers, which laws
    cite."""
    text = ""
    for line in lines:
        if text.endswith("-") and line.text[:1].islower():
            text = text[:-1] + line.text
        else:
            text = f"{text} {line.text}" if text else line.text
    match = _BULLET.match(text)
    if match and not re.match(r"\d|[а-яіїєa-z]\)", text):
        return f"- {text[match.end() :]}"
    return text


def docx_markdown(path: Path) -> str:
    """A DOCX's text as Markdown; see the module's docstring."""
    document = open_docx(str(path))
    out = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:tbl"):
            out.append(_table_markdown(Table(child, document)))
            continue
        if child.tag != qn("w:p"):
            continue
        paragraph = Paragraph(child, document)
        text = " ".join(paragraph.text.split())
        if not text:
            continue
        style = (paragraph.style.name if paragraph.style is not None else "").lower()
        level = _heading_level(text, 0)
        if not level and (match := re.match(r"(?:heading|заголовок)\s*(\d)", style)):
            level = int(match.group(1)) + 1
        if not level and style == "title":
            level = 2
        runs = [run for run in paragraph.runs if run.text.strip()]
        if not level and runs and all(run.bold for run in runs) and len(text) <= 120:
            level = 3
        numbered = child.pPr is not None and child.pPr.numPr is not None
        if level:
            out.append(f"{'#' * min(level, 4)} {text}")
            out = _merge_wrapped_headings(out)
        elif numbered or "list" in style or _BULLET.match(text):
            out.append(
                f"- {_BULLET.sub('', text)}" if not re.match(r"^\d{1,2}[.)]", text) else text
            )
        else:
            out.append(text)
    return "\n\n".join(out)


def _table_markdown(table: Table) -> str:
    rows = []
    for row in table.rows:
        cells = []
        for cell in row.cells:  # a merged cell repeats in every column it spans
            text = " ".join(cell.text.split()).replace("|", "/")
            if not cells or cells[-1] != text:
                cells.append(text)
        rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    return "\n".join(lines + ["| " + " | ".join(row) + " |" for row in rows[1:]])


# --- cleaning and deduplication -----------------------------------------------------------


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(_INVISIBLE)
    lines = [_SPACES.sub(" ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def language(text: str) -> str:
    letters = [char for char in text if char.isalpha()]
    cyrillic = sum("Ѐ" <= char <= "ӿ" for char in letters) / max(1, len(letters))
    if cyrillic < 0.2:
        return "en"
    russian = sum(char in "ыэъёЫЭЪЁ" for char in text) > sum(char in "іїєґІЇЄҐ" for char in text)
    return "mixed" if cyrillic < 0.7 else "ru" if russian else "uk"


def deduplicate(documents: list[Document]) -> None:
    """Mark duplicates and superseded versions in place; `documents` are newest first."""
    first: dict[str, Document] = {}
    for doc in documents:
        if doc.sha256 in first:
            doc.status, doc.duplicate_of = "duplicate", first[doc.sha256].doc_id
        else:
            first[doc.sha256] = doc
    kept = [doc for doc in documents if doc.status == "kept"]
    shingles = {doc.doc_id: _shingles(doc.text) for doc in kept}
    for newer, older in itertools.combinations(kept, 2):  # newest first, so `newer` is newer
        if older.superseded_by or newer.kind != older.kind or newer.company != older.company:
            continue
        a, b = shingles[newer.doc_id], shingles[older.doc_id]
        if len(a & b) / max(1, len(a | b)) >= NEAR_DUPLICATE:
            older.superseded_by = newer.superseded_by or newer.doc_id


def _shingles(text: str, size: int = 5) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    return {" ".join(words[i : i + size]) for i in range(max(1, len(words) - size + 1))}

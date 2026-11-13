"""Chunking: documents into the passages the index holds. README.md, "Chunking", says why.

`structural` (what the RAG uses) cuts along the document's own structure: a posting's sections
(the description's parts, skills, languages, Djinni's details) and a law's articles. A section
of up to MAX_TOKENS is one chunk. A longer one is cut between its paragraphs, list items or a
law's numbered parts, never inside one, into pieces of about TARGET_TOKENS. Consecutive
sections under MIN_TOKENS (a posting's skills, languages and details) are joined. Each chunk
starts with a header naming the document and the section, "Senior Python Developer — Luxoft,
2019-07-16 › Requirements", so that look-alike passages from different postings stay apart.

`fixed` (the baseline) cuts the same Markdown every FIXED_TOKENS tokens with FIXED_OVERLAP
tokens of overlap, whatever the structure; its header names only the document.

Either way a chunk can carry a context that a model wrote (rag/context.py): it is searched
with the chunk and shown with it, but a chunk's relevance is judged on its own text.
"""

import re
from dataclasses import asdict, dataclass
from functools import cache

import tiktoken

from rag.ingest import Document

MIN_TOKENS, TARGET_TOKENS, MAX_TOKENS = 60, 250, 400
FIXED_TOKENS, FIXED_OVERLAP = 250, 50
_HEADING = re.compile(r"^(#{1,4}) (.+)$")


@dataclass
class Chunk:
    chunk_id: str  # "<doc_id>#<n>"
    doc_id: str
    strategy: str  # "structural" or "fixed"
    kind: str  # "posting" or "official"
    title: str
    section: str  # "Description › Requirements", "Розділ II › Стаття 5. ..."
    header: str  # the document and the section, in one line
    text: str
    tokens: int  # of header and text
    date: str | None
    year: int | None
    language: str
    company: str | None
    source: str
    current: bool  # False when a newer version of the document is in the corpus
    doc_sha256: str
    context: str = ""  # where the chunk sits and what it is about, by a model (rag/context.py)

    @property
    def indexed(self) -> str:
        """What is embedded, searched and shown to the answer model: the header, the
        context if there is one, then the text."""
        context = f"\n{self.context}" if self.context else ""
        return f"{self.header}{context}\n\n{self.text}"

    @property
    def original(self) -> str:
        """The header and the text, without the model's context: what the document says."""
        return f"{self.header}\n\n{self.text}"


def count_tokens(text: str) -> int:
    return len(_encoding().encode(text))


def first_tokens(text: str, n: int) -> str:
    """The text cut after its first `n` tokens."""
    return _encoding().decode(_encoding().encode(text)[:n])


@cache
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("o200k_base")


def structural(doc: Document) -> list[Chunk]:
    pieces: list[tuple[str, str]] = []  # (section, text)
    pending: list[tuple[str, str]] = []  # short sections waiting to be joined

    def flush_pending() -> None:
        if pending:
            names = " + ".join(dict.fromkeys(section for section, _ in pending))
            pieces.append((names, "\n\n".join(text for _, text in pending)))
            pending.clear()

    for section, blocks in _sections(doc.text):
        text = "\n\n".join(blocks)
        size = count_tokens(text)
        if size < MIN_TOKENS:
            pending.append((section, text))
            if count_tokens("\n\n".join(t for _, t in pending)) >= TARGET_TOKENS:
                flush_pending()
            continue
        waiting = count_tokens("\n\n".join(t for _, t in pending)) if pending else 0
        if pending and waiting + size <= MAX_TOKENS:  # short sections join the next one
            pending.append((section, text))
            flush_pending()
            continue
        flush_pending()
        if size <= MAX_TOKENS:
            pieces.append((section, text))
        else:
            pieces += [(section, part) for part in _pack(blocks)]
    flush_pending()
    return [_chunk(doc, "structural", n, section, text) for n, (section, text) in enumerate(pieces)]


def fixed(doc: Document) -> list[Chunk]:
    tokens = _encoding().encode(doc.text)
    step = FIXED_TOKENS - FIXED_OVERLAP
    starts = range(0, max(1, len(tokens) - FIXED_OVERLAP), step)
    texts = [_encoding().decode(tokens[start : start + FIXED_TOKENS]).strip() for start in starts]
    return [_chunk(doc, "fixed", n, "", text) for n, text in enumerate(texts) if text]


def _sections(markdown: str) -> list[tuple[str, list[str]]]:
    """The document's sections with their blocks (paragraphs, lists, tables), in order. A
    section is named by its headings below the document's title: "Description › Requirements"."""
    path: list[tuple[int, str]] = []
    sections: list[tuple[str, list[str]]] = []
    blocks: list[str] = []

    def close() -> None:
        if blocks:
            sections.append((" › ".join(name for _, name in path) or "Intro", blocks.copy()))
            blocks.clear()

    for block in _blocks(markdown):
        match = _HEADING.match(block)
        if not match:
            blocks.append(block)
            continue
        close()
        level = len(match.group(1))
        if level == 1:
            continue  # the title: it is in every chunk's header
        path = [(lvl, name) for lvl, name in path if lvl < level] + [(level, match.group(2))]
    close()
    return sections


def _blocks(markdown: str) -> list[str]:
    """Paragraphs, list items, table rows grouped as one table, and headings."""
    blocks: list[str] = []
    for paragraph in re.split(r"\n\s*\n", markdown.strip()):
        lines = paragraph.splitlines()
        if all(line.startswith("|") for line in lines):
            blocks.append(paragraph)
        else:
            blocks += [line for line in lines if line.strip()]
    return blocks


def _pack(blocks: list[str]) -> list[str]:
    """Blocks into pieces of about TARGET_TOKENS, cut only between blocks; a block over
    MAX_TOKENS is cut between its sentences, or a table between its rows."""
    pieces, current, size = [], [], 0
    for block in blocks:
        for part in _split(block) if count_tokens(block) > MAX_TOKENS else [block]:
            part_size = count_tokens(part)
            if current and size + part_size > TARGET_TOKENS:
                pieces.append("\n\n".join(current))
                current, size = [], 0
            current.append(part)
            size += part_size
    if current:
        pieces.append("\n\n".join(current))
    return pieces


def _split(block: str) -> list[str]:
    """A block too long for one chunk: a table by rows, each part with the table's header; any
    other block by sentences."""
    if not block.startswith("|"):
        return _sentences(block)
    head, rows = block.splitlines()[:2], block.splitlines()[2:]
    parts, current = [], []
    for row in rows:
        if current and count_tokens("\n".join([*head, *current, row])) > TARGET_TOKENS:
            parts.append("\n".join([*head, *current]))
            current = []
        current.append(row)
    return [*parts, "\n".join([*head, *current])] if current else parts


def _sentences(text: str) -> list[str]:
    """A long block cut after its sentences into parts of up to TARGET_TOKENS; a sentence
    longer than that, between its words."""
    parts, current = [], ""
    pieces = re.split(r"(?<=[.;:!?])\s+", text)
    words = [
        part
        for piece in pieces
        for part in (_words(piece) if count_tokens(piece) > MAX_TOKENS else [piece])
    ]
    for sentence in words:
        if current and count_tokens(f"{current} {sentence}") > TARGET_TOKENS:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    return [*parts, current] if current else parts


def _words(text: str) -> list[str]:
    parts, current = [], []
    for word in text.split():
        if current and count_tokens(" ".join([*current, word])) > TARGET_TOKENS:
            parts.append(" ".join(current))
            current = []
        current.append(word)
    return [*parts, " ".join(current)] if current else parts


def _chunk(doc: Document, strategy: str, n: int, section: str, text: str) -> Chunk:
    if strategy == "structural" and (point := re.match(r"(\d{1,2})[.)]\s", text)):
        section = (
            f"{section} › п. {point.group(1)}" if section != "Intro" else f"п. {point.group(1)}"
        )
    where = ", ".join(
        part for part in (doc.company if doc.kind == "posting" else None, doc.date) if part
    )
    header = f"{doc.title} — {where}" if where else doc.title
    if section:
        header += f" › {section}"
    return Chunk(
        chunk_id=f"{doc.doc_id}#{n}",
        doc_id=doc.doc_id,
        strategy=strategy,
        kind=doc.kind,
        title=doc.title,
        section=section,
        header=header,
        text=text,
        tokens=count_tokens(f"{header}\n\n{text}"),
        date=doc.date,
        year=int(doc.date[:4]) if doc.date else None,
        language=doc.language,
        company=doc.company,
        source=doc.source,
        current=doc.current,
        doc_sha256=doc.sha256,
    )


def as_dict(chunk: Chunk) -> dict:
    return asdict(chunk)

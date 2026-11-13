"""The RAG offline: no model is called; embeddings, the reranker and the LLM are fakes."""

import hashlib
import threading
from collections import defaultdict
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pymupdf
import pytest
from docx import Document as new_docx

from rag.answer import (
    REFUSALS,
    Answer,
    Passage,
    Rag,
    cited_passages,
    question_language,
    within_budget,
)
from rag.chunking import MAX_TOKENS, count_tokens, fixed, structural
from rag.config import load
from rag.context import Contextualizer, cleaned
from rag.evaluate import _kappa, answer_metrics, answer_run, failures, relevant, score_answer
from rag.ingest import (
    Document,
    _Line,
    _pdf_blocks,
    _reading_order,
    _Unit,
    deduplicate,
    description_markdown,
    docx_markdown,
    pdf_markdown,
)
from rag.llm import OpenRouter
from rag.prompts import load_prompt
from rag.search import Filters, Hit, Retriever, tokens


def doc(doc_id="djinni-1", text="# Python Developer\n\nCompany: Acme\n", **fields) -> Document:
    values = dict(
        doc_id=doc_id, kind="posting", format="html", title="Python Developer", source="https://x",
        date="2026-01-01", language="en", company="Acme", text=text, raw_file="djinni/x.html",
        raw_sha256="0", sha256=hashlib.sha256(text.encode()).hexdigest(),
    )  # fmt: skip
    return Document(**(values | fields))


# --- ingestion --------------------------------------------------------------------------


def test_a_descriptions_own_section_titles_become_headings():
    lines = ["We build things.", "Requirements:", "- Python", "- SQL", "Nice to have", "- Go"]
    assert description_markdown(lines) == [
        "We build things.", "", "", "### Requirements", "", "- Python", "- SQL",
        "", "### Nice to have", "", "- Go",
    ]  # fmt: skip


def test_a_repost_is_a_duplicate_and_a_changed_one_supersedes_the_older():
    body = " ".join(f"word{i}" for i in range(200))
    newest = doc("djinni-3", f"# T\n\n{body} changed", date="2026-03-01")
    repost = doc("djinni-2", f"# T\n\n{body} changed", date="2026-02-01")
    older = doc("djinni-1", f"# T\n\n{body}", date="2026-01-01")
    other = doc("djinni-9", "# Another job\n\nnothing alike", date="2025-01-01")
    documents = [newest, repost, older, other]
    deduplicate(documents)
    assert (repost.status, repost.duplicate_of) == ("duplicate", "djinni-3")
    assert (older.status, older.superseded_by) == ("kept", "djinni-3")
    assert newest.current and other.current


def test_docx_keeps_headings_lists_and_tables(tmp_path):
    document = new_docx()
    document.add_heading("Розділ I. Загальні положення", level=1)
    document.add_paragraph("Стаття 1. Визначення термінів")
    document.add_paragraph("перший пункт", style="List Bullet")
    table = document.add_table(rows=2, cols=2)
    for row, cells in zip(table.rows, [("Група", "Ставка"), ("3", "5%")], strict=True):
        for cell, value in zip(row.cells, cells, strict=True):
            cell.text = value
    document.save(tmp_path / "law.docx")
    markdown = docx_markdown(tmp_path / "law.docx")
    assert "## Розділ I. Загальні положення" in markdown
    assert "### Стаття 1. Визначення термінів" in markdown
    assert "- перший пункт" in markdown
    assert "| Група | Ставка |\n|---|---|\n| 3 | 5% |" in markdown


def test_pdf_drops_running_headers_and_page_numbers_and_joins_hyphenated_words(tmp_path):
    # Latin text: PyMuPDF's built-in font has no Cyrillic. Real PDFs embed their fonts.
    pdf = pymupdf.open()
    for number in range(1, 4):
        page = pdf.new_page()
        page.insert_text((72, 30), "Official Gazette of Ukraine", fontsize=9)
        page.insert_text((72, 100), f"Part {number}. The title", fontsize=15)
        page.insert_text((72, 130), "A text about the develop-", fontsize=11)
        page.insert_text((72, 145), "ment of the digital economy.", fontsize=11)
        page.insert_text((300, 820), str(number), fontsize=9)
    pdf.save(tmp_path / "law.pdf")
    markdown = pdf_markdown(tmp_path / "law.pdf")
    assert "Official Gazette" not in markdown
    assert "## Part 2. The title" in markdown
    assert "A text about the development of the digital economy." in markdown
    assert "\n3\n" not in f"\n{markdown}\n"


def test_pdf_blocks_side_by_side_are_read_a_column_at_a_time():
    # A flowchart's boxes, as PyMuPDF gives them: one text block each.
    def line(block, text, top, left):
        return _Line(0, block, top, top + 0.02, left, left + 0.3, 11.0, False, text)

    lines = [
        line(0, "How to reconcile the lists.", 0.05, 0.1),
        line(1, "Inside the area:", 0.30, 0.1),
        line(2, "Outside the area:", 0.30, 0.6),
        line(3, "come in person.", 0.40, 0.1),
        line(4, "send two copies.", 0.40, 0.6),
    ]
    assert _pdf_blocks(lines, []).split("\n\n") == [
        "How to reconcile the lists.", "Inside the area:", "come in person.",
        "Outside the area:", "send two copies.",
    ]  # fmt: skip


def test_reading_order_takes_rows_top_down_and_a_run_of_columns_a_column_at_a_time():
    def unit(text, top, bottom, left, right):
        return _Unit(0, top, bottom, left, right, [text])

    page = [
        unit("note", 0.80, 0.85, 0.10, 0.90),
        unit("right 2", 0.50, 0.58, 0.52, 0.92),
        unit("left 1", 0.40, 0.45, 0.10, 0.45),
        unit("title", 0.02, 0.06, 0.20, 0.80),
        unit("left 2", 0.50, 0.58, 0.05, 0.48),
        unit("right 1", 0.40, 0.45, 0.55, 0.90),
    ]
    read = [u.texts[0] for u in _reading_order(page)]
    assert read == ["title", "left 1", "left 2", "right 1", "right 2", "note"]
    one_column = [unit(str(n), n / 10, n / 10 + 0.05, 0.1, 0.9) for n in (3, 1, 2)]
    assert [u.texts[0] for u in _reading_order(one_column)] == ["1", "2", "3"]


# --- chunking ---------------------------------------------------------------------------


POSTING = """# Senior Python Developer

Company: Acme
Posted: 2026-01-01

## Description

### Requirements

{requirements}

### We offer

- Remote work

## Languages

- English: B2

## Details

- Тільки віддалено
"""


def test_structural_chunks_follow_sections_and_join_short_ones():
    requirements = "\n".join(
        f"- requirement number {i} with a few more words in it" for i in range(12)
    )
    chunks = structural(doc(text=POSTING.format(requirements=requirements)))
    sections = [chunk.section for chunk in chunks]
    assert "Description › Requirements" in sections[0] or "Description › Requirements" in sections
    assert any("Languages" in s and "Details" in s for s in sections)  # short ones together
    assert all(chunk.header.startswith("Python Developer — Acme, 2026-01-01") for chunk in chunks)
    assert all(chunk.tokens <= MAX_TOKENS + 40 for chunk in chunks)


def test_a_long_section_is_cut_between_list_items_never_inside_one():
    item = "- " + "word " * 40
    chunks = structural(doc(text=POSTING.format(requirements="\n".join([item.strip()] * 30))))
    pieces = [c for c in chunks if c.section == "Description › Requirements"]
    assert len(pieces) > 1
    assert all(line.startswith("- ") for c in pieces for line in c.text.splitlines() if line)


def test_fixed_chunks_overlap_and_ignore_structure():
    text = "# T\n\n" + " ".join(f"w{i}" for i in range(2000))
    chunks = fixed(doc(text=text))
    assert len(chunks) > 3 and all(count_tokens(c.text) <= 250 for c in chunks)
    assert chunks[0].text.split()[-1] in chunks[1].text  # overlap


# --- search -----------------------------------------------------------------------------


class FakeEmbeddings:
    """A word-hashing embedding: texts sharing words point the same way."""

    def __call__(self, texts):
        vectors = np.zeros((len(texts), 64), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in tokens(text):
                vectors[row, int(hashlib.md5(word.encode()).hexdigest(), 16) % 64] += 1
        return vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9)


class FakeReranker:
    def __call__(self, query, texts):
        wanted = set(tokens(query))
        return [len(wanted & set(tokens(text))) / max(1, len(wanted)) for text in texts]


def corpus():
    texts = {
        "djinni-1": "Remote work, relocation to Portugal for a Python developer",
        "djinni-2": "Office in Kyiv, Django and PostgreSQL",
        "djinni-3": "Remote work in Poland, Go developer",
    }
    chunks = []
    for doc_id, text in texts.items():
        chunks += structural(doc(doc_id, f"# Job {doc_id}\n\n## Description\n\n{text}\n"))
    chunks[2] = replace(chunks[2], current=False)  # djinni-3 is superseded
    return Retriever(chunks, FakeEmbeddings(), FakeReranker())


@pytest.mark.parametrize("mode", ["bm25", "vector", "hybrid", "rerank"])
def test_every_mode_finds_the_matching_posting(mode):
    hits = corpus().search("relocation to Portugal", mode=mode, k=2)
    assert hits[0].chunk.doc_id == "djinni-1"


def test_filters_leave_out_superseded_versions_and_other_kinds():
    retriever = corpus()
    found = {h.chunk.doc_id for h in retriever.search("remote work", mode="hybrid", k=5)}
    assert "djinni-3" not in found
    every = Filters(current_only=False)
    assert "djinni-3" in {
        h.chunk.doc_id
        for h in retriever.search("remote work Poland", mode="hybrid", k=5, filters=every)
    }
    assert (
        retriever.search("remote work", mode="vector", k=5, filters=Filters(kind="official")) == []
    )


def test_ukrainian_endings_are_cut():
    assert tokens("розробника") == tokens("розробник") == tokens("розробники")


# --- answers ----------------------------------------------------------------------------


class FakeClient:
    def __init__(self, reply):
        self.reply, self.calls, self.user = reply, 0, None
        self.usage = defaultdict(lambda: None)
        self._lock = threading.Lock()

    def chat(self, model, system, user, **kwargs):
        with self._lock:
            self.calls += 1
            self.user = user
        return self.reply


def test_the_context_keeps_the_best_passages_that_fit_the_budget():
    hits = [Hit(c, 1.0) for c in corpus().chunks]
    one = count_tokens(f"[1] {hits[0].chunk.indexed}")
    assert len(within_budget(hits, one + 5)) == 1
    assert len(within_budget(hits, 10_000)) == 3
    assert within_budget(hits, 60)[0].chunk.text  # the best one, cut to fit


def test_citations_map_back_to_passages_and_a_bare_refusal_is_an_abstention():
    passages = [Passage(n, c, 1.0) for n, c in enumerate(corpus().chunks, 1)]
    assert [p.number for p in cited_passages("Remote [1]. Kyiv office [2, 3].", passages)] == [
        1,
        2,
        3,
    ]
    config = load()
    rag = Rag(config, corpus(), FakeClient("The documents don't say."))
    answer = rag.ask("Is there relocation to Portugal?")
    assert answer.abstained and answer.reason == "model abstained"


def test_nothing_relevant_means_no_model_call():
    config = load()
    client = FakeClient("should not be asked")
    answer = Rag(config, corpus(), client).ask("квантові обчислення на Марсі")
    assert answer.text == REFUSALS["uk"] and answer.abstained and client.calls == 0


def test_the_answer_prompt_is_told_the_language_and_the_refusal():
    client = FakeClient("Relocation to Portugal [1].")
    rag = Rag(load(), corpus(), client)
    rag.prompt = load_prompt("answer", "v2")
    rag.ask("Is there relocation to Portugal?")
    assert "Answer in English" in client.user and "The documents don't say." in client.user
    assert client.user.count("Question: Is there relocation to Portugal?") == 2


def test_question_language():
    assert (question_language("Чи є віддалена робота?"), question_language("Is it remote?")) == (
        "uk",
        "en",
    )


# --- scoring ----------------------------------------------------------------------------


def test_scoring_checks_sources_facts_and_abstention():
    chunk = corpus().chunks[0]
    answer = Answer(
        "q",
        "Relocation to Portugal [1].",
        False,
        "answered",
        [Passage(1, chunk, 0.9)],
        [Passage(1, chunk, 0.9)],
    )
    item = {"id": "q", "type": "answerable", "question": "q", "expected": "Portugal",
            "sources": ["djinni-1"], "key_facts": [["portugal"], ["lisbon"]]}  # fmt: skip
    scored = score_answer(item, answer)
    assert (scored.source_ok, scored.key_facts, scored.abstention_ok) == (True, 0.5, True)
    refusal = Answer("q", "The documents don't say.", True, "model abstained", [])
    unanswerable = score_answer({**item, "type": "unanswerable", "sources": []}, refusal)
    assert (unanswerable.abstention_ok, unanswerable.source_ok) == (True, None)


def test_a_chunk_is_relevant_when_it_holds_the_quote_from_the_right_document():
    chunk = corpus().chunks[0]
    assert relevant(chunk, [{"doc_id": "djinni-1", "quote": "relocation to  Portugal"}])
    assert not relevant(chunk, [{"doc_id": "djinni-2", "quote": "relocation to Portugal"}])


def test_relevance_is_judged_on_the_chunks_own_text_not_on_its_context():
    kyiv = replace(corpus().chunks[1], context="en: about relocation to Portugal")
    assert "relocation to Portugal" in kyiv.indexed
    assert not relevant(kyiv, [{"doc_id": "djinni-2", "quote": "relocation to Portugal"}])


class FakeJudge:
    def verdict(self, question, expected, answer):
        if "broken" in question:
            raise ValueError("the reply was cut short")
        return {"verdict": "correct", "reason": "same facts"}

    def faithfulness(self, answer):
        return 1.0, []


def test_every_answer_is_judged_and_a_judge_failure_leaves_one_unjudged():
    rag = Rag(load(), corpus(), FakeClient("Relocation to Portugal [1]."))
    items = [
        {"id": f"q{n}", "type": "answerable", "question": question, "expected": "Portugal",
         "sources": ["djinni-1"]}
        for n, question in enumerate(["relocation to Portugal?", "relocation to Portugal, broken?"])
    ]  # fmt: skip
    scored = answer_run(rag, FakeJudge(), items)
    assert [s.verdict for s in scored] == ["correct", None]
    assert "judge failed" in scored[1].judge_reason
    assert answer_metrics(scored, rag)["judged"] == 1


def test_kappa_and_thresholds():
    assert _kappa(["correct", "incorrect"] * 5, ["correct", "incorrect"] * 5) == 1.0
    assert failures(
        {"abstention": 0.5, "faithfulness": 0.9}, {"abstention": 0.8, "faithfulness": 0.8}
    ) == ["abstention 0.5 < 0.8"]


# --- contexts and the client ---------------------------------------------------------------


def test_contexts_are_written_once_then_come_from_the_cache(tmp_path):
    client = FakeClient("Here it is:\nuk: Про переїзд до Португалії.\nen: About relocation.\n")
    posting = doc("djinni-1", "# Python Developer\n\n## Description\n\nRelocation to Portugal.\n")
    chunks = structural(posting)

    def contexts():
        return Contextualizer("m", load_prompt("context", "v1"), tmp_path / "c.jsonl", client)

    first = contexts()(chunks, {"djinni-1": posting})
    assert first[0].context == "uk: Про переїзд до Португалії.\nen: About relocation."
    assert first[0].context in first[0].indexed and first[0].context not in first[0].original
    assert contexts()(chunks, {"djinni-1": posting}) == first
    assert client.calls == len(chunks)


def test_a_context_reply_keeps_its_two_lines_on_one_line_each():
    assert cleaned("Sure!\nuk: Про   відпустку.\n\nen: About leave.") == (
        "uk: Про відпустку.\nen: About leave."
    )
    assert cleaned("No tags here.\nJust text.") == "No tags here. Just text."


def test_a_reply_whose_json_does_not_parse_is_asked_for_once_more(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only")
    replies = iter(['{"verdict": "corr', '{"verdict": "correct"}'])

    def create(**kwargs):
        message = SimpleNamespace(content=next(replies))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)

    client = OpenRouter()
    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    assert client.chat("m", "s", "u", schema={"type": "object"}) == {"verdict": "correct"}
    assert client.usage["m"].calls == 2


# --- the corpus's privacy steps -----------------------------------------------------------


def test_pages_lose_recruiters_photos_scripts_and_contacts():
    from rag.corpus import without_people

    html = """<html><head><script>track()</script>
    <script type="application/ld+json">{"title": "Python Developer"}</script></head><body>
    <a href="/r/42227-researcher/">Татьяна Бондарева</a><img src="photo.jpg">
    <div class="job-post__description">Write to hr@example.com or +380 67 123 4567.</div>
    <!-- recruiter: Olena --></body></html>"""
    clean = without_people(html)
    for gone in ("Бондарева", "photo.jpg", "track()", "hr@example.com", "123 4567", "Olena"):
        assert gone not in clean
    assert "application/ld+json" in clean and "[email]" in clean and "[phone]" in clean


def test_official_pdfs_are_redacted_and_lose_their_metadata(tmp_path, monkeypatch):
    import rag.corpus

    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 100), "Deputy Minister John SMITH", fontsize=11)
    page.insert_text((72, 130), "The letter's text stays.", fontsize=11)
    pdf.set_metadata({"author": "John Smith"})
    pdf.save(tmp_path / "letter.pdf")
    monkeypatch.setattr(rag.corpus, "REDACTIONS", {"letter.pdf": ["John SMITH"]})
    assert rag.corpus.redact_official(tmp_path) == []
    redacted = pymupdf.open(tmp_path / "letter.pdf")
    text = redacted[0].get_text()
    assert "SMITH" not in text and "The letter's text stays." in text
    assert not redacted.metadata.get("author")

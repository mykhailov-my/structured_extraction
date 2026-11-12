# Report: RAG with sources and evals (block 2)

The numbers come from `evals/results/` of the run committed with this report (`make rag`).
CI repeats the run on every push and fails below the thresholds in `rag.yaml`.

## Setup

- **Corpus:** 62 files: 50 Djinni postings (HTML) and 12 official documents (9 PDF, 3 DOCX).
  61 are indexed; 1 exact repost is dropped and 4 superseded versions are left out of search.
  This gives 437 chunks by structure, and 424 fixed-size chunks for the comparison. See
  README.md, "RAG (block 2)".
- **Search:**
  - BM25, with Ukrainian and English endings cut;
  - `baai/bge-m3` embeddings (OpenRouter) in Qdrant;
  - reciprocal rank fusion of the top 30 from each;
  - `BAAI/bge-reranker-v2-m3` (INT8 ONNX, CPU) over the top 20 fused.
  - The answer gets the best 6 that fit in 1,800 tokens.
- **Answers:** `mistralai/mistral-small-3.2-24b-instruct`, prompt `answer v1`, temperature 0.
  If the reranker scores even the best passage under 0.2, the answer is "not in the
  documents" without a model call.
- **Judge:** `anthropic/claude-haiku-5.5`, from another model family than the answers, prompts
  `judge v1` and `faithfulness v1`.
- **Test sets:**
  - 15 retrieval questions: 7 cross-language, 5 paraphrased, 3 that name the document;
  - 26 answer questions: 13 answerable, 7 traps (look-alikes, outdated versions), 6 with no
    answer in the corpus.

## Retrieval

15 questions, each with the passage that answers it given as a document and a quote. A
chunk counts when it is from that document and holds the quote, so both chunkings are scored
on the same questions. Seven questions are cross-language (a Ukrainian question about an
English posting, or the other way round), five are paraphrased, and three name their
document. [evals/results/retrieval.md](evals/results/retrieval.md)

| Chunking | Search | recall@1 | recall@3 | recall@5 | recall@10 | MRR |
|---|---|--:|--:|--:|--:|--:|
| structural | BM25 | 0.20 | 0.33 | 0.40 | 0.47 | 0.28 |
| structural | vectors | 0.33 | 0.67 | 0.73 | 0.80 | 0.51 |
| structural | hybrid (RRF) | 0.27 | 0.47 | 0.53 | 0.67 | 0.39 |
| structural | **hybrid + rerank** | **0.67** | **0.80** | **0.87** | **0.87** | **0.74** |
| fixed | BM25 | 0.20 | 0.33 | 0.33 | 0.53 | 0.28 |
| fixed | vectors | 0.47 | 0.60 | 0.73 | 0.80 | 0.56 |
| fixed | hybrid (RRF) | 0.20 | 0.53 | 0.60 | 0.73 | 0.38 |
| fixed | hybrid + rerank | 0.60 | 0.80 | 0.80 | 0.87 | 0.68 |

- **The reranker matters most:** MRR goes from 0.39 to 0.74 on the same candidates.
- **Fusion alone is worse than vectors alone.** BM25 can't match "переїзд до Португалії" to
  "relocation to Portugal", so for cross-language questions it adds noise to the fused list.
  Hybrid still earns its place under the reranker, since its pool of 20 holds what either
  list found. Paraphrased questions are found 5 of 5, cross-language 6 of 7, named 2 of 3.
- **Structure wins under the reranker, by one question.** It also keeps 97% of chunks within a
  sentence or list item, against 19% for fixed size (README.md, "Chunking").
- **Both misses come from one document,** Resolution 692's list of amendments (errors 1 and 2).

## Answers

26 questions: 13 answerable, 7 traps, 6 with no answer in the corpus.
[evals/results/answers.md](evals/results/answers.md) has every answer with its sources and
checks.

| Metric | Value | CI threshold |
|---|--:|--:|
| A right source cited (answerable and traps) | 0.95 | 0.75 |
| Traps answered from the right document | 1.00 | |
| Unanswerable questions answered "not in the documents" | **1.00** | 0.85 |
| Answerable questions refused (lower is better) | 0.05 | |
| Key facts found | 0.75 | 0.65 |
| The judge's "correct" (partial counts 0.5) | 0.83 | 0.65 |
| Faithfulness: claims the passages support | 1.00 | 0.80 |
| recall@5 of the search used | 0.87 | 0.80 |
| Latency p50 / p95 (search, rerank, answer) | 5.4 s / 7.0 s | |

"Not in the documents" worked six times out of six. Three unanswerable questions were
stopped before the model was asked: the reranker's best score was 0.004–0.15, under the 0.2
threshold. The other three were near misses that the model refused itself: Proxet's posting
has no salary, GlobalLogic's says nothing about Canada, and no document gives FOP tax rates.
The reranker had scored their best passages 0.77, 0.88 and 0.35. The one refusal of an
answerable question is error 2.

**Cost** per 1,000 questions, at OpenRouter's prices on 2026-11-12:
- answering: $0.15 (mistral-small answers, bge-m3 query embeddings; the reranker runs
  locally);
- judging: $0.40 more (Claude Haiku 5.5, verdict and faithfulness).

Embedding the corpus cost under a cent.

## The judge, checked by hand

<!-- CALIBRATION -->
Pending: a person grades the answers (`python main.py rag grade`), then `python main.py rag
calibrate` has the judge grade the same texts. The rules both use are in
`prompts/rag/judge_v1.yaml` and evals/README.md.

## Errors

1. **The outdated rate wins when the change is written as an amendment.** (o01, trap)
   - **Expected:** a reserved employee of a critical enterprise must earn at least 3 minimum
     wages, since Resolution 692 of 30.05.2026; 2.5 still holds in combat and occupied areas.
   - **Got:** "не нижче ... мінімальної заробітної плати ..., помноженої на коефіцієнт 2,5",
     citing the regional FAQ of March 2026, and 692's paragraph for combat areas.
   - **Why:** 692 makes the change in amendment language: "в абзаці третьому цифри “2,5”
     замінити цифрою “3”". That sentence never says "коефіцієнт" or "зарплата", so neither
     BM25 nor the vectors match it to the question. Its chunk also lacks the line saying which
     paragraph it amends; the same miss is retrieval question r12. The superseded FAQ states
     the old rule in plain words and is retrieved instead. The prompt's "newest wins" rule
     can't help, because no passage in front of the model states the new value.
2. **A cross-language question about the same document: a safe refusal.** (o04, r15)
   - **Expected:** yes: as worded by 692, a Diia City resident meeting article 5 of the
     digital-economy law, by its last six months of tax returns, qualifies as critical.
   - **Got:** "The documents don't say."
   - **Why:** the criterion is item 7 of a long amended list. With no headings, its chunk is
     cut by size and its header says only "Intro". The English question finds the Diia City
     documents instead. Failing to "don't know" is the cheap way to fail; inventing an answer
     would have been the expensive one.
3. **A two-column flowchart comes out interleaved.** (o07)
   - **Expected:** a company outside the territorial recruitment centre's area sends it two
     copies of the extracts and copies of the documents, and the centre checks them within
     3 days.
   - **Got:** only the first step, preparing the extracts for each centre.
   - **Why:** the source is a one-slide flowchart with two branches side by side. PyMuPDF reads
     the lines across both columns, so the branches' sentences alternate ("Військовозобов’язані
     працюють на / Військовозобов’язані працюють на підприємстві, яке знаходиться за межами /
     ..."). The model kept the one sentence that came out whole.
4. **The passage was there, and the model answered something else.** (q07)
   - **Expected:** spoken German is an advantage at DocStudio.
   - **Got:** "Віддалена робота тільки [1]" ("remote work only"), in Ukrainian, to an English
     question.
   - **Why:** the whole short posting is one chunk, and "Spoken German will be an advantage" is
     in it. But the chunk ends with Djinni's details in Ukrainian ("Тільки віддалено"), and a
     24B model latched onto them and their language. The judge marked it incorrect.
5. **The key-fact check is stricter than meaning.** (q06, q10)
   - **Expected:** CAPTCHAs and other anti-bot measures; B2 English and professional Ukrainian
     for client meetings.
   - **Got:** "handle various bot protections (e.g., Cloudflare)", and B2 English alone.
   - **Why:** the first answer is right in meaning, but "CAPTCHA" isn't in it, so key facts
     score 0. The judge, rightly, says partial for both. That is why key facts are only one
     check: string matching misses paraphrase, and the judge, calibrated by hand, covers it.

## What I'd improve next

- **Context in every chunk of a document without headings** (errors 1 and 2). The brief's
  stretch item, contextual chunk headers: a cheap model writes one line per chunk on what it
  changes and where it sits ("Resolution 692 raises the multiplier for reserved employees'
  pay from 2.5 to 3"). The line goes into the embedding and the BM25 text. Or carry the
  numbered point a piece belongs to into its header.
- **Layout-aware PDF extraction** for slides and flowcharts (error 3): read columns
  separately, or hand single-slide PDFs to a vision model.
- **An extract-then-answer prompt** (error 4): the model first quotes the sentence that
  answers, then answers from it. Or try a stronger answer model, at a known cost per 1,000
  questions.
- **More hand grades.** Fifteen or more answers per run, and grading faithfulness too, since
  now only correctness is calibrated.
- **The FOP tax rules and the Diia City law.** zakon.rada.gov.ua and tax.gov.ua refuse
  automated downloads. A person can save them from a browser into `data/rag/raw/official/`.

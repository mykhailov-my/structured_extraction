# Report: RAG with sources and evals (block 2)

The numbers come from `evals/results/` of the run committed with this report (`make rag`).
CI repeats the run on every push and fails below the thresholds in `rag.yaml`.

## Setup

- **Corpus:** 62 files: 50 Djinni postings (HTML) and 12 official documents (9 PDF, 3 DOCX).
  61 are indexed; 1 exact repost is dropped and 4 superseded versions are left out of search.
  This gives 438 chunks by structure, and 424 fixed-size chunks for the comparison. See
  README.md, "RAG (block 2)".
- **Contexts:** each chunk carries two lines, in Ukrainian and English, on where it sits in
  its document and what it is about. `openai/gpt-6-luna` wrote them from the whole document
  (prompt `context v2`).
- **Search:**
  - BM25, with Ukrainian and English endings cut;
  - `baai/bge-m3` embeddings (OpenRouter) in Qdrant;
  - reciprocal rank fusion of the top 30 from each;
  - `BAAI/bge-reranker-v2-m3` (INT8 ONNX, CPU) over the top 20 fused.
  - Each chunk is searched with its header and context. The answer gets the best 6 that fit
    in 2,400 tokens.
- **Answers:** `openai/gpt-6-luna`, prompt `answer v2`. If the reranker scores even the best
  passage under 0.2, the answer is "not in the documents" without a model call.
- **Judge:** `anthropic/claude-haiku-5.5`, prompts `judge v1` and `faithfulness v1`. It is
  from another model family than the one that answers and writes the contexts.
- **Test sets:**
  - 15 retrieval questions: 7 cross-language, 5 paraphrased, 3 that name the document;
  - 26 answer questions: 13 answerable, 7 traps (look-alikes, outdated versions), 6 with no
    answer in the corpus.

## What changed on 13 November

The first version, of 12 November, had the five errors listed under "Errors" below. Four
changes followed, each measured before the next was made:

| | 12 Nov | Layout order, contexts v1 | Answer v2 | Contexts v2 | Luna answers (now) |
|---|--:|--:|--:|--:|--:|
| recall@5, hybrid + rerank | 0.87 | 0.93 | 0.93 | **1.00** | **1.00** |
| MRR, hybrid + rerank | 0.74 | 0.72 | 0.72 | **0.86** | **0.86** |
| A right source cited | 0.95 | 0.95 | 0.95 | 0.85 / 0.90 | **0.95** |
| Traps answered from the right document | 1.00 | 1.00 | 1.00 | 0.71 / 0.86 | **1.00** |
| Key facts found | 0.75 | 0.85 | 0.88 | 0.83 / 0.88 | **0.95** |
| The judge's "correct" | 0.83 | 0.83 | 0.87 | 0.81 / 0.85 | 0.85 / 0.90 |
| Faithfulness | 1.00 | 1.00 | 0.98 | 1.00 / 0.98 | 1.00 |
| Unanswerable refused | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| Answerable refused (lower is better) | 0.05 | 0.00 | 0.05 | 0.15 / 0.10 | 0.05 |
| Latency p50 | 5.4 s | 7.6 s | 7.1 s | 7.2 s | 8.0 s |
| Cost per 1,000 questions | $0.15 | $0.20 | $0.21 | $0.21 | $0.32 |

- **Two numbers in a cell** are two runs of the same configuration. The answers aren't
  deterministic, and neither is the judge:
  - Mistral at temperature 0 through OpenRouter, and Luna, which takes no temperature, word
    their answers differently from run to run.
  - The judge graded one near-identical text "correct" once and "partial" once (o07).
  - So on 26 questions the judge's score moves by up to 0.06 between identical runs, and a
    smaller difference isn't one. The deterministic checks (sources, traps, key facts) held
    across Luna's three runs.
- **Cost:** the committed `metrics.json` says $0.07, because OpenRouter served prompts that
  repeated earlier runs from OpenAI's prompt cache. The table gives the first, uncached run.
  Judging costs another $0.47 per 1,000 questions.

The changes:
1. **PDF pages read in layout order** (error 3). PDF blocks used to be sorted by height,
   which interleaved side-by-side columns. Now they go by recursive XY-cut: rows top to
   bottom, and a run of columns one column at a time. Only pages with side-by-side blocks
   changed: the flowchart, the Supreme Court's two-column slides, two letters' header blocks
   and one signature line.
2. **Contextual chunk headers** (errors 1 and 2): two lines per chunk, written once and
   cached, for about $0.55. With them, BM25 matches cross-language questions too, and an
   amendment's chunk names what it changes.
   - Version 1 said "the coefficient rises from 2.5 to 3".
   - Version 2 says "the salary threshold for reservation rises from 2.5 to 3 minimum
     wages", and that is what the question asks about.
   - Details: README.md, "Contextual chunk headers"; prompts/CHANGELOG.md.
3. **Answer prompt v2** (error 4):
   - the code names the language and the exact refusal;
   - the question comes before the passages and after them;
   - "answer exactly what is asked";
   - the context lines are explained.
4. **GPT-6 Luna for answers.** Once retrieval found everything, Mistral Small was the limit.
   It refused o06 with the answer in its first passage, and it answered an English question
   in Ukrainian. Luna costs $0.11 more per 1,000 questions and 0.7 s more at the median.
   Each model ran twice on the same prompt and passages; the side by side is in
   prompts/CHANGELOG.md.

Engineering changes along the way:
- **CI in two jobs.** Lint, tests and retrieval need no key; the answers and the judge need
  the secret.
- **The judge in parallel**, six answers at a time. A reply whose JSON doesn't parse is asked
  for once more, and `judged` in `metrics.json` counts the answers graded.
- **Retrieval measured on four indexes** (each chunking, with and without contexts), with
  recall@20 as the reranker's pool.
- **Prompts in their own module**, shared by the answer, the judge and the contexts.
- **164 offline tests**, 30 of them for the RAG.

## Retrieval

The 15 questions each come with the passage that answers them, given as a document and a
quote. A chunk counts when it is from that document and its own text holds the quote; its
context doesn't count. So all four indexes are scored on the same questions. The full table
is in [evals/results/retrieval.md](evals/results/retrieval.md).

The search as used (hybrid + rerank) on the four indexes:

| Index | recall@1 | recall@3 | recall@5 | recall@20 (the pool) | MRR |
|---|--:|--:|--:|--:|--:|
| **structural + context** | **0.73** | **1.00** | **1.00** | **1.00** | **0.86** |
| structural | 0.67 | 0.80 | 0.87 | 0.93 | 0.74 |
| fixed + context | 0.53 | 0.80 | 0.87 | 0.87 | 0.68 |
| fixed | 0.60 | 0.80 | 0.80 | 0.87 | 0.68 |

Each step on structural chunks, without → with contexts:

| Search | recall@5 | MRR |
|---|--:|--:|
| BM25 | 0.40 → 0.60 | 0.28 → 0.48 |
| vectors | 0.73 → 0.80 | 0.51 → 0.57 |
| hybrid (RRF) | 0.53 → 0.80 | 0.39 → 0.54 |
| hybrid + rerank | 0.87 → 1.00 | 0.74 → 0.86 |

- **Contexts help BM25 most.** Without them it can't match "переїзд до Португалії" to
  "relocation to Portugal". Fusion was worse than vectors alone; with contexts, it matches
  them at recall@5 and has the larger pool at 20.
- **The reranker still matters most.** On the same pool it moves MRR from 0.54 to 0.86.
- **Structure gains more from contexts than fixed size does.** A structural chunk is one
  section, so its context can say which one. A fixed chunk often spans two, and its context
  has to describe both.
- **A caution:** context v2 was tried on the chunks behind errors 1 and 2 first, and those
  chunks are in this set (r12, r15). Its rule is general (what an amendment changes, what
  an added item allows), but 15 questions can't show that it generalizes. A fresh set of
  questions would.
- **The cost of contexts is at rank 1.** Every chunk of a posting now says which posting it
  is, so a sibling chunk of the right posting can outrank the one with the quote (r05).
  Under contexts v1, recall@1 fell from 0.67 to 0.53, partly for that reason; v2's more
  specific contexts brought it to 0.73. The answer sees both chunks either way.

## Answers

26 questions: 13 answerable, 7 traps, 6 with no answer in the corpus.
[evals/results/answers.md](evals/results/answers.md) has every answer with its sources and
checks.

| Metric | Value | CI threshold |
|---|--:|--:|
| A right source cited (answerable and traps) | 0.95 | 0.85 |
| Traps answered from the right document | 1.00 | |
| Unanswerable questions answered "not in the documents" | **1.00** | 0.85 |
| Answerable questions refused (lower is better) | 0.05 | |
| Key facts found | 0.95 | 0.80 |
| The judge's "correct" (partial counts 0.5) | 0.85 | 0.75 |
| Faithfulness: claims the passages support | 1.00 | 0.90 |
| recall@5 of the search used | 1.00 | 0.90 |
| Latency p50 / p95 (search, rerank, answer) | 8.0 s / 11.2 s | |

The thresholds were raised with the system (they were 0.65–0.80). Each sits below the
committed run with room for the run-to-run spread, so CI fails on a regression, not on noise.

"Not in the documents" worked six times out of six.
- **Stopped before the model was asked: three.** The reranker's best score was 0.009–0.02,
  under the 0.2 threshold.
- **Refused by the model: three near misses.**
  - Proxet's posting has no salary (best passage 0.80).
  - GlobalLogic's says nothing about Canada (0.93).
  - No document gives the 2027 minimum wage (0.47).
- **Answerable questions' best passages** scored 0.92–1.00.

The one answerable question refused is o04 (error 2).

**Cost** per 1,000 questions, at OpenRouter's prices on 2026-11-13, uncached:
- answering: $0.32 (GPT-6 Luna answers, bge-m3 query embeddings; the reranker runs locally);
- judging: $0.47 more (Claude Haiku 5.5, verdict and faithfulness).

The corpus cost about $0.55 once (contexts), plus under a cent (embeddings).

## The judge, checked by hand

<!-- CALIBRATION -->
Pending: a person grades the answers (`python main.py rag grade`), then `python main.py rag
calibrate` has the judge grade the same texts. The rules both use are in
`prompts/rag/judge_v1.yaml` and evals/README.md.

What to look at: six of the run's answers are "partial" only because they leave out a side
detail of the reference answer (error 5). The hand grades will show whether a person agrees.

## Errors

1. **The outdated rate won when the change was written as an amendment.** (o01, trap.)
   **Fixed:** the answer is now "не нижче трьох мінімальних зарплат … змінами від 30.05.2026
   поріг 2,5 замінено на 3", citing Resolution 692.
   - **Expected:** at least 3 minimum wages since Resolution 692 of 30.05.2026; 2.5 still
     holds in combat and occupied areas.
   - **Why it failed:** 692 makes the change in amendment language: "в абзаці третьому цифри
     “2,5” замінити цифрою “3”". That sentence says neither "коефіцієнт" nor "зарплата", so
     no search matched it to the question, and the superseded FAQ was retrieved instead.
   - **What fixed it:** the chunk's context now says "the salary threshold for reservation
     rises from 2.5 to 3 minimum wages". The chunk comes up for the question, and answer v2
     reads the amendment as a change from its date.
   - **What's left:** the judge says partial, since the answer leaves out the 2.5 that stays
     in combat areas. Another run gave it, and the judge said correct.
2. **A cross-language question about the same document.** (o04, r15.) **Half fixed.**
   - **Expected:** yes: as worded by 692, a Diia City resident meeting article 5 of the
     digital-economy law, by its last six months of tax returns, qualifies as critical.
   - **Now:** the criterion's chunk says in its context "the critical-importance criterion for
     Diia City residents". r15 ("Can a Diia City resident qualify as a critical enterprise to
     reserve its staff?") finds it at rank 1, up from a miss.
   - **Still failing:** o04 asks the same thing in other words ("be recognised as a critical
     enterprise so that its staff can be reserved"). The regional FAQ's note on Diia City
     residents outranks the criterion, so the passages don't have the answer, and the model
     says "The documents don't say." That is the cheap way to fail: inventing an answer
     would be the expensive one.
3. **A two-column flowchart came out interleaved.** (o07.) **Fixed** by reading PDF pages in
   layout order: both branches are whole.
   - **Now:** the answer has both steps (two copies of the extracts and copies of the
     documents; the centre checks them within 3 days), with all key facts. The judge called
     it correct in one run and partial in two, on near-identical texts.
4. **The passage was there, and the model answered something else.** (q07.) **Fixed** by
   answer v2.
   - **Before:** "Віддалена робота тільки [1]" ("remote work only"), in Ukrainian, to an
     English question. The chunk ends with Djinni's details in Ukrainian, and the model
     latched onto them and their language.
   - **Now:** "Spoken German will be an advantage [1]." The prompt names the reply's
     language, and it asks for exactly what was asked.
5. **The judge grades side details as missing facts.** (q01, q06, q08, q10, o01, o07.)
   - **What happens:** six answers have every key fact and a right source, and the judge
     still says partial, because each leaves out something the reference mentions. RabbitMQ
     as an alternative to Kafka; that Ukrainian is also needed for client meetings; the
     posting's date.
   - **What the rubric says:** its "correct" requires "every fact the reference requires",
     and the references are written more fully than the questions ask.
   - **What it means:** the judge's 0.85 understates the answers, and the deterministic key
     facts (0.95) are closer. Whether a person agrees is what the calibration is for.
     Until then, the judge's threshold in CI (0.75) leaves room for it.

## What I'd improve next

- **Calibrate the judge, then fix its rubric.** Once there are hand grades: if people call
  these answers correct, `judge v2` separates a missing required fact from a missing side
  detail, and the references mark which is which.
- **Wording sensitivity** (error 2). o04 and r15 ask the same thing and get different
  passages. Rewriting the question into the documents' terms before the search, or
  searching with two or three paraphrases and fusing them, would make retrieval depend less
  on wording.
- **A fresh retrieval set.** Context v2 was tuned with r12 and r15 in view; ten new
  questions written without looking at the contexts would show what it's really worth.
- **Repeat the answer evals.** Two runs of one configuration differ by up to 0.06 on the
  judge. Reporting the mean of three runs, or pinning one provider per model, would make
  small changes visible.
- **The FOP tax rules and the Diia City law.** zakon.rada.gov.ua and tax.gov.ua refuse
  automated downloads. A person can save them from a browser into `data/rag/raw/official/`.

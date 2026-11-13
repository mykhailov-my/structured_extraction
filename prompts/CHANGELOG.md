# Prompt changelog

A prompt version is the file `prompts/<doc_type>/<version>.yaml`. Once it has results in
`results/`, don't edit it: copy it to the next version, change that, and add an entry here
saying what changed, why (which errors, in which run), and what it did to the metrics.
Results store a hash of their prompt file, so an edited version is detected and re-run.

## v1 · 2026-10-21 · job, cv

Baseline: what to extract, "only what the text states, otherwise null or []", answer in
English, and the JSON schema with its field descriptions in the system prompt.

The schema is in the prompt even though the API enforces it. With constrained decoding
(Ollama's `format`) the model never sees the field descriptions otherwise, so it wouldn't
know that Upper-Intermediate means `b2`.

On 2026-10-24, before any golden label existed, the job schema was redesigned twice, and v1's
text stayed the same while the schema it embeds changed. The first redesign graded each
requirement by kind and a depth of 0–100. The second, which v1 runs with now, took Djinni's
own values as enums, split the requirements into five lists, and graded each skill with a level
(basic to expert) and its years. Hard skills now come from a list of 88 ids. Results made with
the earlier schemas don't count: they carry the old schema's hash and are run again. The fuller
labelling rules in `data/golden/README.md` are not in v1; they are the obvious candidate for
v2.

## v2 · 2026-10-24 · job

- Changed: v1 plus the golden set's rules for seniority and skill levels from
  `data/golden/README.md`. Seniority comes only from a level the posting names. A skill's level
  comes from its wording, with the Ukrainian equivalents, then its years, then the role's level.
  Nothing else changed.
- Why: in v1 all four runs made up a seniority from the years asked, on the same 12 of 30
  postings (seniority 0.57). Hard-skill levels scored 0.35–0.42. The commonest level miss was
  "experience with X" answered as middle where the rules say junior: 272 of 804 misses. Next
  came bare skill names answered at the role's level instead of one below, as with 706772's
  infrastructure list in a 6-year posting.
- Effect, against Claude's labels, which nobody has checked yet (results/metrics.md):
  - mistral-small: accuracy 0.888 -> 0.902 greedy and 0.885 -> 0.895 nucleus, still 100% valid.
  - qwen-9b: 0.877 -> 0.852 greedy and 0.851 -> 0.795 nucleus, valid 100% -> 97% and 93%.
    Its three failed postings (744638 greedy; 731104 and 854363 nucleus) all came from
    Darkbloom. OpenRouter spreads qwen3.5-9b over several providers, and Darkbloom doesn't
    enforce the schema. It returned ids such as `deep_learning` and `scrapy`, or items without
    a `name`, and repeated them in the repair. Of Darkbloom's first answers, 6 of 8 broke the
    schema on v2 and 1 of 17 on v1. Parasail and SiliconFlow broke it in none of 95.
  - On the postings both versions answered validly, v2 is ahead in every run: qwen-9b
    0.875 -> 0.901 greedy (29 postings) and 0.853 -> 0.881 nucleus (28).
  - Levels: hard skills 0.35–0.42 -> 0.46–0.59, soft skills 0.38–0.50 -> 0.66–0.74.
  - Seniority didn't improve: the models still infer it from years on the same postings.
    mistral-small also reads 852050's "Senior Python Developer" as middle, from its 3 years:
    the role-level rule leaked into seniority. That's the next thing to fix.
  - The lists v2 doesn't target (soft skills, domain experience, legal) moved by up to 0.14
    both ways. Greedy and nucleus already differ by up to 0.11 on them in v1, so 30 postings
    can't tell these changes from noise.
  - The longer prompt costs 10–20% more per 1,000 postings (mistral-small greedy
    $0.64 -> $0.72, qwen-9b greedy $0.80 -> $0.96). Median latency grew by 0.3–2.5 s.
  - Claude wrote both the labels and these rules, so some of the gain may be agreement with
    Claude's reading of the postings. The numbers will hold once the labels are checked.

<!--
## v3 · YYYY-MM-DD · job

- Changed: ...
- Why: ... (runs and doc ids from results/mismatches.csv)
- Effect: accuracy 0.xx -> 0.yy, valid xx% -> yy% (results/metrics.md)
-->

# RAG prompts (homework 2)

The RAG's prompts are `prompts/rag/<name>_<version>.yaml`:
- `answer`: the answer with its sources;
- `judge`: an answer against the expected one;
- `faithfulness`: an answer's claims against its passages;
- `context`: a chunk's context, written once per chunk and cached.

`rag.yaml` picks the versions. The same rule as above applies: a
version with results is frozen, and a change is a new version with an entry here.

## answer v1, judge v1, faithfulness v1 · 2026-11-12

Baseline.
- **answer:** uses only the numbered passages and cites [n] after every sentence.
  - It says exactly "У документах цього немає." / "The documents don't say." when the passages
    don't answer, or answer only part of what was asked.
  - It keeps to the company and document the question names.
  - When passages disagree, it takes the newest.
- **judge:** grades correct, partial or incorrect by the rules a person grades by
  (evals/README.md), giving its reason first.
- **faithfulness:** splits the answer into claims and checks each against the passages.

Before any model answers, retrieval already refuses: if the reranker scores even the best
passage under `min_relevance`, the answer is "not in the documents" and the model isn't
asked.

## context v1 · 2026-11-13 (replaced by v2 the same day)

Contextual chunk headers (`src/rag/context.py`). `openai/gpt-6-luna` reads a chunk's whole
document and writes where the chunk sits and what it is about, in two lines: Ukrainian, then
English. The lines are searched with the chunk (BM25, embeddings, reranker) and shown with it
to the answer model. A chunk's relevance in the evals is still judged on its own text.

**Retrieval** (15 questions, structural chunks, without → with contexts):

| Search | recall@5 | MRR |
|---|--:|--:|
| BM25 | 0.40 → 0.53 | 0.28 → 0.53 |
| vectors | 0.73 → 0.80 | 0.51 → 0.51 |
| hybrid | 0.53 → 0.67 | 0.39 → 0.57 |
| hybrid + rerank | 0.87 → 0.93 | 0.74 → 0.72 |

- r12, the 2.5 → 3 amendment, went from rank 18 to rank 3.
- recall@1 fell from 0.67 to 0.53. Every chunk of a posting now says which posting it is, so
  a sibling chunk can outrank the one that holds the quote (r05). That is the same document,
  so the answer still sees it. r11 lost rank 1 to a look-alike posting.
- o01's own question still missed the amendment. Its context said "the coefficient rises from
  2.5 to 3", not that the coefficient is for pay.

**Answers** (answer v1; the budget rose from 1,800 to 2,400 tokens, so that six passages
still fit with their contexts):
- key facts 0.75 → 0.85;
- refusals of answerable questions 0.05 → 0;
- the judge 0.83 → 0.83.

Two answers came out as bare citations ("[1, 2]").

## answer v2 · 2026-11-13

- **Language and refusal:** the code now names both in the message ("Answer in English. If
  the passages don't answer it, reply exactly: The documents don't say."). Before, v1 asked
  the model to infer the question's language, and it answered an English question in
  Ukrainian (q02, q07).
- **The question twice:** it comes before the passages and after them.
- **Only what was asked:** answer exactly the question, and leave out the rest of a
  passage: a posting's salary, format and location. In v1, DocStudio's German question got
  "remote work only" (q07).
- **Context lines explained:** they say where a passage sits; the facts come from the
  passage's own text.
- **Amendments:** "замінити" and "доповнити" change the text they name from their date on.

Results, with context v1 under both prompts:
- the judge 0.83 → 0.87;
- key facts 0.85 → 0.88;
- faithfulness 1.00 → 0.98;
- refusals of answerable questions 0 → 0.05.

q02 is answered in English, q07 (DocStudio's German) and q12 are now correct, and no answer
is a bare citation. o04 (Diia City) is refused again, as under v1 before contexts.

## context v2 · 2026-11-13

- **Amendments:** a context now says what the amended provision regulates, in the words of a
  question about it, with its old and new values. "A bare number is not enough: say what it
  measures and for whom."
- **List items:** an item added to a list (criteria, grounds, exceptions) is described by
  the list, and by what the item allows and for whom.

Why: under v1, the 2.5 → 3 chunk's context said "the coefficient rises from 2.5 to 3". o01
asks about pay, and its search still didn't find that chunk.

How it was tried: first on the chunks behind errors 1 and 2 (three samples of the 2.5 → 3
chunk, two of the Diia City one), then for all 862 chunks. Those chunks are in the
retrieval set, so its numbers flatter v2 somewhat. The rule is general, but 15 questions
can't show that it generalizes.

**Retrieval** (structural chunks, hybrid + rerank), v1 → v2:
- recall@1 0.53 → 0.73;
- recall@5 0.93 → 1.00;
- MRR 0.72 → 0.86;
- r12 went from rank 3 to rank 1, and r15 from a miss to rank 1.

**Answers** (answer v2, Mistral) stayed within the run-to-run spread: two identical runs
scored 0.81 and 0.85 with the judge. o01 now answers 3, citing 692, though without the 2.5
that still holds in combat areas.

## answer v2 on openai/gpt-6-luna · 2026-11-13 (rag.yaml: the model, not the prompt)

The answer model is now `openai/gpt-6-luna` instead of `mistralai/mistral-small-3.2-24b-instruct`.
It runs at its own temperature, since a reasoning model takes no other, with up to 3,000
tokens, since its thinking counts towards them.

With contexts v2 in place, retrieval stopped being the limit, and Mistral was. It refused
o06 with "на шість місяців" in its first passage, and it answered q10 in Ukrainian although
told "Answer in English".

The prompt, passages and judge were the same for both models; each was run twice:

| | Mistral Small 3.2 | GPT-6 Luna |
|---|--:|--:|
| A right source cited | 0.85 / 0.90 | 0.95 / 0.95 |
| Traps | 0.71 / 0.86 | 1.00 / 1.00 |
| Key facts | 0.83 / 0.88 | 0.95 / 0.95 |
| The judge | 0.81 / 0.85 | 0.90 / 0.85 |
| Refusals of answerable questions | 0.15 / 0.10 | 0.05 / 0.05 |
| Cost per 1,000 questions | $0.21 | $0.32 |
| Latency p50 | 7.2 s | 7.9–8.5 s |

The cost is the first, uncached run's. OpenRouter caches repeated prompts for OpenAI's
models, and the second run cost $0.07.

The one refusal left is o04. Its passages lack the Diia City criterion: a retrieval miss on
that wording, while r15's wording finds the criterion at rank 1.

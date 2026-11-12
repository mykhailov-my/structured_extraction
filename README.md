# structured_extraction

The course project of the AI Engineering course: the Python job market in Ukraine, as Djinni
shows it. It has two parts so far, and the block 3 agent will work on the second part's
corpus.

- **Block 2, RAG with sources and evals (homework 2):** it answers questions about Djinni
  postings and official documents on working in Ukrainian IT.
  - Every claim cites its document and section, and the answer is "not in the documents" when
    they don't have it.
  - The evals check retrieval and answers on every push.
  - See [RAG (block 2)](#rag-block-2) and [REPORT.md](REPORT.md).
- **Block 1, structured extraction (homework 1):** it turns messy Djinni texts (job postings
  and candidate CVs) into JSON that matches a schema.
  - It measures which model, prompt and sampling settings should do it in production. A 24B
    hosted model and a 9B open-weight one, small enough for a laptop, are compared, both
    through [OpenRouter](https://openrouter.ai). The 9B one can run on
    [Ollama](https://ollama.com) instead.
  - Both are scored on a golden set of 30 labelled Python postings.
  - The report template is [docs/block1-report.md](docs/block1-report.md).

## Quick start

You need [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 itself) and an OpenRouter
API key. Ollama is needed only to run the open model on your own machine (`qwen-local`).

```bash
make setup     # install dependencies, create .env from .env.example; put the key in .env
make models    # optional, for qwen-local: ollama pull qwen3.5:9b (~6.6 GB)
make data      # optional: crawl more job postings from djinni.co
make archive   # optional: every Djinni posting in the Wayback Machine (about a week)
make postings  # all collected postings in one format: data/postings/<year>.jsonl
make label     # check the golden labels in a page in your browser
make run       # block 1: every experiment in config.yaml, then the metrics
make rag       # block 2: ingest data/rag/raw/, measure retrieval, answer and score the test set
make ask Q="Чи розглядає RenovateHub кандидатів без досвіду?"   # block 2: one question
```

`make run` is `uv run python main.py run`. Without uv:
`python -m venv .venv && . .venv/bin/activate && pip install -e . && python main.py`.

| Command | What it does |
|---|---|
| `python main.py run` | Runs every combination in `config.yaml`, then scores them. Narrow it down with `--models`, `--prompts`, `--sampling`, `--doc-types` or `--limit N`; `--force` ignores stored results. |
| `python main.py eval` | Re-scores stored results without calling a model. |
| `python main.py extract FILE` | Extracts one file and prints the JSON, for trying out a prompt. |
| `python main.py check` | Counts texts and golden labels and validates the labels. |
| `python main.py label` | Opens a page in your browser for checking the golden labels: a posting beside a form holding its label from `data/golden/job/`. Saving marks the posting verified, and the page then shows where your label differs from Claude's ([data/golden/README.md](data/golden/README.md)). |
| `python main.py crawl-jobs` | Collects public job postings from djinni.co (see [Collecting data](#collecting-data)). |
| `python main.py crawl-archive` | Fetches every posting's page from the Wayback Machine into a cache (see [Every posting](#every-posting-the-wayback-machine)). |
| `python main.py crawl-djinni` | Fetches every posting in a range of job ids from djinni.co into a cache (see [2025–2026](#20252026-straight-from-djinnico)). |
| `python main.py build-postings` | Writes every collected posting, live and archived, in one format to `data/postings/<year>.jsonl`. |
| `make test`, `make lint` | Offline unit tests; ruff. |

## RAG (block 2)

Questions about Python jobs in Ukraine, answered from the documents with the sources cited:

```bash
make rag     # ingest data/rag/raw/, measure retrieval, answer and score the test set
make ask Q="Яка компанія годує команду обідами в київському офісі?"
python main.py rag search "relocation to Portugal" --mode bm25   # or vector, hybrid, rerank
```

`make rag` is `python main.py rag all`. CI runs the same command on every push and pull
request (`.github/workflows/evals.yml`) and fails when a metric falls below its threshold in
`rag.yaml`. It needs `OPENROUTER_API_KEY` in `.env`, or as a repository secret for CI. The
results go to `evals/results/`, and the analysis is in [REPORT.md](REPORT.md).

```text
data/rag/raw/  HTML, PDF, DOCX ──► ingest: structure, cleaning, dedup ──► documents.jsonl, manifest.json
               ──► chunk by sections ──► chunks.jsonl ──► BM25 + bge-m3 vectors (Qdrant) ──► RRF
               ──► bge-reranker ──► best passages within 1,800 tokens ──► answer with [n] citations
                                                                      └─► or "not in the documents"
```

| Step | Code | Output |
|---|---|---|
| Corpus | `src/rag/corpus.py` | `data/rag/raw/{djinni,official}/` with `sources.json` |
| Ingestion | `src/rag/ingest.py` | `data/rag/documents.jsonl`, `data/rag/manifest.json` |
| Chunking | `src/rag/chunking.py` | `data/rag/chunks.jsonl`, `data/rag/chunks_fixed.jsonl` |
| Search | `src/rag/search.py` | `data/rag/embeddings.jsonl` (the embedding cache) |
| Answers | `src/rag/answer.py`, `prompts/rag/` | |
| Evals | `src/rag/evaluate.py`, `evals/` | `evals/results/` |

### Corpus

62 files in three formats. [`data/rag/manifest.json`](data/rag/manifest.json) lists every
file: format, size, hashes, status and chunk counts.

- **50 Djinni postings (HTML), 2019–2026.** They are block 1's golden postings, reposts of two
  of them, and earlier and later postings of eight companies (Luxoft, Sigma Software,
  GlobalLogic, Ajax Systems, DataArt, N-iX, Intellias, Dataforest). So look-alike postings and
  outdated versions are there to trip the search up. They are copied from the crawlers'
  caches without recruiters' names, links and photos, and without contact details in the
  text.
- **12 official documents (9 PDF, 3 DOCX), 2016–2026.** They come from government sites, on
  what postings refer to:
  - reservation of employees (Resolution 692 amending Resolution 76, the Ministry of Economy's
    letters, a regional administration's FAQ and form);
  - military registration;
  - labour relations under martial law (the Supreme Court's review);
  - Diia City.

  The copies have the names and direct phones of the officials who signed or prepared them
  blacked out, and no metadata. FOP taxation is missing: the tax service's sites refuse
  automated downloads (403), and zakon.rada.gov.ua's robots.txt bars them.

### Ingestion

`python main.py rag ingest` turns each raw file into Markdown with its metadata (source URL,
title, date or edition, language, company or publisher, hashes).

- **Structure:**
  - Djinni pages go through the crawler's parser, which drops the page's chrome.
  - The description's own section titles become headings ("Requirements:", "Що пропонуємо:").
  - PDF headings come from font size and weight per text block, so a bold word inside a
    paragraph is not a heading, and a title wrapped over lines is one heading.
  - Laws' "Розділ", "Глава" and "Стаття" lines are headings whatever their font.
  - PDF tables are detected and kept as Markdown tables, and so are DOCX tables; bullets and
    numbered items become list items.
- **Cleaning:** Unicode NFC; non-breaking and zero-width spaces and soft hyphens; words
  hyphenated across PDF lines; running headers, footers and page numbers (a line at a page's
  edge that repeats on most pages).
- **Deduplication:**
  - A SHA-256 of the text without the posting's date drops an exact repost: RenovateHub's
    trainee posting was reposted word for word.
  - Near-duplicates (word 5-shingles, Jaccard ≥ 0.85) stay, but the older one is marked
    superseded: the same posting reposted with a change. RenovateHub's January posting
    required half a year of experience, and the February repost also takes candidates with
    none.
  - Editions of one official document are marked the same way.
  - Superseded versions are kept out of search by default (`--all-versions` brings them back).
  - In all: 1 duplicate, 4 superseded, 61 documents indexed.

### Chunking

Postings and laws have their own structure, and questions follow it. A question about a
posting asks about one of its parts: what it requires, what it offers, its conditions (salary,
format, English). A question about an official document asks about one provision, an article
or a numbered point, or one of a FAQ's questions. So the chunks follow that structure:

- A section (a heading and what follows it) of up to 400 tokens is one chunk.
- A longer section is cut between paragraphs, list items or numbered points, into pieces of
  about 250 tokens, never inside one.
- Sections under 60 tokens join the next one: a posting's skills, languages and Djinni's
  details make one chunk.
- Each chunk starts with a header naming its document and section: "Senior Backend Engineer
  (Python) — Proxet, 2026-10-21 › Description › Nice to have". Without it, a list of
  requirements from one posting looks like any other's. With it, the company and the date are
  in both the BM25 text and the embedding.

The sizes are set by the documents. A posting section is 50–300 tokens, and a FAQ answer or a
law's point is 100–400. So 250–400 holds one unit whole and stays well inside bge-m3's and the
reranker's windows. Six of them fit the answer's context budget of 1,800 tokens.

**Compared with fixed-size chunks** (250 tokens, 50 overlapping, the same header without the
section), on the same 61 documents:

| | Structural | Fixed |
|---|--:|--:|
| Chunks | 437 | 424 |
| Median tokens (header included) | 233 | 283 |
| Chunks that start or end inside a sentence or list item | 3% / 2% | 81% / 81% |
| Chunks that mix two or more sections | 0% | 41% |
| recall@5, search as used (hybrid + rerank) | **0.87** | 0.80 |
| MRR, search as used | **0.74** | 0.68 |
| recall@5 / MRR, vectors only | 0.73 / 0.51 | 0.73 / 0.56 |

One posting shows the difference. Proxet's second fixed chunk starts mid-sentence
("…across services, data flows, and deployment environments."). It holds the end of the
requirements and the start of the nice-to-haves, and stops inside one ("Familiarity with
simulation platforms, digital twins,"). So an answer from it can't tell a requirement from a
plus. The structural chunk "Description › Nice to have" holds that list whole under its
heading, and the answer cites the section by name.

The retrieval numbers come from 15 questions, so one question moves recall by 0.07. With the
reranker, structure wins by one question at recall@5 and by 0.06 in MRR. Vectors alone do a
little better on fixed chunks: they are larger, and the embedding gets more context.
- Where structure helps: a posting's sections and a FAQ's questions are units of meaning, and
  their headers say which posting and which part.
- Where it doesn't: a document with no headings, like Resolution 692's list of amendments, is
  cut by size either way. Its "replace 2.5 with 3" sentence then lacks the line saying which
  paragraph it changes (REPORT.md, error 1).

The full table, every search mode on both chunkings, is in
[evals/results/retrieval.md](evals/results/retrieval.md).

### Search

`src/rag/search.py` has four modes, so that each step is measured on its own:

- `bm25`: lexical, with Ukrainian and English endings cut ("розробника" matches
  "розробник").
- `vector`: `baai/bge-m3` embeddings (multilingual, 1,024 dimensions, through OpenRouter) in
  a Qdrant collection with cosine distance. Embeddings are cached by the text's hash in
  `data/rag/embeddings.jsonl`, which is committed, so CI embeds only what changed.
- `hybrid`: the top 30 of each, fused by reciprocal rank fusion (k = 60).
- `rerank` (the default): the top 20 fused candidates rescored by `BAAI/bge-reranker-v2-m3`.
  It is a multilingual cross-encoder, run as INT8 ONNX on the CPU through fastembed; it
  downloads once, 0.57 GB.

Metadata filters work in every mode, in Qdrant's payload filter and in BM25 alike:
- the kind (`--kind posting|official`);
- the earliest date (`--since 2025-01-01`);
- the company;
- the language;
- the current version only, the default (`--all-versions` turns it off).

### Answers

`src/rag/answer.py` with `prompts/rag/answer_v1.yaml` (versions and changes in
[prompts/CHANGELOG.md](prompts/CHANGELOG.md)):

- **"Not in the documents"** comes in two steps.
  - Before any model call: if the reranker scores even the best passage under 0.2, the
    answer is "У документах цього немає." / "The documents don't say." On the test set,
    answerable questions' best passages score 0.90–0.999, and off-topic questions' best
    passages score 0.003–0.009.
  - A near miss (the right posting, but it has no salary) gets past that step, so the prompt
    makes the model say the same when the passages don't answer.
- **Context budget:** the best passages, in order, while they fit in 1,800 tokens (o200k
  tokenizer); the best one is cut to fit if it alone is too long.
- **Sources:** the passages are numbered, and the model puts [n] after every sentence. The
  numbers map back to the document and section shown under the answer, and the evals check
  them.
- **Conflicts:** each passage's header carries the document's date, and the prompt has the
  newest win. Superseded versions are filtered out before that.

### Evals

[evals/README.md](evals/README.md) describes the files and every metric:
- retrieval: recall@k and MRR for each mode and chunking;
- answers: source accuracy (with forbidden sources for traps), key facts, abstention on
  unanswerable questions and false abstention on answerable ones;
- an LLM judge from another model family, calibrated against answers a person graded;
- faithfulness, claim by claim against the passages.

CI fails below the thresholds in `rag.yaml`.

## How it works

```text
text ─► prompt vN: system (rules + JSON schema) + user (the text)
     ─► provider.complete()    structured output: the answer is constrained to the schema;
                               timeout per model; timeouts, 429 and 5xx retried with back-off
     ─► Pydantic validation ── valid ──► ok
          │ invalid
          ▼
        one repair call: its answer + the validation errors ── valid ──► repaired
          │ still invalid
          ▼
        failed
```

- **Schemas** (`src/extraction/schemas.py`): `JobPosting` has 16 fields and follows what Djinni
  records. Company type, domain, employment, work formats, where candidates may be (Ukraine,
  Europe and Ukraine, the EU, worldwide, or listed countries) and language levels are enums
  of Djinni's own values. They come from its job filters and the fact lines of 1,051 postings.
  Salary is a nested object. The requirements are five lists: hard skills, soft skills,
  languages, domain experience and legal conditions such as a time zone or military
  registration. A skill has a level, from basic through junior, middle and senior to expert,
  and the years when the posting gives them. Hard skills take one of 88 ids in 16 areas
  (`src/extraction/skills.py`), built from Djinni's skill tags. Technologies keep their own
  id; practices share one, so REST, OpenAPI and API integration are all `rest_api`. Anything
  else is `other` plus its name. `CandidateProfile` (10 fields) shares the vocabulary, so jobs
  and candidates can be matched later. Names, contacts, links and employer names are not
  extracted.
- **One interface, two providers** (`src/extraction/providers/`). `OpenRouterProvider` uses the
  OpenAI-compatible API with `response_format: json_schema` in strict mode, and is routed only to
  upstreams that support it. `OllamaProvider` passes the schema as `format`, which makes decoding
  follow it. The pipeline only sees `Provider.complete()`. The experiment runs both models on
  OpenRouter; `qwen-local` in `config.yaml` runs the same 9B weights on Ollama with no code
  change.
- **The schema sent to models is portable.** `$ref`s are inlined and constraints such as
  `exclusiveMinimum` are removed, because strict modes reject them. Pydantic still checks them on
  the answer, and a violation goes down the repair path.
- **Every result is logged** to `results/runs/<doc_type>__<model>__<prompt>__<sampling>.jsonl`:
  model, prompt version and file hash, sampling parameters, status, each raw answer with its
  validation errors, tokens, cost and latency.
- **Stored results are reused** when the text, prompt file, schema, model and sampling haven't
  changed, so a new prompt version only pays for its own runs. Provider errors are retried on
  the next run.

## Configuration

`config.yaml` is the whole experiment. `experiment` lists the doc types, models, prompt versions
and sampling profiles, and every combination of them is run. `models` maps a name to a provider
and model id, `sampling` holds the `temperature` / `top_p` profiles, and `retry` sets the retry
policy. Keys are validated, so a typo fails at start-up instead of quietly changing a run.

Keys live in `.env`, which git ignores; only `.env.example` is committed.

## Metrics

`eval` writes `results/metrics.md` (the tables for the report), `results/metrics.json`, and
`results/mismatches.csv`, which lists every wrong field with its expected and predicted value
for error analysis.

| Metric | Meaning |
|---|---|
| Valid | Share of documents with a schema-valid answer, first try or after the repair call. |
| 1st pass | Valid without the repair call. |
| Failed, Errors | Still invalid after the repair; the provider kept failing, so there was no answer. |
| Accuracy | Mean over fields of the per-field score on golden documents. Enums and numbers need an exact match, and null = null counts as correct. Free text uses word-level F1. Lists use F1 over normalised items (`Node.js` = `nodejs`). Nested objects are scored per leaf (`salary.max_amount`). The requirement lists are paired by id (`python` with `python`; two `other` items by their own words): `hard_skills` is the F1 of the ids, and `hard_skills.level`, `.years` and `.must_have` are scored on the pairs. Free text inside a requirement (`name`, `detail`) isn't scored. A failed document scores 0 on every field; provider errors are left out and counted under Errors. |
| p50, p95 | Seconds per document for the whole extraction, including the repair call and retry waits. The local model is loaded before the first document, so loading isn't counted. |
| $ / 1k docs | Mean cost per document × 1000, as billed by OpenRouter (`usage.cost`); 0 for the local model. |

## Collecting data

`python main.py crawl-jobs --count 20` (or `make data`) collects public job postings from
djinni.co. It takes the newest postings from the RSS feed, round-robin across categories so a
small sample stays varied; `--keywords Python,Java` limits it to those categories. Postings
already in `data/` are skipped. Each posting is stored twice:

- `data/scraped/job/<id>.json`: the page's parts as scraped (title, category, company, salary,
  skills, language requirements, the sidebar facts and the description) with the URL and
  dates, in the [one format](#every-posting-the-wayback-machine) every posting is kept in.
- `data/texts/job/<id>.txt`: the same parts as plain text, which is what the model reads.

The crawler names itself in its User-Agent, obeys robots.txt (which allows `/jobs/`), waits 3 s
between requests and backs off on 429 and 5xx. Emails, phone numbers, links and @handles become
`[email]`, `[phone]`, `[link]` and `[handle]`, and so does a messenger username without the "@"
("в телеграм ivan_hr"). A recruiter's name in a self-introduction ("Меня зовут Елена") becomes
`[name]`. Other names in free text aren't detected, so read new texts before committing them:
the repository is public.

CVs aren't collected. robots.txt disallows candidate profiles (`/developers`), and Djinni's terms
forbid collecting candidates' data by scraping. The `CandidateProfile` schema and its prompt
stay for when there is a source of CVs; until then `config.yaml` runs job postings only.

### Every posting: the Wayback Machine

Djinni keeps closed postings online but hides their date, and nothing lists them. The
[Wayback Machine](https://web.archive.org) has captured about 79,000 Djinni postings since 2017
(78,687 in October 2026; 17,607 of them first captured in 2021, 16,676 in 2025). Two commands
collect them:

```bash
python main.py crawl-archive    # fetch every posting's archived page: about 6 days
python main.py build-postings   # all of them in one format, data/postings/<year>.jsonl
```

- **Index.** The archive's CDX index lists the captures of `djinni.co/jobs/<id>-<slug>/` pages,
  one query per year (`--years`, 2017 to now by default; `--keyword python` keeps slugs with that
  word). The index is slow, a minute or more a query, so its answers are cached in
  `.cache/wayback/`; delete the `.txt` files there to pick up newer captures.
- **Crawl.** Each posting's oldest capture is fetched as archived and kept, gzipped (about 8 KB),
  in `.cache/wayback/pages/`. When it is missing or an error page (Djinni at times blocked the
  archive's crawler with "your IP address has been blocked"), a later capture stands in, and
  `.cache/wayback/failed.txt` notes it so it isn't asked for again. Postings are fetched in a
  fixed random order, so a crawl stopped at any point leaves a random sample, and running it
  again carries on. At 5 s between requests, about 7 s a posting, the whole archive takes
  about 6 days; `--limit N` stops after N postings. To run it in the background on a Mac,
  awake, and follow it:

  ```bash
  nohup caffeinate -is uv run python main.py crawl-archive >> .cache/wayback/crawl.log 2>&1 &
  tail -f .cache/wayback/crawl.log     # a line a posting; time left every 100
  pkill -f "main.py crawl-archive"     # stop; run it again to carry on
  ```
- **Layouts.** Djinni's markup changed three times. `parse_snapshot` reads every version into
  the same parts as `crawl-jobs`, and `layout` in the record says which one the page had:

  | Layout | Captured | Markup |
  |---|---|---|
  | v1 | until mid-2022 | description in `.profile-page-section`, a details line under the title |
  | v2 | mid-2022 to spring 2024 | `.job-details--main-info` header, `.job-additional-info` sidebar |
  | v3 | May to September 2024 | `.job-post-description`, today's sidebar |
  | v4 | since September 2024 | today's page (`.job-post__description`), read by `crawl-jobs`' parser |

  Pages up to v2 show the recruiter's name, photo and job title. The name and photo are left
  out, and the job title is only used to find the company ("HRM at Ogorodniki, Inc").
- **One format.** `build-postings` parses every cached page, plus the postings `crawl-jobs`
  collected, into one record per posting, one JSON object a line, a file per year. A posting
  found in both is kept from djinni.co. The files are rebuilt whole, in minutes, so a parser fix
  reaches every posting without downloading anything again.
- **Dating.** `posted` is the date a page shows. Closed postings show none, and neither did any
  page from May 2024 to early 2025. Djinni hands out job ids in order, so `date` is `posted` or
  else the median date of the 100 dated postings nearest in id, and `year` is its year. A
  posting older or newer than every dated one goes to `undated.jsonl`.
- **Size.** About 6–7 KB a posting, so the whole archive comes to a few hundred MB, plus the page
  cache. Both are git-ignored.

| Field | Meaning |
|---|---|
| `doc_id`, `job_id` | `djinni-<id>`, and Djinni's job id, which grows over time |
| `url`, `source`, `snapshot` | the posting's URL; `djinni.co` (crawled live) or `web.archive.org`, and the archived copy |
| `captured_at` | when the page was fetched, or archived |
| `posted`, `date`, `year` | the date the page shows; that or the estimate from the job id; its year |
| `active` | false when the page marks the posting closed |
| `layout` | `v1` to `v4`, see above |
| `title`, `category`, `company`, `salary` | as the page shows them; `category` is Djinni's: Python, QA Automation, ... |
| `skills`, `languages` | the page's lists of required skills and languages (v4); older layouts have them among the facts |
| `facts` | the details line and sidebar: experience, English, work format, countries, domain, company type |
| `description` | the posting's own text, line by line, list items as "- " |

`data/archive/` holds the earlier 50-a-year sample of Python postings, in the layout `crawl-jobs`
uses; `data/postings/` has all of them too.

### 2025–2026 straight from djinni.co

Djinni keeps closed postings online too, and any posting loads by its job id: `/jobs/<id>-x/`
redirects to it. Job ids grow in order, so a range of ids is every posting of a stretch of
time; 2025 starts at about 700,000, and the newest is about 855,000 (October 2026), about
150,000 postings in all.

```bash
python main.py crawl-djinni --ids 700000-   # 2025 up to the newest posting, into .cache/djinni/
```

Djinni answers in about 0.4 s, but it blocks IPs that ask too fast, and the block also covers
browsing Djinni from that network. 8 workers at 0.5 s each were blocked within about 10
seconds on 23 October 2026. The crawler stops at the first HTTP 403, block page or lasting 429;
the defaults, one worker at 3 s, make 2025–2026 about five days. `build-postings` reads
`.cache/djinni/` too. Djinni's own page wins over an archived copy, and keeps the copy's date
when the page, closed by now, shows none.

## Data and prompts

- `data/texts/job/` holds the 30 texts of the experiment, Djinni Python postings from
  2025–2026, and `data/golden/job/<doc_id>.json` their labels. Claude wrote them, and a
  person checks each one in `make label`, which records it in `data/golden/verified.txt`. The
  rules and notes on the hard cases: [data/golden/README.md](data/golden/README.md). The rest
  of `data/`:
  [data/README.md](data/README.md).
- `prompts/<doc_type>/<version>.yaml` are the prompt versions (system, user and repair
  templates). Every change is logged in [prompts/CHANGELOG.md](prompts/CHANGELOG.md).

## Layout

```text
main.py              entry point: python main.py (python main.py rag ... for block 2)
config.yaml          block 1's experiment: models, sampling, prompt versions
rag.yaml             block 2's RAG: models, prompt versions, search settings, CI thresholds
src/extraction/
  schemas.py         JobPosting, CandidateProfile, the portable JSON schema
  providers/         the Provider interface, OpenRouter, Ollama
  pipeline.py        one document: call, validate, repair once, retries
  runner.py          the experiment matrix and reuse of stored results
  evaluate.py        metrics and reports
  labelling.py       the labelling page (labelling.html) and its local server
  collect/           Djinni crawlers (live site, Wayback Machine), the one posting format
  cli.py             commands
src/rag/             block 2
  corpus.py          picks the postings, strips people from pages, redacts official files
  ingest.py          HTML, PDF, DOCX to Markdown; cleaning; duplicates and versions
  chunking.py        by structure, and the fixed-size baseline
  search.py          BM25, bge-m3 in Qdrant, fusion, the reranker, filters
  answer.py          the context budget, the answer with sources, "not in the documents"
  evaluate.py        retrieval and answer metrics, the judge, faithfulness, calibration
  cli.py             python main.py rag ...
prompts/             versioned prompts (prompts/rag/ for block 2) and CHANGELOG.md
data/                texts, scraped records, golden labels; postings/ (git-ignored)
data/rag/            block 2's corpus (raw/), documents, chunks, manifest, embedding cache
evals/               block 2's test sets, hand grades and results
results/             block 1's model outputs and metrics
tests/               offline tests with fake providers
.github/workflows/   CI: tests and block 2's evals on every push
REPORT.md            block 2's report (block 1's template: docs/block1-report.md)
```

## Roadmap

- [x] Boilerplate: schemas, both providers, validation with one repair, metrics
- [x] Crawler for Djinni job postings (CVs: no source that may be used)
- [x] Archive crawler: Python postings 2019–2026, for how requirements changed
- [ ] Every posting in the archive, in one format (archive crawl paused; 2025–2026 Python
  postings fetched from djinni.co)
- [x] Schema v2: Djinni's own enums; requirements by kind, each skill with a level and its years
- [x] 30 texts: Python postings, 2025–2026
- [x] Golden labels: all 30, written by Claude (10 is the homework's minimum)
- [ ] The labels checked by hand in `make label`: 0 of 30
- [x] Steps 1–2 (baseline and measurements): checkpoint 24.10; accuracy is against Claude's
  labels until they're checked
- [x] Prompt v2, the golden set's seniority and level rules: levels improved, seniority
  didn't ([prompts/CHANGELOG.md](prompts/CHANGELOG.md))
- [ ] Block 1's REPORT (docs/block1-report.md): due 27.10, still a template
- [x] Block 2: corpus of 62 files in 3 formats, ingestion, chunking, hybrid search with
  reranking and filters, answers with sources, evals in CI
- [ ] Block 2: the test set checked by a person, the judge calibrated on hand grades
  (deadline 13.11)
- [ ] Block 3: an agent on block 2's corpus

# structured_extraction

Turns messy Djinni texts (job postings and candidate CVs) into JSON that matches a schema, and
measures which model, prompt and sampling settings should do it in production. It compares a
24B hosted model with a 9B open-weight one small enough for a laptop, both through
[OpenRouter](https://openrouter.ai) (the 9B one can run on [Ollama](https://ollama.com)
instead), scored on a golden set of 30 labelled Python postings.

This is Homework 1 of the AI Engineering course ("Structured Extraction Service") and the first
part of the course project. A crawler that fills `data/` comes next, then RAG and an agent on
top of the extracted data.

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
make run       # every experiment in config.yaml, then the metrics
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
main.py              entry point: python main.py
config.yaml          the experiment: models, sampling, prompt versions
src/extraction/
  schemas.py         JobPosting, CandidateProfile, the portable JSON schema
  providers/         the Provider interface, OpenRouter, Ollama
  pipeline.py        one document: call, validate, repair once, retries
  runner.py          the experiment matrix and reuse of stored results
  evaluate.py        metrics and reports
  labelling.py       the labelling page (labelling.html) and its local server
  collect/           Djinni crawlers (live site, Wayback Machine), the one posting format
  cli.py             commands
prompts/             versioned prompts and CHANGELOG.md
data/                texts, scraped records, golden labels; postings/ (git-ignored)
results/             model outputs and metrics
tests/               offline tests with fake providers
REPORT.md            the comparison report
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
- [ ] Prompt v2 and REPORT.md: deadline 27.10

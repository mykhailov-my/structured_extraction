# structured_extraction

Turns messy Djinni texts (job postings and candidate CVs) into JSON that matches a schema, and
measures which model, prompt and sampling settings should do it in production. It compares a
cheap hosted model on [OpenRouter](https://openrouter.ai) with a local one on
[Ollama](https://ollama.com), scored on a hand-labelled golden set.

This is Homework 1 of the AI Engineering course ("Structured Extraction Service") and the first
part of the course project. A crawler that fills `data/` comes next, then RAG and an agent on
top of the extracted data.

## Quick start

You need [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 itself), an OpenRouter API
key, and Ollama for the local model.

```bash
make setup     # install dependencies, create .env from .env.example; put the key in .env
make models    # ollama pull qwen3.5:4b (~3.5 GB)
make data      # optional: crawl more job postings from djinni.co
make archive   # optional: Python postings 2019-2026 from the Wayback Machine (~1 h)
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
| `python main.py crawl-jobs` | Collects public job postings from djinni.co (see [Collecting data](#collecting-data)). |
| `python main.py crawl-archive` | Collects past years' postings from the Wayback Machine (see [Past years](#past-years-the-wayback-machine)). |
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

- **Schemas** (`src/extraction/schemas.py`): `JobPosting` (11 fields) and `CandidateProfile` (10)
  have enums (seniority, CEFR English level, work format, company type, currency), a nested
  `Salary` and lists of skills, locations and domains. Both share one vocabulary so jobs and
  candidates can be matched later. Names, contacts, links and employer names are not extracted.
- **One interface, two providers** (`src/extraction/providers/`). `OpenRouterProvider` uses the
  OpenAI-compatible API with `response_format: json_schema` in strict mode, and is routed only to
  upstreams that support it. `OllamaProvider` passes the schema as `format`, which makes decoding
  follow it. The pipeline only sees `Provider.complete()`.
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
| Accuracy | Mean over fields of the per-field score on golden documents. Enums and numbers need an exact match, and null = null counts as correct. Free text uses word-level F1. Lists use F1 over normalised items (`Node.js` = `nodejs`). Nested objects are scored per leaf (`salary.max_amount`). A failed document scores 0 on every field; provider errors are left out and counted under Errors. |
| p50, p95 | Seconds per document for the whole extraction, including the repair call and retry waits. The local model is loaded before the first document, so loading isn't counted. |
| $ / 1k docs | Mean cost per document × 1000, as billed by OpenRouter (`usage.cost`); 0 for the local model. |

## Collecting data

`python main.py crawl-jobs --count 20` (or `make data`) collects public job postings from
djinni.co. It takes the newest postings from the RSS feed, round-robin across categories so a
small sample stays varied; `--keywords Python,Java` limits it to those categories. Postings
already in `data/` are skipped. Each posting is stored twice:

- `data/scraped/job/<id>.json`: the page's parts as scraped. That is the URL and publication
  date, title, company, salary, skills, language requirements, the sidebar facts and the
  description.
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

### Past years: the Wayback Machine

Djinni keeps closed postings online but hides their date, so the live site can't tell when a
posting was written. `python main.py crawl-archive` (or `make archive`) reads past postings from
the [Wayback Machine](https://web.archive.org) instead: by default 50 Python postings a year,
2019–2026, into `data/archive/`. That takes about an hour, mostly spent waiting 5 s between
requests.

- **Which postings.** The archive's CDX index lists the captures of `djinni.co/jobs/<id>-<slug>/`
  pages whose slug contains the keyword (`--keyword python`), one query per year. The index is
  slow (about a minute a query), so its answers are cached in `.cache/wayback/`; delete the
  `.txt` files there to pick up newer captures. The fetched pages are cached there too
  (gzipped, about 8 KB each). After a parser fix, delete `data/archive/` and run again: the
  same postings are picked and re-parsed from the cache in seconds.
- **Dating.** A posting belongs to the year of its first capture if its id is above every id
  captured in the years before. Ids grow over time, so a lower id is an older posting archived
  late. When the page shows its posting date ("Job posted on 12 July 2019"), that date must fall
  in the same year. Closed postings show no date, and neither did any page from May 2024 to
  early 2025, so a posting from the last days of December can still be counted in the next
  year.
- **Spread.** Each year's picks are spaced evenly through its captures in time order, so they
  cover all of the year the archive has, not its first weeks. The archive has no Python
  postings before July in 2019 or before August in 2020, and months it captured often get more
  picks. A snapshot that fails, turns out older, or holds Djinni's "your IP address has been
  blocked" page instead of the posting is replaced by the next capture.
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
- **Records.** `data/archive/scraped/job/wayback-<year>-<id>.json` adds `snapshot` (the archived
  page), `captured_at`, `posted` (when the page shows it), `year`, `active` (false when the page
  marks the posting closed) and `layout`. The text goes to `data/archive/texts/job/`. The archive
  isn't part of the experiment, since nothing in it is labelled; it is there to compare
  requirements across years.

## Data and prompts

- `data/texts/<doc_type>/<doc_id>.txt` holds the raw texts and
  `data/golden/<doc_type>/<doc_id>.json` the hand labels; the rules are in
  [data/README.md](data/README.md). The `synthetic-*` files only show the format.
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
  collect/           Djinni crawlers (live site, Wayback Machine), contact scrubbing
  cli.py             commands
prompts/             versioned prompts and CHANGELOG.md
data/                texts, scraped records and golden labels; archive/ for past years
results/             model outputs and metrics
tests/               offline tests with fake providers
REPORT.md            the comparison report
```

## Roadmap

- [x] Boilerplate: schemas, both providers, validation with one repair, metrics
- [x] Crawler for Djinni job postings (CVs: no source that may be used)
- [x] Archive crawler: Python postings 2019–2026, for how requirements changed
- [x] 30+ texts
- [ ] 10+ golden labels
- [ ] Steps 1–2 (baseline and measurements): checkpoint 24.10
- [ ] Prompt v2 and REPORT.md: deadline 27.10

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
  cli.py             commands
prompts/             versioned prompts and CHANGELOG.md
data/                texts and golden labels
results/             model outputs and metrics
tests/               offline tests with fake providers
REPORT.md            the comparison report
```

## Roadmap

- [x] Boilerplate: schemas, both providers, validation with one repair, metrics
- [ ] Crawler for Djinni postings and profiles, writing to `data/texts/`
- [ ] 30+ texts with 10+ golden labels
- [ ] Steps 1–2 (baseline and measurements): checkpoint 24.10
- [ ] Prompt v2 and REPORT.md: deadline 27.10

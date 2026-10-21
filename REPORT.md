# Report

> Template. Fill it in once `make run` has produced `results/metrics.md`: the numbers come from
> there and the error examples from `results/mismatches.csv`.

## Setup

- **Data:** _N_ job postings and _M_ CVs from Djinni, _K_ of them hand-labelled (`data/README.md`).
- **Models:** `mistralai/mistral-small-3.2-24b-instruct` on OpenRouter; `qwen3.5:4b` on Ollama
  (_hardware_).
- **Prompts:** v1 (baseline), v2 (_what changed_); see `prompts/CHANGELOG.md`.
- **Sampling:** greedy (temperature 0, top_p 1) and nucleus (temperature 0.7, top_p 0.9).

## Results

_Paste the tables from `results/metrics.md`: model × prompt version × sampling, with validity,
accuracy, latency p50/p95 and cost per 1000 documents._

## Error analysis

_3–5 typical errors: what the model returned instead of what, and why._

| # | Run | Doc | Field | Expected | Got | Why |
|---|---|---|---|---|---|---|
| 1 | | | | | | |

## Choice for production

_One paragraph: which model, prompt and sampling, and the numbers behind the choice._

**The decision would change if:** _for example volume grows past N docs a day, the latency
budget drops below X s, or the data must not leave our machines._

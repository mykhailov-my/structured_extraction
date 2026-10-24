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

<!--
## v2 · YYYY-MM-DD · job

- Changed: ...
- Why: ... (runs and doc ids from results/mismatches.csv)
- Effect: accuracy 0.xx -> 0.yy, valid xx% -> yy% (results/metrics.md)
-->

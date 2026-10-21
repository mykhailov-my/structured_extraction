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

<!--
## v2 · YYYY-MM-DD · job

- Changed: ...
- Why: ... (runs and doc ids from results/mismatches.csv)
- Effect: accuracy 0.xx -> 0.yy, valid xx% -> yy% (results/metrics.md)
-->

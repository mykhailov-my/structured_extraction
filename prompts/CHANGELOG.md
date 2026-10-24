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

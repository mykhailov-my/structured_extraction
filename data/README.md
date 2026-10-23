# Data

```text
texts/<doc_type>/<doc_id>.txt     one raw text per file, UTF-8, as found (don't tidy it up)
scraped/<doc_type>/<doc_id>.json  the scraped record the text was made from, with its URL
golden/<doc_type>/<doc_id>.json   the hand-labelled answer for the text with the same doc_id
```

- `djinni-<job id>`: public job postings crawled from djinni.co by `python main.py crawl-jobs`.
- `postings/<year>.jsonl` (git-ignored, rebuilt by `python main.py build-postings`): every
  posting collected, live and from the Wayback Machine, one JSON object a line in the one
  format described in the README. Not labelled and not part of the experiment; it is for
  comparing requirements across years.
- `archive/`: an earlier sample, 50 Python postings a year for 2019–2026, in the same two
  folders as above (`wayback-<year>-<job id>`); `postings/` has them all too.
- `synthetic-001`: made up to show the format; delete them once real labels exist.
- There is no source of CVs yet: Djinni's candidate profiles may not be crawled.

## What the homework asks for

- At least 30 texts, at least 10 of them labelled in `golden/`.
- Genuinely messy: short and long, typos, missing fields, Ukrainian and English mixed.
- No personal data. Strip names, emails, phone numbers and profile links before committing:
  this repository is public.

## Labelling rules

- Write the JSON you want the model to return, with every field of the schema present.
- If the text doesn't say it, use `null` (or `[]` for a list). Don't guess.
- Values in English, skills under their usual names (`PostgreSQL`, not `postgress`).
- Salary is monthly unless the text says otherwise; "від 3500$" is
  `"min_amount": 3500, "max_amount": null`.
- English level as CEFR: Upper-Intermediate is `b2` (the full mapping is in
  `src/extraction/schemas.py`).
- `python main.py check` validates every label against the schema.

The field descriptions in `src/extraction/schemas.py` are the definitions, and the model reads
the same descriptions in its prompt.

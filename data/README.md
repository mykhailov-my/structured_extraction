# Data

```text
texts/<doc_type>/<doc_id>.txt     one raw text per file, UTF-8, as found (don't tidy it up)
golden/<doc_type>/<doc_id>.json   the hand-labelled answer for the text with the same doc_id
```

`job` holds job postings, `cv` candidate profiles. The `synthetic-001` files are made up to
show the format; delete them once real data is in.

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

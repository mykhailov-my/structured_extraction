# Data

```text
texts/job/<doc_id>.txt          the experiment's texts: 30 Djinni Python postings, 2025–2026
golden/job/<doc_id>.json        the hand label for the text with the same doc_id
golden/claude/job/<doc_id>.json Claude's labels of five texts, to compare with yours
golden/README.md                how to label (`make label`), with Claude's five as examples
scraped/job/<doc_id>.json       the record each text was made from, with its URL
```

- `djinni-<job id>`: public job postings from djinni.co. Ten were crawled live by
  `python main.py crawl-jobs`, and twenty picked from the 2025–2026 Python postings in
  `postings/` (see [golden/README.md](golden/README.md)). Texts are stored as found: don't tidy
  them up.
- `scraped/job/` also keeps the other 20 live postings, which aren't Python or repeat one
  in `texts/`. They have no text there, so the experiment skips them, while
  `build-postings` still reads them.
- `postings/<year>.jsonl` (git-ignored, rebuilt by `python main.py build-postings`): every
  posting collected, live and from the Wayback Machine, one JSON object a line in the one
  format described in the README. Not part of the experiment; it is for comparing
  requirements across years.
- `archive/`: an earlier sample, 50 Python postings a year for 2019–2026 (`wayback-<year>-<job
  id>`); `postings/` has them all too.
- `texts/cv/synthetic-001`: made up to show the CV format. There is no source of CVs: Djinni's
  candidate profiles may not be crawled.

## What the homework asks for

- At least 30 texts, at least 10 of them labelled in `golden/`.
- Genuinely messy: short and long, typos, missing fields, Ukrainian and English mixed.
- No personal data. Texts are scrubbed of emails, phone numbers, links and handles when
  collected, but names in free text aren't caught: read a text before committing it, as this
  repository is public.

The labelling rules are in [golden/README.md](golden/README.md). The field descriptions in
`src/extraction/schemas.py` are the definitions the models read in their prompt, and
`python main.py check` validates every label against them.

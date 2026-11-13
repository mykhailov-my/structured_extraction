# Evals

`make rag` (`python main.py rag all`) runs everything below and writes `evals/results/`. CI
runs it on every push and pull request (`.github/workflows/evals.yml`) in two jobs, and each
fails when a metric falls below its threshold in `rag.yaml`:
- **retrieval**, with no key: lint, unit tests, ingestion and retrieval from the committed
  caches (`make retrieval`, `rag all --offline`), against `recall_at_5`;
- **answers**, with the `OPENROUTER_API_KEY` secret: the whole run, against every threshold.

## Files

| File | What it holds | Who wrote it |
|---|---|---|
| `retrieval.jsonl` | 15+ questions, each with the passage that answers it: a document and a quote from it | Claude, checked by a person |
| `testset.jsonl` | 20+ questions with the expected answer, the documents a right answer cites, key facts, and the type: answerable, trap, unanswerable | Claude, checked by a person (`verified`) |
| `human_grades.jsonl` | answers of the system a person graded by hand: correct, partial or incorrect | a person (`python main.py rag grade`) |
| `results/retrieval.{json,md}` | recall@k and MRR for every search mode, both chunkings, with and without the chunks' contexts | `rag eval-retrieval` |
| `results/answers.json` | every answer with its sources, passages, scores, the judge's verdict and the claims checked | `rag eval` |
| `results/metrics.json` | the run's metrics, compared with the thresholds | `rag all` |
| `results/calibration.json` | the judge's verdicts on the hand-graded answers, and its agreement with the person | `rag calibrate` |

## Retrieval

A chunk is relevant to a question when it comes from the question's document and its own
text contains the question's quote. Relevance is defined by a quote, not a chunk id, so one
question scores either chunking. The context a model wrote for a chunk is searched but never
counts here: a context that repeats the quote doesn't make its chunk relevant. The questions
come in three kinds, since a search that only matches words fails the last two:

- **named**: the question names the company or the job;
- **cross-language**: a Ukrainian question about an English posting, or the other way round;
- **paraphrased**: neither the company nor the posting's own words.

recall@k is the share of questions with a relevant chunk among the first k. MRR is the mean of
1/rank of the first relevant chunk, counting 0 past rank 10. recall@20 is the reranker's pool:
what it can choose from, so a miss there is the first stage's, and a miss only at 5 is the
reranker's.

Every mode is measured on four indexes: structural or fixed-size chunks, each with and
without the chunks' contexts (README.md, "Contextual chunk headers").

## Answers

Each test question has a type:

- **answerable**: one posting or document answers it;
- **trap**: a look-alike posting, another company's, or an outdated version is in the corpus,
  and the answer must come from the right one;
- **unanswerable**: the corpus doesn't answer it, often though a near miss is there (Honeytech
  lists many benefits, but no car).

Deterministic checks:
- **source_accuracy**: an answerable or trap question's answer cites one of its `sources` and
  none of its `forbidden_sources`, such as a superseded version;
- **key_facts**: the share of `key_facts` found in the answer (each fact lists alternative
  spellings);
- **abstention**: the share of unanswerable questions answered "the documents don't say";
- **false_abstention**: the same for questions that do have an answer (lower is better).

LLM checks, by a judge from another model family than the one answering, and than the one
writing the chunks' contexts (`rag.yaml`):
- **judge_correct**: the answer against the expected one, scored correct 1, partial 0.5,
  incorrect 0. The rules are in `prompts/rag/judge_v1.yaml` and are the ones a person grades by;
- **faithfulness**: the answer split into claims, each checked against the passages the
  answer was given. It is the share supported, over answers that aren't abstentions.

The judge runs six answers at a time; a reply whose JSON doesn't parse is asked for once more.
An answer the judge still can't grade is left out of its means and counted: `judged` in
`metrics.json` says how many were graded.

## Calibration

A judge is only worth its agreement with a person. `python main.py rag grade` shows the
latest answers one by one, and the person's verdicts go to `human_grades.jsonl` together with
the graded text. `rag calibrate` has the judge grade those same texts. It reports agreement
on the three verdicts, agreement on correct vs not, Cohen's kappa and the confusion table.
Because it grades stored texts, calibration stays valid when the system's answers change, and
is rerun when the judge's prompt or model does.

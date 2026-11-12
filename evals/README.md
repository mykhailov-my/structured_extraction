# Evals

`make rag` (`python main.py rag all`) runs everything below and writes `evals/results/`. CI
runs the same on every push and pull request and fails when a metric falls below its threshold
in `rag.yaml`.

## Files

| File | What it holds | Who wrote it |
|---|---|---|
| `retrieval.jsonl` | 15+ questions, each with the passage that answers it: a document and a quote from it | Claude, checked by a person |
| `testset.jsonl` | 20+ questions with the expected answer, the documents a right answer cites, key facts, and the type: answerable, trap, unanswerable | Claude, checked by a person (`verified`) |
| `human_grades.jsonl` | answers of the system a person graded by hand: correct, partial or incorrect | a person (`python main.py rag grade`) |
| `results/retrieval.{json,md}` | recall@k and MRR for every search mode and both chunkings | `rag eval-retrieval` |
| `results/answers.json` | every answer with its sources, passages, scores, the judge's verdict and the claims checked | `rag eval` |
| `results/metrics.json` | the run's metrics, compared with the thresholds | `rag all` |
| `results/calibration.json` | the judge's verdicts on the hand-graded answers, and its agreement with the person | `rag calibrate` |

## Retrieval

A chunk is relevant to a question when it comes from the question's document and contains
its quote. Relevance is defined by a quote, not a chunk id, so one question scores either
chunking. The questions come in three kinds, since a search that only matches words fails
the last two:

- **named**: the question names the company or the job;
- **cross-language**: a Ukrainian question about an English posting, or the other way round;
- **paraphrased**: neither the company nor the posting's own words.

recall@k is the share of questions with a relevant chunk among the first k. MRR is the mean of
1/rank of the first relevant chunk, counting 0 past rank 10.

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

LLM checks, by a judge from another model family than the one answering (`rag.yaml`):
- **judge_correct**: the answer against the expected one, scored correct 1, partial 0.5,
  incorrect 0. The rules are in `prompts/rag/judge_v1.yaml` and are the ones a person grades by;
- **faithfulness**: the answer split into claims, each checked against the passages the
  answer was given. It is the share supported, over answers that aren't abstentions.

## Calibration

A judge is only worth its agreement with a person. `python main.py rag grade` shows the
latest answers one by one, and the person's verdicts go to `human_grades.jsonl` together with
the graded text. `rag calibrate` has the judge grade those same texts. It reports agreement
on the three verdicts, agreement on correct vs not, Cohen's kappa and the confusion table.
Because it grades stored texts, calibration stays valid when the system's answers change, and
is rerun when the judge's prompt or model does.

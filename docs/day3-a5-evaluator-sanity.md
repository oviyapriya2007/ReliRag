# Day 3 A5: evaluator sanity testing

Status: **complete, with open quality-review items** (see Known limitations).

Runner: `backend/sanity_evaluate_saved.py` (read-only; evaluation results go to a JSON report in
`data/eval_sanity/`, never to the database). Model `claude-sonnet-4-5`, pass threshold 0.80,
one Claude call per evaluation in both runs below.

## 1. Controlled negative cases

Report: `data/eval_sanity/sanity_20261011_132138.json` (`--negatives`). All 6 cases behaved as
expected; no integrity, quote-presence, semantic-support or expectation failures.

| Case | Faithfulness / answer rel. / context rel. | Failure type | Expected |
|---|---|---|---|
| `udp_guarantees_delivery` | 0.0 / 0.0 / 1.0 | unsupported_claim | fail |
| `mixed_true_false` | 0.5 / 0.5 / 1.0 | unsupported_claim | fail |
| `overreach` | 0.5 / 0.25 / 1.0 | unsupported_claim | fail |
| `off_topic` | 1.0 / 0.0 / 0.0 | missing_info | fail |
| `wrong_evidence` | 0.0 / 1.0 / 0.0 | unsupported_claim | fail |
| `grounded_control` | 1.0 / 1.0 / 1.0 | none (passed) | pass |

Every false claim was judged `unsupported`; every true claim was `supported` with a quote from
chunk 97. The earlier run `sanity_20261011_123258.json` failed all 6 cases with
`evaluator_error` because of the SDK `temperature` bug (see Known limitations).

## 2. Saved answers

Report: `data/eval_sanity/sanity_20261011_133257.json` (`--answers 7 20 12 15`). The report now
includes each retrieved chunk's text, so every verdict can be checked by hand.

| Answer | Question | Type | Faith. / ans. rel. / ctx. rel. | Outcome |
|---|---|---|---|---|
| 7 | What is the main difference between TCP and UDP? | normal | 1.0 / 1.0 / 1.0 | **passed** |
| 20 | wat is network security | normal (hedged) | 0.875 / 0.5 / 0.25 | failed, missing_info: **needs manual review** |
| 12 | What is the current password for my university Wi-Fi? | legacy refusal | 0.8 / 1.0 / 0.0 | failed, irrelevant_retrieval: **interpret separately** |
| 15 | Can I safely open this attachment? | legacy refusal | 1.0 / 0.75 / 0.25 | failed, missing_info: **interpret separately** |

- **Answer 7** passed: both claims supported by exact quotes from chunk 97.
- **Answer 20** needs manual review. 7 of 8 claims are supported. The VPN claim was marked
  unsupported only because Claude's quote did not match chunk 119, although chunk 119 does state
  that a VPN "creates a protected tunnel over an untrusted network" and that "Encryption protects
  traffic in transit". The claim "None of the passages explicitly define the term 'network
  security'" was marked supported using an unrelated quote. Context relevance 0.25 is debatable
  for a broad question.
- **Answers 12 and 15** are legacy refusals: saved with status `ANSWERED` and text starting
  `INSUFFICIENT_EVIDENCE` followed by an explanation. The evaluator scores that explanation, not
  whether refusing was correct, so their pass/fail and scores are not comparable with normal
  answers. Refusing was the right behaviour for both questions.

Not evaluated: saved answers 6, 9 (duplicate of 7 with Markdown), 13, 14, 16 and 18 (refusals
of the same pattern as 12 and 15).

## Known limitations

- **No temperature control.** The installed Anthropic SDK (1.11.0) has no `temperature` (or
  `top_p`/`top_k`) parameter in `messages.create()`. The evaluator's `temperature=0` was removed
  so calls succeed; evaluations now run with the API's default sampling, so scores may vary
  between runs. Each case above was run once.
- **Evaluator score quality needs further review.** Single run, one model, no human-labelled
  ground truth. Quote-presence checks confirm a quote exists in its chunk, not that it entails
  the claim.
- **Absence claims are inconsistent.** Claims such as "the passages do not contain X" cannot be
  backed by a quote: in answer 12 such a claim was downgraded to unsupported (lowering
  faithfulness), while in answer 15 two were accepted as supported with unrelated quotes.
- **Downgraded claims lose Claude's quote.** When a quote fails verification, the report keeps
  only the error, not the rejected quote, so the cause (e.g. answer 20's VPN claim) cannot be
  inspected.
- **Refusal handling needs review.** Legacy refusals are stored as `ANSWERED` and evaluated like
  normal answers; refusal correctness is not measured.
- **Incorrect-claim coverage** relies on the 5 scripted negative cases; Person B's deliberately
  wrong answers were not found in the repository.

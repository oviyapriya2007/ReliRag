// Must match the backend EVALUATOR_PASS_THRESHOLD (backend/app/config.py). Scores are on a 0-1 scale.
export const EVALUATOR_PASS_THRESHOLD = 0.7

export const EVALUATOR_ERROR = 'evaluator_error'

export const THRESHOLD_SCORES = [
  'faithfulness',
  'answer_relevance',
  'context_relevance',
]

export function thresholdPercent(threshold = EVALUATOR_PASS_THRESHOLD) {
  return Math.round(threshold * 100)
}

/** True if a 0-1 score meets the threshold, false if below, null if missing or invalid. */
export function scoreMeetsThreshold(value, threshold = EVALUATOR_PASS_THRESHOLD) {
  if (value == null || value === '' || typeof value === 'boolean') return null
  const score = Number(value)
  if (!Number.isFinite(score) || score < 0 || score > 1) return null
  return score >= threshold
}

/**
 * Per-score threshold results and an overall status for an evaluation:
 * 'passed', 'below_threshold', 'incomplete' (a score is missing or invalid),
 * 'evaluator_error', or 'not_evaluated'. `matchesVerdict` compares the status with the
 * stored `passed` verdict, or is null when there is nothing to compare.
 */
export function thresholdCheck(evaluation, threshold = EVALUATOR_PASS_THRESHOLD) {
  const scores = Object.fromEntries(
    THRESHOLD_SCORES.map((key) => [
      key,
      scoreMeetsThreshold(evaluation?.[key], threshold),
    ]),
  )
  const values = Object.values(scores)

  let status
  if (!evaluation) status = 'not_evaluated'
  else if (evaluation.failure_type === EVALUATOR_ERROR) status = EVALUATOR_ERROR
  else if (values.some((passed) => passed === null)) status = 'incomplete'
  else if (values.every(Boolean)) status = 'passed'
  else status = 'below_threshold'

  const decided = status === 'passed' || status === 'below_threshold'
  const matchesVerdict =
    decided && typeof evaluation.passed === 'boolean'
      ? evaluation.passed === (status === 'passed')
      : null

  return { scores, status, matchesVerdict }
}

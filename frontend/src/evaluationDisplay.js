// Display rules for stored evaluations: how an attempt's outcome, a claim's verification, and
// a self-contradiction are described. Only reads API data; nothing is recomputed.

export const CHECK_LABELS = {
  evidence: 'Evidence could not be verified in the retrieved passages',
  support: 'Evidence does not fully support the claim',
  citation: 'Missing, invalid, or unrelated citation',
  uncited: 'Factual statement without a valid citation',
  limitation: 'Labeled a limitation but asserts a fact',
  contradiction: "Contradicts the answer's own claim",
}

function isInsufficient(status) {
  return String(status ?? '').toUpperCase().includes('INSUFFICIENT')
}

/**
 * Outcome of one attempt: `kind` is 'passed', 'failed', 'evaluator_error', 'insufficient'
 * (no answer was generated or scored, so it was never evaluated), 'not_evaluated', or 'error'.
 */
export function attemptOutcome(attempt) {
  const evaluation = attempt?.evaluation
  if (!evaluation) {
    if (isInsufficient(attempt?.status)) {
      return { kind: 'insufficient', label: 'Not evaluated · insufficient evidence' }
    }
    if (String(attempt?.status ?? '').toUpperCase() === 'ERROR') {
      return { kind: 'error', label: 'Error' }
    }
    return { kind: 'not_evaluated', label: 'Not evaluated' }
  }
  if (evaluation.failure_type === 'evaluator_error') {
    return { kind: 'evaluator_error', label: 'Evaluator error' }
  }
  if (evaluation.passed === true) return { kind: 'passed', label: 'Passed' }
  if (evaluation.passed === false) return { kind: 'failed', label: 'Failed' }
  return { kind: 'not_evaluated', label: 'Not determined' }
}

function sameEvidence(chunkId, quote, otherChunkId, otherQuote) {
  const normalize = (text) => String(text ?? '').replace(/\s+/g, ' ').trim().toLowerCase()
  return chunkId === otherChunkId && normalize(quote) === normalize(otherQuote)
}

/**
 * How verification treated a claim: whether a deterministic check changed it, the check's
 * label and reason, Claude's original verdict when it differs, and Claude's original evidence
 * when it is not the verified evidence (it is never support).
 */
export function claimVerification(claim) {
  const check = claim?.check_name ?? null
  const originalVerdict = claim?.claude_verdict ?? null
  const hasOriginal =
    claim?.claude_evidence_chunk_id != null || Boolean(claim?.claude_evidence_quote)
  const originalEvidence =
    hasOriginal &&
    !sameEvidence(
      claim.claude_evidence_chunk_id,
      claim.claude_evidence_quote,
      claim.evidence_chunk_id ?? null,
      claim.evidence_quote,
    )
      ? { chunkId: claim.claude_evidence_chunk_id ?? null, quote: claim.claude_evidence_quote ?? null }
      : null
  return {
    downgraded: check !== null,
    check,
    checkLabel: check ? CHECK_LABELS[check] ?? check.replaceAll('_', ' ') : null,
    reason: claim?.evidence_error ?? null,
    originalVerdict:
      originalVerdict && originalVerdict !== claim?.verdict ? originalVerdict : null,
    originalEvidence,
  }
}

/** True if verification found that the answer contradicts itself. */
export function hasSelfContradiction(evaluation) {
  return (evaluation?.claims ?? []).some((claim) => claim?.check_name === 'contradiction')
}

/** Label of an attempt in comparisons, marking the reported one. */
export function attemptLabel(attempt, reportedAttemptNumber) {
  const number = attempt?.attempt_number
  const reported = number != null && Number(number) === Number(reportedAttemptNumber)
  const role = Number(number) === 1 ? 'initial' : 'correction'
  return `Attempt ${number ?? '?'} (${role})${reported ? ' · Reported' : ''}`
}

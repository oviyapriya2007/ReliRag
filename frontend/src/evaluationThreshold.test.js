import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

import {
  EVALUATOR_PASS_THRESHOLD,
  scoreMeetsThreshold,
  thresholdCheck,
  thresholdPercent,
} from './evaluationThreshold.js'

const SHARED = JSON.parse(
  readFileSync(new URL('./evaluationThreshold.cases.json', import.meta.url), 'utf8'),
)

function evaluation(faithfulness, answerRelevance, contextRelevance, extra = {}) {
  return {
    faithfulness,
    answer_relevance: answerRelevance,
    context_relevance: contextRelevance,
    ...extra,
  }
}

describe('Evaluator pass threshold', () => {
  it('is 70% on the 0-1 score scale', () => {
    assert.equal(EVALUATOR_PASS_THRESHOLD, 0.7)
    assert.equal(thresholdPercent(), 70)
    assert.equal(SHARED.threshold, EVALUATOR_PASS_THRESHOLD)
  })

  it('fails a score below 70%', () => {
    for (const value of [0.69, 0.6999999, 0.5, 0]) {
      assert.equal(scoreMeetsThreshold(value), false, String(value))
    }
  })

  it('passes a score of exactly 70%', () => {
    assert.equal(scoreMeetsThreshold(0.7), true)
    assert.equal(scoreMeetsThreshold(0.70), true)
    assert.equal(scoreMeetsThreshold(7 / 10), true)
    assert.equal(scoreMeetsThreshold(3.5 / 5), true)
  })

  it('passes a score above 70%', () => {
    for (const value of [0.7000001, 0.71, 0.75, 0.8, 1]) {
      assert.equal(scoreMeetsThreshold(value), true, String(value))
    }
  })

  it('treats missing, invalid, and non-finite scores as unavailable, never passing', () => {
    for (const value of [null, undefined, '', true, 'abc', NaN, Infinity, -Infinity, -0.1, 1.5, 70]) {
      assert.equal(scoreMeetsThreshold(value), null, String(value))
    }
  })
})

describe('thresholdCheck', () => {
  it('matches the backend verdict for every shared boundary case', () => {
    for (const item of SHARED.cases) {
      const check = thresholdCheck(
        evaluation(item.faithfulness, item.answer_relevance, item.context_relevance, {
          passed: item.passed,
          failure_type: item.failure_type,
        }),
      )
      assert.equal(check.status, item.passed ? 'passed' : 'below_threshold', item.name)
      assert.equal(check.matchesVerdict, true, item.name)
    }
  })

  it('reports each score individually', () => {
    const check = thresholdCheck(evaluation(0.7, 0.69, 0.71))
    assert.deepEqual(check.scores, {
      faithfulness: true,
      answer_relevance: false,
      context_relevance: true,
    })
    assert.equal(check.status, 'below_threshold')
  })

  it('never passes an evaluator_error, even with passing scores', () => {
    for (const scores of [[null, null, null], [1, 1, 1]]) {
      const check = thresholdCheck(
        evaluation(...scores, { passed: false, failure_type: 'evaluator_error' }),
      )
      assert.equal(check.status, 'evaluator_error')
      assert.equal(check.matchesVerdict, null)
    }
  })

  it('is incomplete, not passing, when a score is missing or non-finite', () => {
    for (const bad of [null, NaN, Infinity]) {
      const check = thresholdCheck(evaluation(1, bad, 1, { passed: true, failure_type: null }))
      assert.equal(check.status, 'incomplete')
      assert.equal(check.matchesVerdict, null)
    }
  })

  it('is not_evaluated when there is no evaluation', () => {
    assert.equal(thresholdCheck(null).status, 'not_evaluated')
    assert.equal(thresholdCheck(undefined).matchesVerdict, null)
  })

  it('flags a stored verdict recorded under a different threshold', () => {
    const check = thresholdCheck(
      evaluation(0.75, 0.75, 0.75, { passed: false, failure_type: 'unsupported_claim' }),
    )
    assert.equal(check.status, 'passed')
    assert.equal(check.matchesVerdict, false)
  })
})

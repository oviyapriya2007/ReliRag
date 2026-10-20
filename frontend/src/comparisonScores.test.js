import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { comparisonScores, SINGLE_MODE_MESSAGE } from './comparisonScores.js'

// Shape of a real GET /query/{id} response: one mode, no comparison fields.
const singleModeQuery = {
  query_id: 7,
  question: 'Any question',
  mode: 'reli',
  status: 'ANSWERED',
  final_answer: 'An answer [1].',
  final_attempt_number: 1,
  selection_reason: null,
  attempts: [
    {
      attempt_number: 1,
      evaluation: { faithfulness: 0.9, answer_relevance: 0.8, context_relevance: 0.7 },
    },
  ],
}

function byKey(result) {
  return Object.fromEntries(result.metrics.map(({ key, basic, reli }) => [key, { basic, reli }]))
}

describe('comparisonScores: no comparison data', () => {
  it('is unavailable for a single-mode query response', () => {
    assert.equal(comparisonScores(singleModeQuery).available, false)
  })

  it("does not take the query's own evaluation scores as comparison scores", () => {
    for (const { basic, reli } of comparisonScores(singleModeQuery).metrics) {
      assert.equal(basic, null)
      assert.equal(reli, null)
    }
  })

  it('is unavailable for a missing query', () => {
    assert.equal(comparisonScores(null).available, false)
    assert.equal(comparisonScores(undefined).available, false)
  })

  it('is unavailable when comparison fields hold no usable score', () => {
    for (const comparison of [
      null,
      {},
      { faithfulness: {} },
      { basic_rag: { faithfulness: null }, reli_rag: { answer_relevance: '' } },
      { faithfulness: { basic_rag: 'abc', reli_rag: NaN } },
    ]) {
      assert.equal(comparisonScores({ comparison }).available, false, JSON.stringify(comparison))
    }
  })

  it('tells the user to use the Comparison Lab', () => {
    assert.equal(
      SINGLE_MODE_MESSAGE,
      'This query was evaluated in a single mode. Run it in the Comparison Lab to compare Basic RAG and Attest.',
    )
  })
})

describe('comparisonScores: genuine comparison data', () => {
  it('reads metric-first scores', () => {
    const result = comparisonScores({
      comparison: {
        faithfulness: { basic_rag: 0.6, reli_rag: 0.9 },
        answer_relevance: { basic_rag: 0.5, reli_rag: 0.8 },
        context_relevance: { basic_rag: 0.4, reli_rag: 0.7 },
      },
    })
    assert.equal(result.available, true)
    assert.deepEqual(byKey(result), {
      faithfulness: { basic: 0.6, reli: 0.9 },
      answer_relevance: { basic: 0.5, reli: 0.8 },
      context_relevance: { basic: 0.4, reli: 0.7 },
    })
  })

  it('reads system-first scores', () => {
    const result = comparisonScores({
      comparison: {
        basic_rag: { faithfulness: 0.6, answer_relevance: 0.5, context_relevance: 0.4 },
        reli_rag: { faithfulness: 0.9, answer_relevance: 0.8, context_relevance: 0.7 },
      },
    })
    assert.equal(result.available, true)
    assert.deepEqual(byKey(result).faithfulness, { basic: 0.6, reli: 0.9 })
  })

  it('reads comparison_results and comparison_data as fallbacks', () => {
    for (const field of ['comparison_results', 'comparison_data']) {
      const result = comparisonScores({ [field]: { faithfulness: { basic_rag: 0.5, reli_rag: 0.75 } } })
      assert.equal(result.available, true, field)
      assert.deepEqual(byKey(result).faithfulness, { basic: 0.5, reli: 0.75 }, field)
    }
  })

  it('keeps zero as a real score', () => {
    const result = comparisonScores({ comparison: { faithfulness: { basic_rag: 0, reli_rag: 0 } } })
    assert.equal(result.available, true)
    assert.deepEqual(byKey(result).faithfulness, { basic: 0, reli: 0 })
  })

  it('stays available with partial scores, leaving only the missing ones empty', () => {
    const result = comparisonScores({ comparison: { faithfulness: { reli_rag: 0.9 } } })
    assert.equal(result.available, true)
    assert.deepEqual(byKey(result), {
      faithfulness: { basic: null, reli: 0.9 },
      answer_relevance: { basic: null, reli: null },
      context_relevance: { basic: null, reli: null },
    })
  })

  it('lists the three metrics in display order', () => {
    assert.deepEqual(
      comparisonScores(null).metrics.map(({ title, key }) => [title, key]),
      [
        ['Faithfulness', 'faithfulness'],
        ['Answer relevance', 'answer_relevance'],
        ['Context relevance', 'context_relevance'],
      ],
    )
  })
})

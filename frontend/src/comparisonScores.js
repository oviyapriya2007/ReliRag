export const COMPARISON_METRICS = [
  ['Faithfulness', 'faithfulness'],
  ['Answer relevance', 'answer_relevance'],
  ['Context relevance', 'context_relevance'],
]

export const COMPARISON_SYSTEMS = ['basic_rag', 'reli_rag']

export const SINGLE_MODE_MESSAGE =
  'This query was evaluated in a single mode. Run it in the Comparison Lab to compare Basic RAG and Attest.'

function isScore(value) {
  return value != null && value !== '' && Number.isFinite(Number(value))
}

/**
 * Basic RAG vs RELI-RAG scores attached to a query, read from `comparison`,
 * `comparison_results`, or `comparison_data`, keyed either metric-first or system-first.
 * `available` is false when no metric has a usable score for either system, so the caller
 * can explain that no comparison was run instead of showing empty scores.
 */
export function comparisonScores(query) {
  const comparison =
    query?.comparison ??
    query?.comparison_results ??
    query?.comparison_data ??
    null

  const metrics = COMPARISON_METRICS.map(([title, key]) => {
    const [basic, reli] = COMPARISON_SYSTEMS.map(
      (system) => comparison?.[key]?.[system] ?? comparison?.[system]?.[key] ?? null,
    )
    return { title, key, basic, reli }
  })

  const available = metrics.some(({ basic, reli }) => isScore(basic) || isScore(reli))

  return { available, metrics }
}

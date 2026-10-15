import { useEffect, useState } from 'react'
import { USE_MOCK, getAnalyticsSummary } from '../../api/client'

const colors = {
  purple: '#554188',
  blue: '#738fbd',
  pink: '#db88a4',
  lightBlue: '#a8c3d4',
  border: '#E5DBE6',
  background: '#F5F5F4',
}

function formatPercent(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return 'N/A'
  }

  return `${(value * 100).toFixed(1)}%`
}

function formatScore(value) {
  return formatPercent(value)
}

function formatLatency(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return 'N/A'
  }

  return `${(value / 1000).toFixed(2)} s`
}

function StatCard({ label, value, note, color }) {
  return (
    <article className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm">
      <p className="text-sm text-gray-500">{label}</p>
      <p
        className="mt-3 text-3xl font-bold"
        style={{ color: color || colors.purple }}
      >
        {value}
      </p>
      <p className="mt-2 text-xs text-gray-500">{note}</p>
    </article>
  )
}

function ScoreBar({ label, value, color }) {
  const available =
    value !== null &&
    value !== undefined &&
    Number.isFinite(value)

  const percentage = available
    ? Math.max(0, Math.min(100, value * 100))
    : 0

  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className="text-sm font-medium text-gray-700">{label}</span>
        <span className="text-sm font-bold text-gray-800">
          {formatScore(value)}
        </span>
      </div>

      <div
        className="h-3 overflow-hidden rounded-full bg-gray-100"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={available ? percentage : undefined}
      >
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${percentage}%`,
            backgroundColor: color,
          }}
        />
      </div>
    </div>
  )
}

function ScorePanel({ title, scores, accent }) {
  return (
    <section className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm">
      <h2 className="text-lg font-bold text-gray-800">{title}</h2>

      <p className="mt-1 text-sm text-gray-500">
        {scores.evaluations} usable evaluations
      </p>

      <div className="mt-6 space-y-5">
        <ScoreBar
          label="Faithfulness"
          value={scores.faithfulness}
          color={accent}
        />
        <ScoreBar
          label="Answer relevance"
          value={scores.answer_relevance}
          color={colors.pink}
        />
        <ScoreBar
          label="Context relevance"
          value={scores.context_relevance}
          color={colors.lightBlue}
        />
        <ScoreBar
          label="Overall score"
          value={scores.overall}
          color={colors.purple}
        />
      </div>
    </section>
  )
}

function Analytics() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [benchmarkRunId, setBenchmarkRunId] = useState('')
  const [topDocuments, setTopDocuments] = useState('5')

  async function loadAnalytics(filters = {}) {
    const runId = filters.benchmarkRunId ?? ''
    const documentLimit = Number(filters.topDocuments ?? 5)

    setLoading(true)
    setError('')

    try {
      const result = await getAnalyticsSummary({
        benchmarkRunId: runId,
        topDocuments: documentLimit,
      })

      setData(result)
    } catch (err) {
      setError(err.message || 'Failed to load analytics.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!USE_MOCK) {
      loadAnalytics()
    }
  }, [])

  if (USE_MOCK) {
    return (
      <div className="space-y-4">
        <header>
          <p className="text-sm font-medium" style={{ color: '#7080DA' }}>
            PERFORMANCE OVERVIEW
          </p>
          <h1 className="mt-1 text-3xl font-bold" style={{ color: colors.purple }}>
            Analytics &amp; History
          </h1>
        </header>

        <div className="rounded-xl border border-[#E5DBE6] bg-white p-5 text-sm text-gray-700">
          Live analytics requires mock mode to be disabled.
          Set <code>VITE_USE_MOCK=false</code> in your frontend environment
          configuration and restart the Vite development server.
        </div>
      </div>
    )
  }

  const basic = data?.by_mode?.basic
  const reli = data?.by_mode?.reli
  const corrections = data?.corrections

  return (
    <div className="space-y-6">
      <header>
        <p className="text-sm font-medium" style={{ color: '#7080DA' }}>
          PERFORMANCE OVERVIEW
        </p>
        <h1 className="mt-1 text-3xl font-bold" style={{ color: colors.purple }}>
          Analytics &amp; History
        </h1>
        <p className="mt-2 text-sm text-gray-500">
          Monitor real evaluation results, correction outcomes, model quality,
          latency, and document usage.
        </p>
      </header>

      <section className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm">
        <h2 className="text-lg font-bold text-gray-800">
          Analytics filters
        </h2>

        <p className="mt-1 text-sm text-gray-500">
          Optionally filter by benchmark run and choose how many top documents
          to display.
        </p>

        <form
          className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3"
          onSubmit={(event) => {
            event.preventDefault()
            loadAnalytics({ benchmarkRunId, topDocuments })
          }}
        >
          <input
            type="text"
            value={benchmarkRunId}
            onChange={(event) => setBenchmarkRunId(event.target.value)}
            placeholder="Benchmark run ID (optional)"
            aria-label="Benchmark run ID"
            maxLength={64}
            className="min-w-0 rounded-xl border border-[#E5DBE6] px-4 py-3 text-sm outline-none focus:border-[#7080DA]"
          />

          <select
            value={topDocuments}
            onChange={(event) => setTopDocuments(event.target.value)}
            aria-label="Number of top documents"
            className="min-w-0 rounded-xl border border-[#E5DBE6] bg-white px-4 py-3 text-sm"
          >
            <option value="5">Top 5 documents</option>
            <option value="10">Top 10 documents</option>
            <option value="20">Top 20 documents</option>
            <option value="50">Top 50 documents</option>
          </select>

          <button
            type="submit"
            disabled={loading}
            className="rounded-xl bg-[#554188] px-4 py-3 text-sm font-semibold text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading ? 'Loading...' : 'Apply filters'}
          </button>
        </form>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-gray-500">
            {data?.benchmark_run_id
              ? `Benchmark: ${data.benchmark_run_id}`
              : 'Showing all available benchmark runs'}
          </p>

          <button
            type="button"
            disabled={loading}
            onClick={() => {
              setBenchmarkRunId('')
              setTopDocuments('5')
              loadAnalytics({
                benchmarkRunId: '',
                topDocuments: '5',
              })
            }}
            className="text-sm font-semibold text-[#554188] hover:underline disabled:opacity-50"
          >
            Reset filters
          </button>
        </div>
      </section>

      {error && (
        <div
          role="alert"
          className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"
        >
          <p className="font-semibold">Unable to load analytics</p>
          <p className="mt-1 break-words">{error}</p>
          <button
            type="button"
            onClick={() => loadAnalytics({ benchmarkRunId, topDocuments })}
            className="mt-3 rounded-lg border border-red-300 px-3 py-2 font-semibold hover:bg-red-100"
          >
            Try again
          </button>
        </div>
      )}

      {loading && !data && (
        <div className="rounded-2xl border border-[#E5DBE6] bg-white p-10 text-center">
          <p className="font-semibold text-gray-700">
            Loading live analytics...
          </p>
          <p className="mt-2 text-sm text-gray-500">
            Fetching statistics from the RELI-RAG backend.
          </p>
        </div>
      )}

      {!data && !loading && !error && (
        <div className="rounded-2xl border border-[#E5DBE6] bg-white p-10 text-center">
          <p className="text-sm text-gray-600">
            No analytics data is available yet.
          </p>
        </div>
      )}

      {data && (
        <>
          <div className="rounded-xl border border-[#E5DBE6] bg-white px-4 py-3 text-sm text-gray-600">
            <span className="font-semibold text-[#554188]">Live backend data:</span>{' '}
            These metrics come from the analytics API. Only usable evaluations
            contribute to score averages; counts and score denominators can differ.
            {loading && ' Refreshing data...'}
          </div>

          <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="Total questions"
              value={data.total_questions}
              note="Queries recorded in the selected scope"
              color={colors.purple}
            />

            <StatCard
              label="First-pass success"
              value={formatPercent(data.first_pass.rate)}
              note={`${data.first_pass.count} passed out of ${data.first_pass.total} usable first-attempt evaluations`}
              color={colors.blue}
            />

            <StatCard
              label="Insufficient evidence"
              value={data.insufficient_evidence}
              note="Queries with insufficient evidence status"
              color="#b7791f"
            />

            <StatCard
              label="Unsupported claims"
              value={data.unsupported_claims}
              note="Unsupported claims in recorded evaluations"
              color="#c24141"
            />
          </section>

          <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <ScorePanel
              title="Basic RAG — Final scores"
              scores={basic.final_scores}
              accent={colors.blue}
            />

            <ScorePanel
              title="RELI-RAG — Final scores"
              scores={reli.final_scores}
              accent={colors.pink}
            />
          </section>

          <section className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm">
            <h2 className="text-lg font-bold text-gray-800">
              First-pass performance by mode
            </h2>
            <p className="mt-1 text-sm text-gray-500">
              The rate uses queries with a usable first-attempt evaluation.
            </p>

            <div className="mt-5 grid grid-cols-1 gap-5 md:grid-cols-2">
              {[{ name: 'Basic RAG', mode: basic }, { name: 'RELI-RAG', mode: reli }].map(
                ({ name, mode }) => (
                  <div
                    key={name}
                    className="rounded-xl bg-[#F5F5F4] p-4"
                  >
                    <p className="text-sm font-semibold text-gray-700">
                      {name}
                    </p>
                    <p className="mt-2 text-2xl font-bold text-[#554188]">
                      {formatPercent(mode.first_pass.rate)}
                    </p>
                    <p className="mt-1 text-xs text-gray-500">
                      {mode.first_pass.count} passed / {mode.first_pass.total} evaluated
                      first attempts
                    </p>
                    <p className="mt-3 text-sm text-gray-600">
                      Questions recorded: {mode.questions}
                    </p>
                    <p className="mt-1 text-sm text-gray-600">
                      Insufficient evidence: {mode.insufficient_evidence}
                    </p>
                  </div>
                ),
              )}
            </div>
          </section>

          <section className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm">
            <h2 className="text-lg font-bold text-gray-800">
              Correction performance
            </h2>
            <p className="mt-1 text-sm text-gray-500">
              Correction metrics are based on RELI-RAG queries and stored
              correction attempts.
            </p>

            <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard
                label="Eligible for correction"
                value={corrections.eligible}
                note="First attempts that failed a usable evaluation"
                color={colors.purple}
              />
              <StatCard
                label="Corrections triggered"
                value={corrections.triggered}
                note="Queries with a stored second attempt"
                color={colors.blue}
              />
              <StatCard
                label="Successful corrections"
                value={corrections.successful}
                note="Second attempt passed its evaluation"
                color="#27845a"
              />
              <StatCard
                label="Correction success rate"
                value={formatPercent(corrections.success_rate)}
                note="Successful corrections / triggered corrections"
                color={colors.pink}
              />
            </div>

            <p className="mt-4 text-sm text-gray-500">
              Correction trigger rate: {formatPercent(corrections.trigger_rate)}
              {' · '}
              Failed after correction: {corrections.failed_after_correction}
            </p>
          </section>

          <section className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm">
            <h2 className="text-lg font-bold text-gray-800">
              Average latency
            </h2>
            <p className="mt-1 text-sm text-gray-500">
              Average recorded Claude generation and evaluation times per query.
              Retrieval and query-rewriting time are not included in this metric.
            </p>

            <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-3">
              {[
                {
                  label: 'Generation',
                  value: data.by_mode.basic.latency.avg_generation_ms,
                  note: 'Basic RAG',
                },
                {
                  label: 'Evaluation',
                  value: data.by_mode.basic.latency.avg_evaluation_ms,
                  note: 'Basic RAG',
                },
                {
                  label: 'Total recorded',
                  value: data.by_mode.basic.latency.avg_total_ms,
                  note: 'Basic RAG',
                },
              ].map((metric) => (
                <div
                  key={metric.label}
                  className="rounded-xl bg-[#F5F5F4] p-4"
                >
                  <p className="text-sm text-gray-500">{metric.label}</p>
                  <p className="mt-2 text-2xl font-bold text-[#554188]">
                    {formatLatency(metric.value)}
                  </p>
                  <p className="mt-1 text-xs text-gray-500">{metric.note}</p>
                </div>
              ))}
            </div>

            <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
              {[
                {
                  label: 'RELI-RAG generation',
                  value: reli.latency.avg_generation_ms,
                },
                {
                  label: 'RELI-RAG evaluation',
                  value: reli.latency.avg_evaluation_ms,
                },
                {
                  label: 'RELI-RAG total recorded',
                  value: reli.latency.avg_total_ms,
                },
              ].map((metric) => (
                <div
                  key={metric.label}
                  className="rounded-xl border border-[#E5DBE6] p-4"
                >
                  <p className="text-sm text-gray-500">{metric.label}</p>
                  <p className="mt-2 text-xl font-bold text-[#554188]">
                    {formatLatency(metric.value)}
                  </p>
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm">
            <h2 className="text-lg font-bold text-gray-800">
              Top retrieved documents
            </h2>
            <p className="mt-1 text-sm text-gray-500">
              Documents ranked by retrieval-log count in the selected scope.
            </p>

            {data.top_documents.length === 0 ? (
              <div className="mt-5 rounded-xl bg-[#F5F5F4] p-6 text-center">
                <p className="font-semibold text-gray-700">
                  No document usage found
                </p>
                <p className="mt-1 text-sm text-gray-500">
                  No matching document retrievals were recorded for this scope.
                </p>
              </div>
            ) : (
              <div className="mt-5 space-y-3">
                {data.top_documents.map((document, index) => (
                  <article
                    key={document.document_id}
                    className="flex flex-col gap-3 rounded-xl border border-[#E5DBE6] p-4 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-[#7080DA]">
                        DOCUMENT #{index + 1}
                      </p>
                      <h3 className="mt-1 break-words text-sm font-semibold text-gray-800">
                        {document.filename}
                      </h3>
                      <p className="mt-1 text-xs text-gray-500">
                        Document ID: {document.document_id}
                      </p>
                    </div>

                    <div className="flex gap-6">
                      <div>
                        <p className="text-xs text-gray-500">Retrievals</p>
                        <p className="mt-1 font-bold text-[#554188]">
                          {document.retrievals}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500">Queries</p>
                        <p className="mt-1 font-bold text-[#554188]">
                          {document.queries}
                        </p>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}

export default Analytics

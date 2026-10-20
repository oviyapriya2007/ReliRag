import { useEffect, useState } from 'react'
import { USE_MOCK, getAnalyticsSummary } from '../../api/client'

const colors = {
  purple: '#554188',
  blue: '#738fbd',
  pink: '#db88a4',
  lightBlue: '#a8c3d4',
  border: '#E5DBE6',
  background: '#F5F5F4',
  green: '#91B9A7',
  muted: '#78716C',
}

function formatPercent(value) {
  if (
    value === null ||
    value === undefined ||
    value === '' ||
    !Number.isFinite(Number(value))
  ) {
    return 'N/A'
  }

  return `${(Number(value) * 100).toFixed(1)}%`
}

function formatScore(value) {
  return formatPercent(value)
}

function formatLatency(value) {
  if (
    value === null ||
    value === undefined ||
    value === '' ||
    !Number.isFinite(Number(value))
  ) {
    return 'N/A'
  }

  return `${(Number(value) / 1000).toFixed(2)} s`
}

function formatCount(value) {
  if (
    value === null ||
    value === undefined ||
    value === '' ||
    !Number.isFinite(Number(value))
  ) {
    return 'N/A'
  }

  return Number(value).toLocaleString()
}

function getObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value
    : {}
}

function getArray(value) {
  return Array.isArray(value) ? value : []
}

function StatCard({ label, value, note, color, icon, tint }) {
  return (
    <article
      className="min-w-0 rounded-2xl border bg-white p-5 transition duration-200 hover:-translate-y-0.5 hover:shadow-md"
      style={{ borderColor: colors.border }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-stone-500">{label}</p>
          <p
            className="mt-3 break-words text-3xl font-bold tracking-tight"
            style={{ color: color || colors.purple }}
          >
            {value ?? 'N/A'}
          </p>
        </div>

        <div
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl text-lg"
          style={{
            color: color || colors.purple,
            backgroundColor: tint || '#F5F0FA',
          }}
          aria-hidden="true"
        >
          {icon || '◈'}
        </div>
      </div>

      <p className="mt-3 text-xs leading-5 text-stone-500">{note}</p>
    </article>
  )
}

function ScoreBar({ label, value, color }) {
  const available =
    value !== null &&
    value !== undefined &&
    value !== '' &&
    Number.isFinite(Number(value))

  const numericValue = available ? Number(value) : 0
  const percentage = available
    ? Math.max(0, Math.min(100, numericValue * 100))
    : 0

  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className="text-sm font-medium text-stone-600">{label}</span>
        <span className="text-sm font-bold text-stone-800">
          {formatScore(value)}
        </span>
      </div>

      <div
        className="h-2.5 overflow-hidden rounded-full bg-stone-100"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={available ? percentage : undefined}
      >
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{
            width: `${percentage}%`,
            backgroundColor: color,
          }}
        />
      </div>
    </div>
  )
}

function ScorePanel({ title, scores, accent, tint }) {
  const safeScores = getObject(scores)

  return (
    <section
      className="rounded-2xl border bg-white p-5 sm:p-6"
      style={{ borderColor: colors.border }}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-bold" style={{ color: colors.purple }}>
            {title}
          </h3>
          <p className="mt-1 text-sm text-stone-500">
            {formatCount(safeScores.evaluations)} usable evaluations
          </p>
        </div>

        <span
          className="h-3 w-3 shrink-0 rounded-full"
          style={{ backgroundColor: accent }}
        />
      </div>

      <div className="mt-6 space-y-5">
        <ScoreBar
          label="Faithfulness"
          value={safeScores.faithfulness}
          color={accent}
        />

        <ScoreBar
          label="Answer relevance"
          value={safeScores.answer_relevance}
          color={colors.pink}
        />

        <ScoreBar
          label="Context relevance"
          value={safeScores.context_relevance}
          color={colors.lightBlue}
        />

        <ScoreBar
          label="Overall score"
          value={safeScores.overall}
          color={colors.purple}
        />
      </div>

      <div
        className="mt-5 rounded-xl px-3 py-2 text-xs leading-5 text-stone-500"
        style={{ backgroundColor: tint }}
      >
        Average scores from usable evaluations only.
      </div>
    </section>
  )
}

function Section({ title, description, children, icon }) {
  return (
    <section
      className="rounded-2xl border bg-white p-5 shadow-sm sm:p-6"
      style={{ borderColor: colors.border }}
    >
      <div className="flex items-start gap-3">
        {icon && (
          <div
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-base"
            style={{ backgroundColor: '#F5F0FA', color: colors.purple }}
            aria-hidden="true"
          >
            {icon}
          </div>
        )}

        <div className="min-w-0">
          <h2 className="text-lg font-bold text-stone-800">{title}</h2>
          {description && (
            <p className="mt-1 text-sm leading-6 text-stone-500">
              {description}
            </p>
          )}
        </div>
      </div>

      {children}
    </section>
  )
}

function Analytics() {
  const [data, setData] = useState(null)
  // The first load starts on mount (outside mock mode), so it begins as loading.
  const [loading, setLoading] = useState(!USE_MOCK)
  const [error, setError] = useState('')
  const [benchmarkRunId, setBenchmarkRunId] = useState('')
  const [topDocuments, setTopDocuments] = useState('5')

  function fetchAnalytics(filters = {}) {
    return getAnalyticsSummary({
      benchmarkRunId: filters.benchmarkRunId ?? '',
      topDocuments: Number(filters.topDocuments ?? 5),
    })
      .then((result) => setData(getObject(result)))
      .catch((err) => setError(err?.message || 'Failed to load analytics.'))
      .finally(() => setLoading(false))
  }

  function loadAnalytics(filters = {}) {
    setLoading(true)
    setError('')
    return fetchAnalytics(filters)
  }

  useEffect(() => {
    if (!USE_MOCK) {
      fetchAnalytics()
    }
  }, [])

  if (USE_MOCK) {
    return (
      <div className="space-y-6">
        <header
          className="rounded-3xl border p-6 sm:p-8"
          style={{
            borderColor: colors.border,
            background:
              'linear-gradient(120deg, #F5F0FA 0%, #F1F6FC 55%, #FDF1F5 100%)',
          }}
        >
          <p className="text-xs font-bold tracking-widest" style={{ color: colors.blue }}>
            PERFORMANCE OVERVIEW
          </p>
          <h1 className="mt-3 text-3xl font-bold sm:text-4xl" style={{ color: colors.purple }}>
            Analytics &amp; History
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-7 text-stone-600">
            Explore evaluation quality, correction outcomes, model latency,
            and document usage across recorded Attest queries.
          </p>
        </header>

        <section
          className="rounded-2xl border bg-white p-5 sm:p-6"
          style={{ borderColor: colors.border }}
        >
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-50 text-lg">
              ⚙
            </div>
            <div>
              <h2 className="font-bold text-stone-800">
                Live analytics is disabled
              </h2>
              <p className="mt-2 text-sm leading-7 text-stone-600">
                The frontend is currently running in mock mode. To load
                analytics from your backend, set{' '}
                <code className="rounded-md bg-stone-100 px-1.5 py-1 text-xs">
                  VITE_USE_MOCK=false
                </code>{' '}
                in the frontend environment configuration, then restart the
                Vite development server.
              </p>
            </div>
          </div>
        </section>
      </div>
    )
  }

  const safeData = getObject(data)
  const byMode = getObject(safeData.by_mode)
  const basic = getObject(byMode.basic)
  const reli = getObject(byMode.reli)
  const corrections = getObject(safeData.corrections)
  const basicScores = getObject(basic.final_scores)
  const reliScores = getObject(reli.final_scores)
  const basicLatency = getObject(basic.latency)
  const reliLatency = getObject(reli.latency)
  const firstPass = getObject(safeData.first_pass)
  const topDocumentsList = getArray(safeData.top_documents)

  return (
    <div className="space-y-6 pb-6">
      <header
        className="overflow-hidden rounded-3xl border p-6 sm:p-8"
        style={{
          borderColor: colors.border,
          background:
            'linear-gradient(120deg, #F5F0FA 0%, #F1F6FC 55%, #FDF1F5 100%)',
        }}
      >
        <div className="flex flex-wrap items-center gap-2">
          <span
            className="rounded-full bg-white/80 px-3 py-1.5 text-xs font-bold tracking-wider"
            style={{ color: colors.blue }}
          >
            Attest WORKSPACE
          </span>

          <span className="rounded-full border border-white bg-white/70 px-3 py-1.5 text-xs font-semibold text-stone-600">
            Live backend
          </span>
        </div>

        <h1 className="mt-4 text-3xl font-bold sm:text-4xl" style={{ color: colors.purple }}>
          Analytics &amp; History
        </h1>

        <p className="mt-3 max-w-3xl text-sm leading-7 text-stone-600 sm:text-base">
          Understand model quality, first-pass performance, correction
          effectiveness, processing latency, and document retrieval activity
          using recorded backend statistics.
        </p>

        <div className="mt-5 flex flex-wrap items-center gap-3 text-xs text-stone-500">
          <span className="inline-flex items-center gap-2 rounded-full bg-white/80 px-3 py-2">
            <span className="h-2 w-2 rounded-full bg-emerald-400" />
            API-backed metrics
          </span>
          <span className="rounded-full bg-white/80 px-3 py-2">
            Optional benchmark filtering
          </span>
          <span className="rounded-full bg-white/80 px-3 py-2">
            Evaluation history
          </span>
        </div>
      </header>

      <Section
        title="Analytics filters"
        description="Narrow the statistics to a benchmark run and choose how many frequently retrieved documents to display."
        icon="⌕"
      >
        <form
          className="mt-5 grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_200px_auto]"
          onSubmit={(event) => {
            event.preventDefault()
            loadAnalytics({ benchmarkRunId, topDocuments })
          }}
        >
          <div>
            <label
              htmlFor="analytics-benchmark"
              className="mb-2 block text-sm font-medium text-stone-700"
            >
              Benchmark run ID
            </label>
            <input
              id="analytics-benchmark"
              type="text"
              value={benchmarkRunId}
              onChange={(event) => setBenchmarkRunId(event.target.value)}
              placeholder="Optional benchmark run ID"
              maxLength={64}
              className="w-full min-w-0 rounded-xl border bg-white px-4 py-3 text-sm outline-none transition focus:ring-2"
              style={{
                borderColor: colors.border,
                '--tw-ring-color': colors.lightBlue,
              }}
            />
          </div>

          <div>
            <label
              htmlFor="analytics-top-documents"
              className="mb-2 block text-sm font-medium text-stone-700"
            >
              Documents to display
            </label>
            <select
              id="analytics-top-documents"
              value={topDocuments}
              onChange={(event) => setTopDocuments(event.target.value)}
              className="w-full min-w-0 rounded-xl border bg-white px-4 py-3 text-sm outline-none focus:ring-2"
              style={{
                borderColor: colors.border,
                '--tw-ring-color': colors.lightBlue,
              }}
            >
              <option value="5">Top 5 documents</option>
              <option value="10">Top 10 documents</option>
              <option value="20">Top 20 documents</option>
              <option value="50">Top 50 documents</option>
            </select>
          </div>

          <div className="flex items-end">
            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-xl px-5 py-3 text-sm font-semibold text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60 lg:w-auto"
              style={{ backgroundColor: colors.purple }}
            >
              {loading ? 'Loading...' : 'Apply filters'}
            </button>
          </div>
        </form>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t pt-4" style={{ borderColor: colors.border }}>
          <p className="break-words text-xs leading-5 text-stone-500">
            {safeData.benchmark_run_id
              ? `Active benchmark: ${safeData.benchmark_run_id}`
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
            className="rounded-lg px-3 py-2 text-sm font-semibold transition hover:bg-[#F5F0FA] disabled:opacity-50"
            style={{ color: colors.purple }}
          >
            Reset filters
          </button>
        </div>
      </Section>

      {error && (
        <div
          role="alert"
          className="rounded-2xl border bg-red-50 p-5"
          style={{ borderColor: '#FECACA' }}
        >
          <h2 className="font-bold text-red-900">
            Unable to load analytics
          </h2>
          <p className="mt-2 break-words text-sm leading-6 text-red-800">
            {error}
          </p>

          <button
            type="button"
            onClick={() => loadAnalytics({ benchmarkRunId, topDocuments })}
            disabled={loading}
            className="mt-4 rounded-xl border border-red-200 bg-white px-4 py-2.5 text-sm font-semibold text-red-800 hover:bg-red-100 disabled:opacity-50"
          >
            Try again
          </button>
        </div>
      )}

      {loading && !data && (
        <div
          role="status"
          className="rounded-2xl border bg-white p-10 text-center"
          style={{ borderColor: colors.border }}
        >
          <div className="mx-auto h-9 w-9 animate-spin rounded-full border-4 border-stone-200 border-t-[#738fbd]" />
          <p className="mt-4 font-semibold text-stone-700">
            Loading live analytics...
          </p>
          <p className="mt-2 text-sm text-stone-500">
            Fetching statistics from the Attest backend.
          </p>
        </div>
      )}

      {!data && !loading && !error && (
        <div
          className="rounded-2xl border bg-white p-10 text-center"
          style={{ borderColor: colors.border }}
        >
          <p className="font-semibold text-stone-700">
            No analytics data is available yet.
          </p>
          <p className="mt-2 text-sm text-stone-500">
            Apply filters or try refreshing the analytics.
          </p>
          <button
            type="button"
            onClick={() => loadAnalytics({ benchmarkRunId, topDocuments })}
            className="mt-4 rounded-xl px-4 py-2.5 text-sm font-semibold text-white"
            style={{ backgroundColor: colors.purple }}
          >
            Load analytics
          </button>
        </div>
      )}

      {data && (
        <>
          <div
            className="flex items-start gap-3 rounded-2xl border bg-[#F0F7F3] p-4"
            style={{ borderColor: '#D5E8DB' }}
          >
            <span className="mt-0.5 text-lg text-emerald-700">✓</span>
            <div>
              <p className="text-sm font-bold text-emerald-900">
                Live backend statistics
              </p>
              <p className="mt-1 text-sm leading-6 text-emerald-800">
                Metrics below come from the analytics API. Only usable
                evaluations contribute to score averages, so counts and score
                denominators can differ.
                {loading && ' Refreshing data...'}
              </p>
            </div>
          </div>

          <section>
            <div className="mb-4 px-1">
              <p className="text-xs font-bold uppercase tracking-widest" style={{ color: colors.blue }}>
                At a glance
              </p>
              <h2 className="mt-1 text-xl font-bold text-stone-800">
                Performance summary
              </h2>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard
                label="Total questions"
                value={formatCount(safeData.total_questions)}
                note="Queries recorded in the selected scope"
                color={colors.purple}
                icon="▤"
                tint="#F1EBF8"
              />

              <StatCard
                label="First-pass success"
                value={formatPercent(firstPass.rate)}
                note={`${formatCount(firstPass.count)} passed out of ${formatCount(firstPass.total)} usable first-attempt evaluations`}
                color={colors.blue}
                icon="↗"
                tint="#EDF3FA"
              />

              <StatCard
                label="Insufficient evidence"
                value={formatCount(safeData.insufficient_evidence)}
                note="Queries with insufficient-evidence status"
                color="#B7791F"
                icon="⌕"
                tint="#FFF6E5"
              />

              <StatCard
                label="Unsupported claims"
                value={formatCount(safeData.unsupported_claims)}
                note="Unsupported claims in recorded evaluations"
                color="#C2415A"
                icon="!"
                tint="#FDF0F3"
              />
            </div>
          </section>

          <Section
            title="Aggregate model quality"
            description="Compare the average evaluation scores for Basic RAG and Attest. These are benchmark-level averages, not individual-query scores."
            icon="◈"
          >
            <div className="mt-5 grid grid-cols-1 gap-4 xl:grid-cols-2">
              <ScorePanel
                title="Basic RAG"
                scores={basicScores}
                accent={colors.blue}
                tint="#EDF3FA"
              />

              <ScorePanel
                title="Attest"
                scores={reliScores}
                accent={colors.pink}
                tint="#FDF0F3"
              />
            </div>
          </Section>

          <Section
            title="First-pass performance"
            description="Percentage of queries whose first evaluated attempt passed, shown separately for each mode."
            icon="↗"
          >
            <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-2">
              {[
                {
                  name: 'Basic RAG',
                  mode: basic,
                  accent: colors.blue,
                  tint: '#EDF3FA',
                },
                {
                  name: 'Attest',
                  mode: reli,
                  accent: colors.pink,
                  tint: '#FDF0F3',
                },
              ].map(({ name, mode, accent, tint }) => {
                const first = getObject(mode.first_pass)
                const final = getObject(mode.final_pass)

                return (
                  <article
                    key={name}
                    className="rounded-2xl border p-5"
                    style={{ borderColor: colors.border, backgroundColor: tint }}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <h3 className="font-bold text-stone-800">{name}</h3>
                        <p className="mt-1 text-xs text-stone-500">
                          First-attempt evaluation
                        </p>
                      </div>
                      <span
                        className="h-3 w-3 rounded-full"
                        style={{ backgroundColor: accent }}
                      />
                    </div>

                    <p className="mt-5 text-3xl font-bold" style={{ color: accent }}>
                      {formatPercent(first.rate)}
                    </p>

                    <div className="mt-3 h-2 overflow-hidden rounded-full bg-white">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${Math.max(0, Math.min(100, Number(first.rate) * 100 || 0))}%`,
                          backgroundColor: accent,
                        }}
                      />
                    </div>

                    <p className="mt-3 text-xs leading-5 text-stone-600">
                      {formatCount(first.count)} passed / {formatCount(first.total)} evaluated first attempts
                    </p>

                    <div className="mt-4 space-y-2 border-t border-black/5 pt-4 text-sm">
                      <div className="flex justify-between gap-3">
                        <span className="text-stone-500">Final answers passed</span>
                        <strong className="text-stone-800">
                          {formatCount(final.count)} / {formatCount(final.total)} ({formatPercent(final.rate)})
                        </strong>
                      </div>
                      <div className="flex justify-between gap-3">
                        <span className="text-stone-500">Questions recorded</span>
                        <strong className="text-stone-800">{formatCount(mode.questions)}</strong>
                      </div>
                      <div className="flex justify-between gap-3">
                        <span className="text-stone-500">Insufficient evidence</span>
                        <strong className="text-stone-800">{formatCount(mode.insufficient_evidence)}</strong>
                      </div>
                    </div>
                  </article>
                )
              })}
            </div>
          </Section>

          <Section
            title="Correction performance"
            description="Understand how often Attest triggers a correction and how many second attempts pass evaluation."
            icon="↻"
          >
            <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard
                label="Eligible for correction"
                value={formatCount(corrections.eligible)}
                note="First attempts that failed a usable evaluation"
                color={colors.purple}
                icon="◎"
                tint="#F1EBF8"
              />

              <StatCard
                label="Corrections triggered"
                value={formatCount(corrections.triggered)}
                note="Queries with a stored second attempt"
                color={colors.blue}
                icon="↻"
                tint="#EDF3FA"
              />

              <StatCard
                label="Successful corrections"
                value={formatCount(corrections.successful)}
                note="Second attempt reported as the final answer and passed"
                color="#27845A"
                icon="✓"
                tint="#EFF7F2"
              />

              <StatCard
                label="Correction success rate"
                value={formatPercent(corrections.success_rate)}
                note="Successful corrections / triggered corrections"
                color={colors.pink}
                icon="%"
                tint="#FDF0F3"
              />
            </div>

            <div className="mt-4 flex flex-wrap gap-3">
              <div className="rounded-xl border bg-white px-4 py-3" style={{ borderColor: colors.border }}>
                <span className="text-xs text-stone-500">Correction trigger rate</span>
                <p className="mt-1 font-bold" style={{ color: colors.purple }}>
                  {formatPercent(corrections.trigger_rate)}
                </p>
              </div>

              <div className="rounded-xl border bg-white px-4 py-3" style={{ borderColor: colors.border }}>
                <span className="text-xs text-stone-500">Failed after correction</span>
                <p className="mt-1 font-bold text-red-700">
                  {formatCount(corrections.failed_after_correction)}
                </p>
              </div>
            </div>
          </Section>

          <Section
            title="Average latency"
            description="Average recorded generation and evaluation times per query. Retrieval and query-rewriting time are not included in these metrics."
            icon="◷"
          >
            {[
              {
                name: 'Basic RAG',
                latency: basicLatency,
                accent: colors.blue,
                tint: '#EDF3FA',
              },
              {
                name: 'Attest',
                latency: reliLatency,
                accent: colors.pink,
                tint: '#FDF0F3',
              },
            ].map(({ name, latency, accent, tint }) => (
              <div key={name} className="mt-5">
                <div className="mb-3 flex items-center gap-2">
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ backgroundColor: accent }}
                  />
                  <h3 className="font-bold text-stone-800">{name}</h3>
                </div>

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  {[
                    {
                      label: 'Generation',
                      value: latency.avg_generation_ms,
                    },
                    {
                      label: 'Evaluation',
                      value: latency.avg_evaluation_ms,
                    },
                    {
                      label: 'Total recorded',
                      value: latency.avg_total_ms,
                    },
                  ].map((metric) => (
                    <div
                      key={metric.label}
                      className="rounded-2xl border p-4 sm:p-5"
                      style={{ borderColor: colors.border, backgroundColor: tint }}
                    >
                      <p className="text-sm text-stone-500">{metric.label}</p>
                      <p className="mt-2 break-words text-2xl font-bold" style={{ color: colors.purple }}>
                        {formatLatency(metric.value)}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </Section>

          <Section
            title="Top retrieved documents"
            description="Documents ranked by recorded retrieval activity in the selected scope."
            icon="▤"
          >
            {topDocumentsList.length === 0 ? (
              <div className="mt-5 rounded-2xl border border-dashed p-8 text-center" style={{ borderColor: colors.border }}>
                <div className="text-2xl">▤</div>
                <p className="mt-3 font-semibold text-stone-700">
                  No document usage found
                </p>
                <p className="mt-1 text-sm leading-6 text-stone-500">
                  No matching document retrievals were recorded for this scope.
                </p>
              </div>
            ) : (
              <div className="mt-5 space-y-3">
                {topDocumentsList.map((document, index) => {
                  const safeDocument = getObject(document)

                  return (
                    <article
                      key={safeDocument.document_id ?? index}
                      className="flex flex-col gap-4 rounded-2xl border bg-white p-4 transition hover:bg-[#FCFAFD] sm:flex-row sm:items-center sm:justify-between sm:p-5"
                      style={{ borderColor: colors.border }}
                    >
                      <div className="flex min-w-0 items-start gap-3">
                        <div
                          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-sm font-bold"
                          style={{
                            backgroundColor: index % 2 === 0 ? '#F1EBF8' : '#EDF3FA',
                            color: colors.purple,
                          }}
                        >
                          {index + 1}
                        </div>

                        <div className="min-w-0">
                          <p className="break-words font-semibold text-stone-800">
                            {safeDocument.filename || 'Unnamed document'}
                          </p>
                          <p className="mt-1 text-xs text-stone-500">
                            Document ID: {safeDocument.document_id ?? 'N/A'}
                          </p>
                        </div>
                      </div>

                      <div className="flex shrink-0 gap-5 sm:gap-7">
                        <div>
                          <p className="text-xs text-stone-500">Retrievals</p>
                          <p className="mt-1 text-lg font-bold" style={{ color: colors.purple }}>
                            {formatCount(safeDocument.retrievals)}
                          </p>
                        </div>

                        <div>
                          <p className="text-xs text-stone-500">Queries</p>
                          <p className="mt-1 text-lg font-bold" style={{ color: colors.blue }}>
                            {formatCount(safeDocument.queries)}
                          </p>
                        </div>
                      </div>
                    </article>
                  )
                })}
              </div>
            )}
          </Section>
        </>
      )}
    </div>
  )
}

export default Analytics

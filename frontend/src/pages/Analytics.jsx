
import { useMemo, useState } from 'react'

const evaluations = [
  {
    id: 'EV-104',
    question: 'How does network segmentation improve security?',
    date: '10 Oct 2026',
    faithfulness: 94,
    relevance: 91,
    status: 'PASSED',
  },
  {
    id: 'EV-103',
    question: 'Does every firewall prevent all cyberattacks?',
    date: '09 Oct 2026',
    faithfulness: 94,
    relevance: 88,
    status: 'CORRECTED',
  },
  {
    id: 'EV-102',
    question: 'What is the purpose of a network firewall?',
    date: '08 Oct 2026',
    faithfulness: 62,
    relevance: 75,
    status: 'FAILED_AFTER_CORRECTION',
  },
  {
    id: 'EV-101',
    question: 'Explain the benefits of network security.',
    date: '07 Oct 2026',
    faithfulness: 0,
    relevance: 0,
    status: 'INSUFFICIENT_EVIDENCE',
  },
]

const statusStyles = {
  PASSED: 'bg-green-100 text-green-800',
  CORRECTED: 'bg-amber-100 text-amber-800',
  FAILED_AFTER_CORRECTION: 'bg-red-100 text-red-800',
  INSUFFICIENT_EVIDENCE: 'bg-gray-100 text-gray-700',
}

const statusLabels = {
  PASSED: 'Passed',
  CORRECTED: 'Corrected',
  FAILED_AFTER_CORRECTION: 'Failed after correction',
  INSUFFICIENT_EVIDENCE: 'Insufficient evidence',
}

function Analytics() {
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [selectedEvaluation, setSelectedEvaluation] = useState(null)

  const filteredEvaluations = useMemo(() => {
    const term = search.trim().toLowerCase()

    return evaluations.filter((item) => {
      const matchesSearch =
        item.question.toLowerCase().includes(term) ||
        item.id.toLowerCase().includes(term)

      const matchesStatus =
        statusFilter === 'ALL' || item.status === statusFilter

      return matchesSearch && matchesStatus
    })
  }, [search, statusFilter])

  const completed = evaluations.filter(
    (item) => item.status !== 'INSUFFICIENT_EVIDENCE'
  )
  const averageFaithfulness = Math.round(
    completed.reduce((sum, item) => sum + item.faithfulness, 0) /
      completed.length
  )
  const correctedCount = evaluations.filter(
    (item) => item.status === 'CORRECTED'
  ).length
  const failedCount = evaluations.filter(
    (item) => item.status === 'FAILED_AFTER_CORRECTION'
  ).length

  const scoreMetrics = [
    { label: 'Faithfulness', value: 86, color: '#738fbd' },
    { label: 'Answer relevance', value: 85, color: '#db88a4' },
    { label: 'Context relevance', value: 82, color: '#a8c3d4' },
  ]

  return (
    <div className="space-y-6">
      <header>
        <p className="text-sm font-medium" style={{ color: '#7080DA' }}>
          PERFORMANCE OVERVIEW
        </p>
        <h1 className="mt-1 text-3xl font-bold" style={{ color: '#554188' }}>
          Analytics & History
        </h1>
        <p className="mt-2 text-sm text-gray-500">
          Track evaluation quality, review past questions, and inspect results.
        </p>
      </header>

      <div className="rounded-xl border border-[#E5DBE6] bg-white px-4 py-3 text-sm text-gray-600">
        <span className="font-semibold text-[#554188]">Demo mode:</span>{' '}
        All statistics and history records on this screen are illustrative mock data.
      </div>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          {
            label: 'Total evaluations',
            value: evaluations.length,
            note: 'Sample records',
            color: '#554188',
          },
          {
            label: 'Average faithfulness',
            value: `${averageFaithfulness}%`,
            note: 'Excludes insufficient evidence',
            color: '#738fbd',
          },
          {
            label: 'Corrected answers',
            value: correctedCount,
            note: 'Correction applied',
            color: '#b7791f',
          },
          {
            label: 'Failed evaluations',
            value: failedCount,
            note: 'Require review',
            color: '#c24141',
          },
        ].map((card) => (
          <article
            key={card.label}
            className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm"
          >
            <p className="text-sm text-gray-500">{card.label}</p>
            <p
              className="mt-3 text-3xl font-bold"
              style={{ color: card.color }}
            >
              {card.value}
            </p>
            <p className="mt-2 text-xs text-gray-500">{card.note}</p>
          </article>
        ))}
      </section>

      <section className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm">
        <div>
          <h2 className="text-lg font-bold text-gray-800">
            Quality score overview
          </h2>
          <p className="mt-1 text-sm text-gray-500">
            Illustrative metric values for the dashboard preview.
          </p>
        </div>

        <div className="mt-6 space-y-5">
          {scoreMetrics.map((metric) => (
            <div key={metric.label}>
              <div className="mb-2 flex items-center justify-between gap-3">
                <span className="text-sm font-medium text-gray-700">
                  {metric.label}
                </span>
                <span className="text-sm font-bold text-gray-800">
                  {metric.value}%
                </span>
              </div>
              <div
                className="h-3 overflow-hidden rounded-full bg-gray-100"
                role="progressbar"
                aria-label={metric.label}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={metric.value}
              >
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${metric.value}%`,
                    backgroundColor: metric.color,
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-gray-800">
              Evaluation history
            </h2>
            <p className="mt-1 text-sm text-gray-500">
              Search and filter previous evaluation records.
            </p>
          </div>
          <span className="rounded-full bg-[#E5DBE6] px-3 py-1 text-xs font-semibold text-[#554188]">
            {filteredEvaluations.length} RECORDS
          </span>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-2">
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search questions or evaluation ID..."
            aria-label="Search evaluation history"
            className="min-w-0 rounded-xl border border-[#E5DBE6] px-4 py-3 text-sm outline-none focus:border-[#7080DA] focus:ring-2 focus:ring-[#7080DA]/20"
          />

          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            aria-label="Filter by evaluation status"
            className="min-w-0 rounded-xl border border-[#E5DBE6] bg-white px-4 py-3 text-sm outline-none focus:border-[#7080DA]"
          >
            <option value="ALL">All statuses</option>
            <option value="PASSED">Passed</option>
            <option value="CORRECTED">Corrected</option>
            <option value="FAILED_AFTER_CORRECTION">
              Failed after correction
            </option>
            <option value="INSUFFICIENT_EVIDENCE">
              Insufficient evidence
            </option>
          </select>
        </div>

        <div className="mt-5 space-y-3">
          {filteredEvaluations.length === 0 ? (
            <div className="rounded-xl bg-[#F5F5F4] p-8 text-center">
              <p className="font-semibold text-gray-700">
                No evaluations found
              </p>
              <p className="mt-1 text-sm text-gray-500">
                Try a different search term or status filter.
              </p>
            </div>
          ) : (
            filteredEvaluations.map((item) => (
              <article
                key={item.id}
                className="rounded-xl border border-[#E5DBE6] p-4 transition hover:bg-[#F5F5F4]/60"
              >
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-semibold text-[#7080DA]">
                      {item.id} · {item.date}
                    </p>
                    <h3 className="mt-2 break-words text-sm font-semibold leading-6 text-gray-800">
                      {item.question}
                    </h3>
                    <div className="mt-3 flex flex-wrap gap-4 text-xs text-gray-500">
                      <span>Faithfulness: {item.faithfulness}%</span>
                      <span>Relevance: {item.relevance}%</span>
                    </div>
                  </div>

                  <div className="flex shrink-0 flex-wrap items-center gap-2 sm:flex-col sm:items-end">
                    <span
                      className={`max-w-full rounded-full px-3 py-1 text-xs font-semibold ${statusStyles[item.status]}`}
                    >
                      {statusLabels[item.status]}
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        setSelectedEvaluation(
                          selectedEvaluation?.id === item.id ? null : item
                        )
                      }
                      className="rounded-lg border border-[#E5DBE6] px-3 py-2 text-xs font-semibold text-[#554188] hover:bg-[#E5DBE6]/50"
                    >
                      {selectedEvaluation?.id === item.id
                        ? 'Hide details'
                        : 'View details'}
                    </button>
                  </div>
                </div>

                {selectedEvaluation?.id === item.id && (
                  <div className="mt-4 rounded-xl bg-[#F5F5F4] p-4">
                    <p className="text-sm font-semibold text-gray-800">
                      Evaluation summary
                    </p>
                    <p className="mt-2 break-words text-sm leading-6 text-gray-600">
                      {item.status === 'PASSED' &&
                        'This sample answer passed its configured checks.'}
                      {item.status === 'CORRECTED' &&
                        'This sample answer was revised after an evaluation check.'}
                      {item.status === 'FAILED_AFTER_CORRECTION' &&
                        'This sample answer did not pass after correction and needs review.'}
                      {item.status === 'INSUFFICIENT_EVIDENCE' &&
                        'The available evidence was insufficient to support a reliable answer.'}
                    </p>
                  </div>
                )}
              </article>
            ))
          )}
        </div>
      </section>
    </div>
  )
}

export default Analytics

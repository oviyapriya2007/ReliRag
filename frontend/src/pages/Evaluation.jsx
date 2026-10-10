
import { useState } from 'react'

const statusStyles = {
  PASSED: 'bg-green-100 text-green-800',
  CORRECTED: 'bg-amber-100 text-amber-800',
  FAILED_AFTER_CORRECTION: 'bg-red-100 text-red-800',
  INSUFFICIENT_EVIDENCE: 'bg-gray-100 text-gray-700',
}

const claims = [
  {
    id: 1,
    claim: 'Firewalls filter network traffic according to security rules.',
    supported: true,
    source: 'Network Security Fundamentals.pdf · Page 12',
  },
  {
    id: 2,
    claim: 'Network segmentation can limit unauthorized access.',
    supported: true,
    source: 'Computer Networks.pdf · Page 28',
  },
  {
    id: 3,
    claim: 'Every firewall prevents all cyberattacks.',
    supported: false,
    source: 'No supporting evidence found',
  },
]

function Evaluation() {
  const [selectedStatus, setSelectedStatus] = useState('CORRECTED')

  const scores = [
    { label: 'Faithfulness', score: 94, color: '#738fbd' },
    { label: 'Answer relevance', score: 91, color: '#db88a4' },
    { label: 'Context relevance', score: 87, color: '#a8c3d4' },
  ]

  return (
    <div className="space-y-6">
      <header>
        <p className="text-sm font-medium" style={{ color: '#7080DA' }}>
          RELIABILITY ANALYSIS
        </p>
        <h1 className="mt-1 text-3xl font-bold" style={{ color: '#554188' }}>
          Evaluation Details
        </h1>
        <p className="mt-2 text-sm text-gray-500">
          Inspect answer quality, verify individual claims, and review correction status.
        </p>
      </header>

      <section className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
              Sample evaluation
            </p>
            <h2 className="mt-1 text-lg font-bold text-gray-800">
              Network segmentation and firewall security
            </h2>
          </div>
          <span className="rounded-full bg-[#E5DBE6] px-3 py-1 text-xs font-semibold text-[#554188]">
            DEMO DATA
          </span>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-3">
          {scores.map((item) => (
            <div key={item.label} className="rounded-xl bg-[#F5F5F4] p-4">
              <p className="text-sm text-gray-600">{item.label}</p>
              <div className="mt-2 flex items-center justify-between gap-2">
                <span className="text-2xl font-bold text-gray-800">
                  {item.score}%
                </span>
                <span className="text-xs text-gray-500">Illustrative</span>
              </div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-gray-200">
                <div
                  className="h-full rounded-full"
                  style={{ width: `${item.score}%`, backgroundColor: item.color }}
                />
              </div>
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-gray-500">
          These example scores are not calculated by the evaluation engine.
        </p>
      </section>

      <section className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm">
        <h2 className="text-lg font-bold text-gray-800">Correction status</h2>
        <p className="mt-1 text-sm text-gray-500">
          Choose a status to preview how each result will appear in the interface.
        </p>

        <div className="mt-4 flex flex-wrap gap-2">
          {Object.keys(statusStyles).map((status) => (
            <button
              key={status}
              type="button"
              onClick={() => setSelectedStatus(status)}
              className={`rounded-xl px-3 py-2 text-xs font-semibold transition ${
                selectedStatus === status
                  ? 'ring-2 ring-[#554188] ring-offset-2'
                  : ''
              } ${statusStyles[status]}`}
            >
              {status}
            </button>
          ))}
        </div>

        <div className="mt-5 rounded-xl bg-[#F5F5F4] p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Selected result
          </p>
          <span
            className={`mt-2 inline-block rounded-full px-3 py-1 text-sm font-semibold ${statusStyles[selectedStatus]}`}
          >
            {selectedStatus.replaceAll('_', ' ')}
          </span>
          <p className="mt-2 text-sm text-gray-600">
            {selectedStatus === 'PASSED' &&
              'The answer passed the configured evaluation checks.'}
            {selectedStatus === 'CORRECTED' &&
              'The answer was revised after an evaluation check.'}
            {selectedStatus === 'FAILED_AFTER_CORRECTION' &&
              'The answer did not pass even after correction.'}
            {selectedStatus === 'INSUFFICIENT_EVIDENCE' &&
              'There is not enough evidence to support a reliable answer.'}
          </p>
        </div>
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-lg font-bold text-gray-800">Claim verification</h2>
          <p className="mt-1 text-sm text-gray-500">
            Review whether individual statements are supported by the retrieved evidence.
          </p>
        </div>

        {claims.map((item) => (
          <article
            key={item.id}
            className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <p className="flex-1 text-sm font-medium leading-6 text-gray-800">
                {item.claim}
              </p>
              <span
                className={`rounded-full px-3 py-1 text-xs font-semibold ${
                  item.supported
                    ? 'bg-green-100 text-green-800'
                    : 'bg-red-100 text-red-800'
                }`}
              >
                {item.supported ? 'SUPPORTED' : 'UNSUPPORTED'}
              </span>
            </div>
            <div className="mt-4 rounded-lg border-l-4 border-[#738fbd] bg-[#F5F5F4] p-3">
              <p className="text-xs font-semibold text-gray-500">Evidence reference</p>
              <p className="mt-1 text-sm text-gray-700">{item.source}</p>
            </div>
          </article>
        ))}
      </section>
    </div>
  )
}

export default Evaluation

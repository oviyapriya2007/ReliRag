
import { useState } from 'react'

function Comparison() {
  const [showDetails, setShowDetails] = useState(true)

  const metrics = [
    { label: 'Faithfulness', before: 58, after: 94 },
    { label: 'Answer relevance', before: 72, after: 91 },
    { label: 'Context relevance', before: 65, after: 87 },
  ]

  const correctionSteps = [
    {
      number: '1',
      title: 'Problem identified',
      description: 'The original answer claimed complete protection.',
    },
    {
      number: '2',
      title: 'Evidence reviewed',
      description:
        'The available evidence describes traffic filtering, not guaranteed prevention of every attack.',
    },
    {
      number: '3',
      title: 'Answer corrected',
      description:
        'The revised answer explains the firewall’s purpose and limitations.',
    },
    {
      number: '4',
      title: 'Quality re-evaluated',
      description:
        'The corrected answer can now be evaluated against the retrieved context.',
    },
  ]

  return (
    <div className="space-y-6">
      <header>
        <p className="text-sm font-medium" style={{ color: '#7080DA' }}>
          ANSWER QUALITY WORKSPACE
        </p>
        <h1 className="mt-1 text-3xl font-bold" style={{ color: '#554188' }}>
          Comparison Lab
        </h1>
        <p className="mt-2 text-sm text-gray-500">
          Compare a basic RAG answer with RELI-RAG's corrected answer.
        </p>
      </header>

      <section className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          Sample question
        </p>
        <h2 className="mt-2 text-lg font-semibold text-gray-800">
          Does every firewall prevent all cyberattacks?
        </h2>
        <p className="mt-2 text-sm text-gray-500">
          Demo comparison · Illustrative scores only
        </p>
      </section>

      <section className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <article className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-lg font-bold text-gray-800">Basic RAG</h2>
            <span className="rounded-full bg-red-100 px-3 py-1 text-xs font-semibold text-red-800">
              ORIGINAL
            </span>
          </div>

          <p className="mt-4 text-sm leading-7 text-gray-700">
            Yes. Every firewall prevents all cyberattacks by blocking malicious
            traffic from entering the network.
          </p>

          <div className="mt-5 rounded-xl bg-red-50 p-4">
            <p className="text-sm font-semibold text-red-800">Issue detected</p>
            <p className="mt-1 text-sm leading-6 text-red-700">
              The answer makes an absolute claim that is not supported by the
              available evidence.
            </p>
          </div>

          <p className="mt-5 text-sm text-gray-500">
            Illustrative faithfulness
          </p>
          <p className="mt-1 text-3xl font-bold text-red-700">58%</p>
        </article>

        <article className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-lg font-bold text-gray-800">RELI-RAG</h2>
            <span className="rounded-full bg-green-100 px-3 py-1 text-xs font-semibold text-green-800">
              CORRECTED
            </span>
          </div>

          <p className="mt-4 text-sm leading-7 text-gray-700">
            No. Firewalls can filter network traffic according to security rules,
            but they cannot guarantee protection against every cyberattack.
            Their effectiveness depends on configuration and the threats involved.
          </p>

          <div className="mt-5 rounded-xl bg-green-50 p-4">
            <p className="text-sm font-semibold text-green-800">
              Correction applied
            </p>
            <p className="mt-1 text-sm leading-6 text-green-700">
              The absolute claim was replaced with a qualified answer that
              avoids promising complete protection.
            </p>
          </div>

          <p className="mt-5 text-sm text-gray-500">
            Illustrative faithfulness
          </p>
          <p className="mt-1 text-3xl font-bold text-green-700">94%</p>
        </article>
      </section>

      <section className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-gray-800">
              Quality score comparison
            </h2>
            <p className="mt-1 text-sm text-gray-500">
              Illustrative scores before and after correction.
            </p>
          </div>

          <span className="rounded-full bg-[#E5DBE6] px-3 py-1 text-xs font-semibold text-[#554188]">
            MOCK DATA
          </span>
        </div>

        <div className="mt-5 space-y-5">
          {metrics.map((metric) => (
            <div key={metric.label}>
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium text-gray-700">
                  {metric.label}
                </span>
                <span className="text-sm font-semibold text-gray-800">
                  {metric.before}% → {metric.after}%
                  <span className="ml-2 text-green-700">
                    (+{metric.after - metric.before})
                  </span>
                </span>
              </div>

              <div className="space-y-2">
                <div className="h-2 overflow-hidden rounded-full bg-gray-100">
                  <div
                    className="h-full rounded-full bg-[#db88a4]"
                    style={{ width: `${metric.before}%` }}
                  />
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-gray-100">
                  <div
                    className="h-full rounded-full bg-[#738fbd]"
                    style={{ width: `${metric.after}%` }}
                  />
                </div>
              </div>
            </div>
          ))}

          <div className="flex flex-wrap gap-4 pt-1 text-xs text-gray-500">
            <span className="flex items-center gap-2">
              <span className="h-3 w-3 rounded-sm bg-[#db88a4]" />
              Before correction
            </span>
            <span className="flex items-center gap-2">
              <span className="h-3 w-3 rounded-sm bg-[#738fbd]" />
              After correction
            </span>
          </div>
        </div>

        <p className="mt-4 text-xs text-gray-500">
          The displayed values are examples for UI testing, not measured results.
        </p>
      </section>

      <section className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm">
        <button
          type="button"
          onClick={() => setShowDetails((previous) => !previous)}
          aria-expanded={showDetails}
          className="flex w-full items-center justify-between gap-3 text-left"
        >
          <span className="text-lg font-bold text-gray-800">
            Correction details
          </span>
          <span className="shrink-0 text-sm font-semibold text-[#554188]">
            {showDetails ? 'Hide −' : 'Show +'}
          </span>
        </button>

        {showDetails && (
          <div className="mt-5 space-y-3">
            {correctionSteps.map((step) => (
              <div
                key={step.number}
                className="flex items-start gap-4 rounded-xl bg-[#F5F5F4] p-4"
              >
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#E5DBE6] text-sm font-bold text-[#554188]">
                  {step.number}
                </div>

                <div className="min-w-0 flex-1 pt-0.5">
                  <h3 className="break-words text-sm font-semibold leading-6 text-gray-800">
                    {step.title}
                  </h3>
                  <p className="mt-1 break-words text-sm leading-6 text-gray-600">
                    {step.description}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

export default Comparison

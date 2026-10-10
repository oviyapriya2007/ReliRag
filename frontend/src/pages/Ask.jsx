
import { useState } from 'react'

const evidence = [
  {
    id: 1,
    title: 'Network Security Fundamentals.pdf',
    page: 12,
    score: 0.94,
    text: 'Firewalls monitor and filter incoming and outgoing network traffic according to defined security rules.',
  },
  {
    id: 2,
    title: 'Computer Networks.pdf',
    page: 28,
    score: 0.87,
    text: 'Network segmentation divides a network into smaller sections to improve security and limit unauthorized access.',
  },
]

function Ask() {
  const [question, setQuestion] = useState('')
  const [submitted, setSubmitted] = useState(false)

  function handleAsk(event) {
    event.preventDefault()
    if (question.trim()) setSubmitted(true)
  }

  return (
    <div className="space-y-6">
      <header>
        <p className="text-sm font-medium" style={{ color: '#7080DA' }}>
          KNOWLEDGE WORKSPACE
        </p>
        <h1 className="mt-1 text-3xl font-bold" style={{ color: '#554188' }}>
          Ask RELI-RAG
        </h1>
        <p className="mt-2 text-sm text-gray-500">
          Ask a question, inspect supporting evidence, and review answer quality.
        </p>
      </header>

      <form
        onSubmit={handleAsk}
        className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm"
      >
        <label className="mb-3 block text-sm font-semibold text-gray-700">
          Your question
        </label>
        <textarea
          value={question}
          onChange={(event) => {
            setQuestion(event.target.value)
            setSubmitted(false)
          }}
          placeholder="e.g. How does network segmentation improve security?"
          rows={3}
          className="w-full resize-y rounded-xl border border-[#E5DBE6] p-4 text-sm outline-none focus:border-[#7080DA] focus:ring-2 focus:ring-[#7080DA]/20"
        />
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-gray-500">
            Demo mode · Answers use sample data
          </p>
          <button
            type="submit"
            className="rounded-xl px-5 py-3 text-sm font-semibold text-white transition hover:opacity-90"
            style={{ backgroundColor: '#554188' }}
          >
            Ask question →
          </button>
        </div>
      </form>

      {submitted && (
        <div className="space-y-5">
          <section className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-lg font-bold text-gray-800">Generated answer</h2>
              <span className="rounded-full bg-[#E5DBE6] px-3 py-1 text-xs font-semibold text-[#554188]">
                MOCK RESPONSE
              </span>
            </div>
            <p className="leading-7 text-gray-700">
              Network segmentation improves security by dividing a network into
              smaller sections, limiting unauthorized access between them.
              Firewalls help enforce traffic rules and control communication
              between these sections.
            </p>
            <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
              {[
                ['Faithfulness', '94%', '#738fbd'],
                ['Answer relevance', '91%', '#db88a4'],
                ['Context relevance', '87%', '#a8c3d4'],
              ].map(([label, value, color]) => (
                <div
                  key={label}
                  className="rounded-xl p-4"
                  style={{ backgroundColor: `${color}25` }}
                >
                  <p className="text-sm text-gray-600">{label}</p>
                  <p className="mt-1 text-2xl font-bold text-gray-800">{value}</p>
                </div>
              ))}
            </div>
            <p className="mt-4 text-xs text-gray-500">
              These scores are illustrative mock values, not actual evaluation results.
            </p>
          </section>

          <section className="space-y-3">
            <div>
              <h2 className="text-lg font-bold text-gray-800">Retrieved evidence</h2>
              <p className="mt-1 text-sm text-gray-500">
                Sample passages that support the answer.
              </p>
            </div>
            {evidence.map((item) => (
              <article
                key={item.id}
                className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h3 className="font-semibold text-gray-800">{item.title}</h3>
                    <p className="mt-1 text-xs text-gray-500">
                      Page {item.page} · Evidence {String(item.id).padStart(2, '0')}
                    </p>
                  </div>
                  <span className="rounded-lg bg-[#F5F5F4] px-3 py-2 text-xs font-semibold text-[#554188]">
                    Similarity {(item.score * 100).toFixed(0)}%
                  </span>
                </div>
                <p className="mt-4 rounded-lg border-l-4 border-[#738fbd] bg-[#F5F5F4] p-4 text-sm leading-6 text-gray-700">
                  {item.text}
                </p>
              </article>
            ))}
          </section>
        </div>
      )}
    </div>
  )
}

export default Ask

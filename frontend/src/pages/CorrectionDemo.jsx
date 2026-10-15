import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  DEMO_SOURCE_DOCUMENT,
  buildCorrectionDemoPayload,
} from '../demo/correctionDemo'

const PURPLE = '#554188'
const BLUE = '#738fbd'
const BORDER = '#E5DBE6'
const MUTED = '#57534E'
const GREEN = '#166534'
const RED = '#991B1B'

const cardStyle = {
  borderColor: BORDER,
  borderRadius: '16px',
}

function DemoBadge({ children }) {
  return (
    <span
      className="inline-block rounded-full px-3 py-1 text-xs font-bold tracking-wide"
      style={{ color: '#92400E', backgroundColor: '#FEF3C7' }}
    >
      {children}
    </span>
  )
}

function VerdictBadge({ passed }) {
  return (
    <span
      className="inline-block rounded-full px-3 py-1 text-xs font-semibold"
      style={
        passed
          ? { color: GREEN, backgroundColor: '#DCFCE7' }
          : { color: RED, backgroundColor: '#FEE2E2' }
      }
    >
      {passed ? 'PASSED (simulated)' : 'FAILED (simulated)'}
    </span>
  )
}

function ScoreRow({ label, value }) {
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <span style={{ color: MUTED }}>{label}</span>
      <strong style={{ color: PURPLE }}>
        {Math.round(Number(value) * 100)}%
      </strong>
    </div>
  )
}

function AttemptPanel({ attempt, title }) {
  const evaluation = attempt.evaluation

  return (
    <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
            {title}
          </h2>
          <p className="mt-1 text-sm" style={{ color: MUTED }}>
            Strategy:{' '}
            {attempt.strategy
              ? attempt.strategy.replaceAll('_', ' ')
              : 'initial retrieval'}
            {' · '}
            Citations: {attempt.citations.join(', ')}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <DemoBadge>DEMO / SIMULATED</DemoBadge>
          <VerdictBadge passed={evaluation.passed === true} />
        </div>
      </div>

      <pre
        className="mt-4 whitespace-pre-wrap rounded-xl p-4 text-sm leading-7"
        style={{ backgroundColor: '#F5F5F4', color: '#292524' }}
      >
        {attempt.answer}
      </pre>

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border p-4" style={{ borderColor: BORDER }}>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Simulated evaluation scores
          </p>
          <div className="mt-3 space-y-2">
            <ScoreRow label="Faithfulness" value={evaluation.faithfulness} />
            <ScoreRow
              label="Answer relevance"
              value={evaluation.answer_relevance}
            />
            <ScoreRow
              label="Context relevance"
              value={evaluation.context_relevance}
            />
          </div>
          {evaluation.failure_type && (
            <p className="mt-3 text-sm" style={{ color: RED }}>
              Failure type: {evaluation.failure_type.replaceAll('_', ' ')}
            </p>
          )}
        </div>

        <div className="rounded-xl border p-4" style={{ borderColor: BORDER }}>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Simulated evaluator feedback
          </p>
          <p className="mt-3 text-sm leading-6 text-gray-700">
            {evaluation.feedback}
          </p>
        </div>
      </div>

      <details className="mt-4">
        <summary
          className="cursor-pointer text-sm font-semibold"
          style={{ color: PURPLE }}
        >
          Evidence references ({attempt.retrieval.length})
        </summary>
        <ul className="mt-3 space-y-3">
          {attempt.retrieval.map((item) => (
            <li
              key={item.chunk_id}
              className="rounded-xl border p-3 text-sm"
              style={{ borderColor: BORDER }}
            >
              <p className="font-semibold text-gray-800">
                [{item.rank}] {item.filename}, page {item.page_number}
              </p>
              <p className="mt-2 leading-6 text-gray-600">{item.content}</p>
            </li>
          ))}
        </ul>
      </details>
    </section>
  )
}

export default function CorrectionDemo() {
  const demo = useMemo(() => buildCorrectionDemoPayload(), [])
  const [visible, setVisible] = useState(true)

  const attempt1 = demo.attempts[0]
  const attempt2 = demo.attempts[1]

  return (
    <div className="space-y-6">
      <header>
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-medium" style={{ color: BLUE }}>
            RELI-RAG
          </p>
          <DemoBadge>DEMO / SIMULATED</DemoBadge>
        </div>
        <h1 className="mt-1 text-3xl font-bold" style={{ color: PURPLE }}>
          Correction Demo
        </h1>
        <p className="mt-2 max-w-3xl text-sm leading-6" style={{ color: MUTED }}>
          A scripted walkthrough of how RELI-RAG can correct a partial answer.
          Results are fixed for presentation, labelled DEMO / SIMULATED, and are
          never saved to the database or sent to Claude. Production Ask queries
          are unchanged.
        </p>
      </header>

      <section
        className="border p-5 shadow-sm"
        style={{ ...cardStyle, backgroundColor: '#FFFBEB', borderColor: '#F59E0B' }}
      >
        <p className="text-sm font-semibold text-amber-900">
          Isolated from production RAG
        </p>
        <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-amber-900">
          <li>No API calls, no Claude requests, no database writes</li>
          <li>
            Source text is paraphrased from{' '}
            <code className="rounded bg-white/70 px-1">
              {DEMO_SOURCE_DOCUMENT}
            </code>{' '}
            for the demo only
          </li>
          <li>
            Live evaluation stays on{' '}
            <Link to="/ask" className="font-semibold underline">
              Ask
            </Link>
          </li>
        </ul>
      </section>

      <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
            Fixed demo question
          </h2>
          <DemoBadge>DEMO / SIMULATED</DemoBadge>
        </div>
        <p className="mt-3 text-base font-medium leading-7 text-gray-800">
          {demo.question}
        </p>
        <button
          type="button"
          onClick={() => setVisible((value) => !value)}
          className="mt-4 rounded-xl px-4 py-2 text-sm font-semibold text-white"
          style={{ backgroundColor: PURPLE }}
        >
          {visible ? 'Hide scripted results' : 'Show scripted results'}
        </button>
      </section>

      {visible && (
        <>
          <AttemptPanel
            attempt={attempt1}
            title="Attempt 1 — incomplete answer"
          />

          <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
                Correction query (rewrite)
              </h2>
              <DemoBadge>DEMO / SIMULATED</DemoBadge>
            </div>
            <p className="mt-2 text-sm" style={{ color: MUTED }}>
              After Attempt 1 fails for missing information, the demo shows a
              rewritten retrieval query that keeps all three topics.
            </p>
            <pre
              className="mt-4 whitespace-pre-wrap rounded-xl p-4 text-sm leading-7"
              style={{ backgroundColor: '#F0F5FF', color: '#292524' }}
            >
              {demo.correction_query}
            </pre>
          </section>

          <AttemptPanel
            attempt={attempt2}
            title="Attempt 2 — corrected answer"
          />

          <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
            <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
              Demo outcome
            </h2>
            <p className="mt-2 text-sm leading-6 text-gray-700">
              Reported attempt: {demo.final_attempt_number} of{' '}
              {demo.attempts.length}. Simulated final status:{' '}
              <strong>{demo.status}</strong>. Attempt 2 is marked PASSED because
              it covers network segmentation, MFA, and centralized logging with
              evidence references [1], [2], and [3].
            </p>
          </section>
        </>
      )}
    </div>
  )
}

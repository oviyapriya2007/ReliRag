import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  DEMO_SOURCE_DOCUMENT,
  buildCorrectionDemoPayload,
} from '../demo/correctionDemo'

const PURPLE = '#554188'
const BLUE = '#738fbd'
const PINK = '#db88a4'
const BORDER = '#E5DBE6'
const MUTED = '#57534E'
const GREEN = '#166534'
const RED = '#991B1B'

const cardStyle = {
  borderColor: BORDER,
  borderRadius: '20px',
}

function DemoBadge({ children }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-bold tracking-wide text-amber-800">
      <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
      {children}
    </span>
  )
}

function VerdictBadge({ passed }) {
  return (
    <span
      className="inline-flex items-center rounded-full px-3 py-1.5 text-xs font-semibold"
      style={
        passed
          ? { color: GREEN, backgroundColor: '#DCFCE7' }
          : { color: RED, backgroundColor: '#FEE2E2' }
      }
    >
      {passed ? 'PASSED · SIMULATED' : 'FAILED · SIMULATED'}
    </span>
  )
}

function ScoreRow({ label, value, color = BLUE }) {
  const numericValue = Number(value)
  const valid = Number.isFinite(numericValue)
  const percentage = valid
    ? Math.max(0, Math.min(100, numericValue * 100))
    : 0

  return (
    <div>
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="text-stone-600">{label}</span>
        <strong style={{ color: PURPLE }}>
          {valid ? `${Math.round(numericValue * 100)}%` : 'Not available'}
        </strong>
      </div>

      <div className="mt-2 h-2 overflow-hidden rounded-full bg-stone-100">
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

function AttemptPanel({ attempt, title, attemptNumber, accent }) {
  const evaluation = attempt.evaluation

  return (
    <section
      className="min-w-0 border bg-white p-5 shadow-sm sm:p-6"
      style={cardStyle}
    >
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl text-lg font-bold"
            style={{
              backgroundColor: accent.background,
              color: accent.text,
            }}
          >
            {attemptNumber}
          </div>

          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-stone-400">
              Correction workflow
            </p>
            <h2 className="mt-1 text-xl font-bold" style={{ color: PURPLE }}>
              {title}
            </h2>
            <p className="mt-1 text-sm capitalize text-stone-500">
              Strategy:{' '}
              {attempt.strategy
                ? attempt.strategy.replaceAll('_', ' ')
                : 'initial retrieval'}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <DemoBadge>DEMO / SIMULATED</DemoBadge>
          <VerdictBadge passed={evaluation.passed === true} />
        </div>
      </div>

      <div
        className="rounded-2xl border p-4 sm:p-5"
        style={{
          backgroundColor: accent.background,
          borderColor: accent.border,
        }}
      >
        <div className="mb-3 flex items-center justify-between gap-3">
          <h3 className="text-sm font-bold" style={{ color: PURPLE }}>
            Generated answer
          </h3>
          <span className="text-xs text-stone-500">
            {attempt.citations.length} citation(s)
          </span>
        </div>

        <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-7 text-stone-700">
          {attempt.answer}
        </pre>

        <p className="mt-4 break-words border-t border-black/5 pt-3 text-xs leading-5 text-stone-500">
          Evidence citations: {attempt.citations.length
            ? attempt.citations.join(', ')
            : 'No citations provided'}
        </p>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <div
          className="rounded-2xl border p-4 sm:p-5"
          style={{ borderColor: BORDER, backgroundColor: '#FCFAFD' }}
        >
          <div className="mb-4">
            <h3 className="font-bold text-stone-800">
              Evaluation scores
            </h3>
            <p className="mt-1 text-xs leading-5 text-stone-500">
              Fixed scores for this demonstration only.
            </p>
          </div>

          <div className="space-y-4">
            <ScoreRow
              label="Faithfulness"
              value={evaluation.faithfulness}
              color={BLUE}
            />
            <ScoreRow
              label="Answer relevance"
              value={evaluation.answer_relevance}
              color={PINK}
            />
            <ScoreRow
              label="Context relevance"
              value={evaluation.context_relevance}
              color="#91B9A7"
            />
          </div>

          {evaluation.failure_type && (
            <p className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-800">
              Failure type:{' '}
              {evaluation.failure_type.replaceAll('_', ' ')}
            </p>
          )}
        </div>

        <div
          className="rounded-2xl border p-4 sm:p-5"
          style={{ borderColor: BORDER, backgroundColor: '#F5F8FC' }}
        >
          <div className="mb-3 flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-white text-sm">
              ✦
            </span>
            <h3 className="font-bold text-stone-800">
              Evaluator feedback
            </h3>
          </div>

          <p className="text-sm leading-7 text-stone-600">
            {evaluation.feedback}
          </p>
        </div>
      </div>

      <details className="mt-5 overflow-hidden rounded-2xl border" style={{ borderColor: BORDER }}>
        <summary className="cursor-pointer list-none bg-white p-4 transition hover:bg-stone-50">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="font-semibold text-stone-800">
                Evidence explorer
              </p>
              <p className="mt-1 text-xs text-stone-500">
                Inspect the retrieved source passages used in this attempt.
              </p>
            </div>

            <span
              className="rounded-full px-3 py-1 text-xs font-semibold"
              style={{ backgroundColor: '#E5DBE6', color: PURPLE }}
            >
              {attempt.retrieval.length} source(s)
            </span>
          </div>
        </summary>

        <div className="space-y-3 border-t bg-[#FCFAFD] p-4" style={{ borderColor: BORDER }}>
          {attempt.retrieval.map((item) => (
            <article
              key={item.chunk_id}
              className="rounded-xl border bg-white p-4"
              style={{ borderColor: BORDER }}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span
                  className="rounded-lg px-2.5 py-1 text-xs font-bold"
                  style={{ backgroundColor: '#DCE8F0', color: '#385A78' }}
                >
                  Evidence [{item.rank}]
                </span>

                <span className="text-xs text-stone-500">
                  Page {item.page_number}
                </span>
              </div>

              <h4 className="mt-3 break-words text-sm font-semibold text-stone-800">
                {item.filename}
              </h4>

              <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-stone-600">
                {item.content}
              </p>
            </article>
          ))}
        </div>
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
    <div className="space-y-6 pb-6">
      <header
        className="overflow-hidden rounded-3xl border p-6 sm:p-8"
        style={{
          borderColor: BORDER,
          background:
            'linear-gradient(120deg, #F5F0FA 0%, #F1F6FC 55%, #FDF1F5 100%)',
        }}
      >
        <div className="flex flex-wrap items-center gap-2">
          <span
            className="rounded-full bg-white/80 px-3 py-1.5 text-xs font-bold tracking-wider"
            style={{ color: BLUE }}
          >
            RELI-RAG WORKSPACE
          </span>
          <DemoBadge>DEMO / SIMULATED</DemoBadge>
        </div>

        <h1 className="mt-4 text-3xl font-bold sm:text-4xl" style={{ color: PURPLE }}>
          Correction Demo
        </h1>

        <p className="mt-3 max-w-3xl text-sm leading-7 text-stone-600 sm:text-base">
          Explore how a retrieval-augmented generation workflow can identify
          an incomplete answer, rewrite its retrieval query, and produce an
          improved response using relevant evidence.
        </p>

        <div className="mt-6 grid gap-3 sm:grid-cols-3">
          <div className="rounded-2xl border border-white/80 bg-white/70 p-4">
            <p className="text-xs font-medium text-stone-500">Workflow</p>
            <p className="mt-1 font-bold" style={{ color: PURPLE }}>
              Two attempts
            </p>
          </div>

          <div className="rounded-2xl border border-white/80 bg-white/70 p-4">
            <p className="text-xs font-medium text-stone-500">Correction</p>
            <p className="mt-1 font-bold" style={{ color: PURPLE }}>
              Query rewrite
            </p>
          </div>

          <div className="rounded-2xl border border-white/80 bg-white/70 p-4">
            <p className="text-xs font-medium text-stone-500">Execution mode</p>
            <p className="mt-1 font-bold" style={{ color: PURPLE }}>
              Scripted demo
            </p>
          </div>
        </div>
      </header>

      <section
        className="border p-5 sm:p-6"
        style={{
          ...cardStyle,
          backgroundColor: '#FFFBEB',
          borderColor: '#F5D58A',
        }}
      >
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white text-lg">
            🛡️
          </div>

          <div className="min-w-0">
            <h2 className="font-bold text-amber-950">
              Isolated from production RAG
            </h2>

            <p className="mt-1 text-sm leading-6 text-amber-900">
              This page displays fixed demonstration data. It does not execute
              a live correction pipeline.
            </p>

            <ul className="mt-3 space-y-2 text-sm leading-6 text-amber-950">
              <li>✓ No API calls, Claude requests, or database writes.</li>
              <li>
                ✓ The source is paraphrased from{' '}
                <code className="break-words rounded-md bg-white/80 px-1.5 py-0.5">
                  {DEMO_SOURCE_DOCUMENT}
                </code>{' '}
                for this demonstration only.
              </li>
              <li>
                ✓ Production queries and evaluation remain available on{' '}
                <Link
                  to="/ask"
                  className="font-semibold underline decoration-amber-500 underline-offset-4"
                >
                  Ask
                </Link>
                .
              </li>
            </ul>
          </div>
        </div>
      </section>

      <section className="border bg-white p-5 shadow-sm sm:p-6" style={cardStyle}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-stone-400">
              Step 01 · Starting point
            </p>
            <h2 className="mt-1 text-xl font-bold" style={{ color: PURPLE }}>
              Fixed demo question
            </h2>
          </div>
          <DemoBadge>DEMO / SIMULATED</DemoBadge>
        </div>

        <div
          className="mt-4 rounded-2xl border p-4 sm:p-5"
          style={{ backgroundColor: '#F5F0FA', borderColor: BORDER }}
        >
          <p className="text-base font-medium leading-7 text-stone-800">
            {demo.question}
          </p>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-stone-500">
            {visible
              ? 'The two scripted attempts are currently visible.'
              : 'The scripted attempt details are hidden.'}
          </p>

          <button
            type="button"
            onClick={() => setVisible((value) => !value)}
            aria-expanded={visible}
            className="rounded-xl px-5 py-3 text-sm font-semibold text-white transition hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-[#a8c3d4] focus:ring-offset-2"
            style={{ backgroundColor: PURPLE }}
          >
            {visible ? 'Hide scripted results' : 'Show scripted results'}
          </button>
        </div>
      </section>

      {visible && (
        <>
          <div className="flex items-center gap-3 px-1">
            <div className="h-8 w-1.5 rounded-full" style={{ backgroundColor: PINK }} />
            <div>
              <h2 className="font-bold text-stone-800">
                Correction workflow
              </h2>
              <p className="text-sm text-stone-500">
                Follow the answer from the first attempt to the corrected result.
              </p>
            </div>
          </div>

          <AttemptPanel
            attempt={attempt1}
            title="Incomplete answer"
            attemptNumber="01"
            accent={{
              background: '#FCF1F4',
              border: '#F0D5DE',
              text: '#9D526D',
            }}
          />

          <section className="border bg-white p-5 shadow-sm sm:p-6" style={cardStyle}>
            <div className="flex items-start gap-3">
              <div
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl text-lg"
                style={{ backgroundColor: '#E5DBE6', color: PURPLE }}
              >
                ↻
              </div>

              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold uppercase tracking-wider text-stone-400">
                  Step 02 · Retrieval adjustment
                </p>

                <h2 className="mt-1 text-xl font-bold" style={{ color: PURPLE }}>
                  Correction query
                </h2>

                <p className="mt-2 text-sm leading-6 text-stone-600">
                  After the first attempt misses required information, the
                  scripted example rewrites the retrieval query to retain all
                  three relevant topics.
                </p>
              </div>

              <DemoBadge>SIMULATED</DemoBadge>
            </div>

            <pre
              className="mt-5 whitespace-pre-wrap break-words rounded-2xl border p-4 text-sm leading-7 text-stone-700 sm:p-5"
              style={{ backgroundColor: '#F0F5FF', borderColor: '#DCE8F0' }}
            >
              {demo.correction_query}
            </pre>

            <p className="mt-3 text-xs leading-5 text-stone-500">
              This query is part of the fixed demo payload; it is not sent to a live retrieval service.
            </p>
          </section>

          <AttemptPanel
            attempt={attempt2}
            title="Corrected answer"
            attemptNumber="02"
            accent={{
              background: '#EFF7F2',
              border: '#CFE6D8',
              text: '#367455',
            }}
          />

          <section
            className="border p-5 shadow-sm sm:p-6"
            style={{
              ...cardStyle,
              background: 'linear-gradient(120deg, #F2F7F4 0%, #F2F5FC 100%)',
            }}
          >
            <div className="flex items-start gap-3">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-white text-xl">
                ✓
              </div>

              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-wider text-stone-500">
                  Step 03 · Final result
                </p>
                <h2 className="mt-1 text-xl font-bold" style={{ color: PURPLE }}>
                  Demo outcome
                </h2>
              </div>
            </div>

            <div className="mt-5 grid gap-3 sm:grid-cols-3">
              <div className="rounded-2xl border border-white bg-white/80 p-4">
                <p className="text-xs text-stone-500">Reported attempt</p>
                <p className="mt-1 text-xl font-bold" style={{ color: PURPLE }}>
                  {demo.final_attempt_number} / {demo.attempts.length}
                </p>
              </div>

              <div className="rounded-2xl border border-white bg-white/80 p-4">
                <p className="text-xs text-stone-500">Final status</p>
                <p className="mt-1 break-words text-xl font-bold" style={{ color: GREEN }}>
                  {demo.status}
                </p>
              </div>

              <div className="rounded-2xl border border-white bg-white/80 p-4">
                <p className="text-xs text-stone-500">Result type</p>
                <p className="mt-1 text-xl font-bold" style={{ color: PURPLE }}>
                  Simulated
                </p>
              </div>
            </div>

            <p className="mt-4 text-sm leading-7 text-stone-600">
              In this scripted example, Attempt 2 is marked as passed because
              it covers network segmentation, multi-factor authentication
              (MFA), and centralized logging, with evidence references [1],
              [2], and [3]. These results illustrate the correction workflow;
              they are not live evaluation results.
            </p>

            <div className="mt-5 border-t border-white pt-4">
              <Link
                to="/ask"
                className="inline-flex items-center gap-2 rounded-xl px-5 py-3 text-sm font-semibold text-white transition hover:opacity-90"
                style={{ backgroundColor: BLUE }}
              >
                Open live Ask workspace
                <span aria-hidden="true">→</span>
              </Link>
            </div>
          </section>
        </>
      )}
    </div>
  )
}

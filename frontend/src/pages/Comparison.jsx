import { useState } from 'react'
import { USE_MOCK, compareAnswers } from '../../api/client'

// Must match EVALUATOR_ERROR in backend/app/services/evaluator.py.
const EVALUATOR_ERROR = 'evaluator_error'

// The attempt the query reports, which is not necessarily the last attempt.
function getReportedAttempt(result) {
  const finalAttemptNumber = result?.final_attempt_number

  if (finalAttemptNumber === null || finalAttemptNumber === undefined) {
    return null
  }

  return (
    (result?.attempts ?? []).find(
      (attempt) => attempt?.attempt_number === finalAttemptNumber,
    ) ?? null
  )
}

function missingEvaluationMessage(result, attempt) {
  if (!result) return 'No result was returned for this mode.'

  if (result.final_attempt_number === null || result.final_attempt_number === undefined) {
    return 'The backend did not identify a reported attempt, so no evaluation is shown.'
  }

  if (!attempt) {
    return `Reported attempt ${result.final_attempt_number} was not found in the response, so no evaluation is shown.`
  }

  return `Attempt ${attempt.attempt_number} was not evaluated, so no scores or verdict are available.`
}

function verdictLabel(evaluation) {
  if (evaluation.failure_type === EVALUATOR_ERROR) return 'Evaluator error'
  if (evaluation.passed === true) return 'Passed'
  if (evaluation.passed === false) return 'Failed'
  return 'Not available'
}

function formatScore(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) {
    return 'Not available'
  }

  const number = Number(value)
  const percentage = number >= 0 && number <= 1 ? number * 100 : number

  return `${percentage.toFixed(1)}%`
}

function ScoreCard({ label, basicValue, reliValue }) {
  const basicAvailable =
    basicValue !== null &&
    basicValue !== undefined &&
    Number.isFinite(Number(basicValue))

  const reliAvailable =
    reliValue !== null &&
    reliValue !== undefined &&
    Number.isFinite(Number(reliValue))

  const basicNumber = basicAvailable
    ? Number(basicValue) >= 0 && Number(basicValue) <= 1
      ? Number(basicValue) * 100
      : Number(basicValue)
    : null

  const reliNumber = reliAvailable
    ? Number(reliValue) >= 0 && Number(reliValue) <= 1
      ? Number(reliValue) * 100
      : Number(reliValue)
    : null

  const difference =
    basicNumber !== null && reliNumber !== null
      ? reliNumber - basicNumber
      : null

  return (
    <div className="rounded-xl border border-[#E5DBE6] bg-white p-4">
      <h3 className="text-sm font-semibold text-gray-700">{label}</h3>

      <div className="mt-3 grid grid-cols-2 gap-4">
        <div>
          <p className="text-xs text-gray-500">Basic RAG</p>
          <p className="mt-1 text-xl font-bold text-[#BBADAD]">
            {formatScore(basicValue)}
          </p>
        </div>

        <div>
          <p className="text-xs text-gray-500">RELI-RAG</p>
          <p className="mt-1 text-xl font-bold text-[#738fbd]">
            {formatScore(reliValue)}
          </p>
        </div>
      </div>

      {basicNumber !== null && reliNumber !== null && (
        <div className="mt-4 space-y-3">
          <div>
            <div className="h-2 overflow-hidden rounded-full bg-gray-100">
              <div
                className="h-full rounded-full bg-[#BBADAD]"
                style={{
                  width: `${Math.max(0, Math.min(100, basicNumber))}%`,
                }}
              />
            </div>
          </div>

          <div>
            <div className="h-2 overflow-hidden rounded-full bg-gray-100">
              <div
                className="h-full rounded-full bg-[#738fbd]"
                style={{
                  width: `${Math.max(0, Math.min(100, reliNumber))}%`,
                }}
              />
            </div>
          </div>

          <p
            className={`text-xs font-semibold ${
              difference > 0
                ? 'text-green-700'
                : difference < 0
                  ? 'text-red-700'
                  : 'text-gray-500'
            }`}
          >
            {difference > 0 ? '+' : ''}
            {difference.toFixed(1)} percentage points
          </p>
        </div>
      )}
    </div>
  )
}

function AnswerCard({ title, result, attempt, color }) {
  const evaluation = attempt?.evaluation ?? null
  const answer =
    result?.final_answer ||
    'No final answer was returned by the backend.'

  const status = result?.status || 'Unknown'

  return (
    <article className="min-w-0 rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-bold text-gray-800">{title}</h2>

        <span
          className={`rounded-full px-3 py-1 text-xs font-semibold ${color}`}
        >
          {status}
        </span>
      </div>

      <div className="mt-4 whitespace-pre-wrap break-words text-sm leading-7 text-gray-700">
        {answer}
      </div>

      <div className="mt-5 rounded-xl bg-[#F5F5F4] p-4">
        <h3 className="text-sm font-semibold text-gray-800">
          Reported attempt evaluation
          {attempt && (
            <span className="ml-1 font-normal text-gray-500">
              (attempt {attempt.attempt_number} of{' '}
              {result?.attempts?.length ?? 0})
            </span>
          )}
        </h3>

        {evaluation ? (
          <div className="mt-3 space-y-2 text-sm">
            <p className="flex items-center justify-between gap-3">
              <span className="text-gray-600">Faithfulness</span>
              <strong className="text-gray-800">
                {formatScore(evaluation.faithfulness)}
              </strong>
            </p>

            <p className="flex items-center justify-between gap-3">
              <span className="text-gray-600">Answer relevance</span>
              <strong className="text-gray-800">
                {formatScore(evaluation.answer_relevance)}
              </strong>
            </p>

            <p className="flex items-center justify-between gap-3">
              <span className="text-gray-600">Context relevance</span>
              <strong className="text-gray-800">
                {formatScore(evaluation.context_relevance)}
              </strong>
            </p>

            <div className="border-t border-gray-200 pt-3">
              <p className="text-gray-600">Evaluation result</p>
              <p
                className={`mt-1 font-semibold ${
                  evaluation.passed === true
                    ? 'text-green-700'
                    : evaluation.passed === false
                      ? 'text-red-700'
                      : 'text-gray-500'
                }`}
              >
                {verdictLabel(evaluation)}
              </p>
            </div>

            {evaluation.failure_type && (
              <p className="break-words text-gray-600">
                Failure type: {evaluation.failure_type}
              </p>
            )}

            {evaluation.feedback && (
              <p className="break-words leading-6 text-gray-600">
                {evaluation.feedback}
              </p>
            )}
          </div>
        ) : (
          <p className="mt-2 text-sm leading-6 text-gray-500">
            {missingEvaluationMessage(result, attempt)}
          </p>
        )}
      </div>

      <div className="mt-4 space-y-1 text-xs text-gray-500">
        <p>Query ID: {result?.query_id ?? 'Not available'}</p>
        <p>
          Attempts recorded: {result?.attempts?.length ?? 0}
        </p>
        {result?.final_attempt_number != null && (
          <p>Final attempt: {result.final_attempt_number}</p>
        )}
      </div>
    </article>
  )
}

function Comparison() {
  const [question, setQuestion] = useState('')
  const [documentIdsInput, setDocumentIdsInput] = useState('')
  const [topK, setTopK] = useState('5')
  const [comparison, setComparison] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleCompare(event) {
    event.preventDefault()
    setError('')
    setComparison(null)

    if (!question.trim()) {
      setError('Enter a question before starting the comparison.')
      return
    }

    const k = Number(topK)

    if (!Number.isInteger(k) || k < 1 || k > 20) {
      setError('Top K must be a whole number between 1 and 20.')
      return
    }

    const documentIds = documentIdsInput.trim()
      ? documentIdsInput
          .split(',')
          .map((id) => id.trim())
          .filter(Boolean)
          .map(Number)
      : null

    if (
      documentIds &&
      documentIds.some((id) => !Number.isInteger(id) || id <= 0)
    ) {
      setError(
        'Document IDs must be positive numbers separated by commas.',
      )
      return
    }

    setLoading(true)

    try {
      const result = await compareAnswers({
        question: question.trim(),
        documentIds,
        k,
      })

      setComparison(result)
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Comparison failed. Check the backend and try again.',
      )
    } finally {
      setLoading(false)
    }
  }

  const basicAttempt = getReportedAttempt(comparison?.basic)
  const reliAttempt = getReportedAttempt(comparison?.reli)
  const basicEvaluation = basicAttempt?.evaluation ?? null
  const reliEvaluation = reliAttempt?.evaluation ?? null

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
          Compare actual Basic RAG and RELI-RAG results from your backend.
        </p>
      </header>

      <section className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm">
        <h2 className="text-lg font-bold text-gray-800">
          Run a comparison
        </h2>

        {USE_MOCK && (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-800">
            Mock mode is enabled. Live comparison requires{' '}
            <code>VITE_USE_MOCK=false</code> in your frontend environment.
          </div>
        )}

        <form onSubmit={handleCompare} className="mt-4 space-y-4">
          <div>
            <label
              htmlFor="comparison-question"
              className="mb-2 block text-sm font-medium text-gray-700"
            >
              Your question
            </label>

            <textarea
              id="comparison-question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Example: What is network segmentation?"
              maxLength={2000}
              rows={3}
              required
              className="w-full rounded-xl border border-[#E5DBE6] px-4 py-3 text-sm outline-none transition focus:border-[#738fbd] focus:ring-2 focus:ring-[#a8c3d4]"
            />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label
                htmlFor="comparison-documents"
                className="mb-2 block text-sm font-medium text-gray-700"
              >
                Document IDs (optional)
              </label>

              <input
                id="comparison-documents"
                value={documentIdsInput}
                onChange={(event) => setDocumentIdsInput(event.target.value)}
                placeholder="Example: 1, 2"
                className="w-full rounded-xl border border-[#E5DBE6] px-4 py-3 text-sm outline-none focus:border-[#738fbd] focus:ring-2 focus:ring-[#a8c3d4]"
              />

              <p className="mt-1 text-xs leading-5 text-gray-500">
                Leave blank to use all eligible documents. Enter numeric
                backend document IDs, not filenames.
              </p>
            </div>

            <div>
              <label
                htmlFor="comparison-top-k"
                className="mb-2 block text-sm font-medium text-gray-700"
              >
                Top K retrieval results
              </label>

              <input
                id="comparison-top-k"
                type="number"
                min="1"
                max="20"
                step="1"
                value={topK}
                onChange={(event) => setTopK(event.target.value)}
                required
                className="w-full rounded-xl border border-[#E5DBE6] px-4 py-3 text-sm outline-none focus:border-[#738fbd] focus:ring-2 focus:ring-[#a8c3d4]"
              />
            </div>
          </div>

          {error && (
            <div
              role="alert"
              className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-700"
            >
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || USE_MOCK}
            className="rounded-xl bg-[#738fbd] px-5 py-3 text-sm font-semibold text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? 'Comparing answers…' : 'Compare answers'}
          </button>
        </form>
      </section>

      {loading && (
        <div
          role="status"
          className="rounded-2xl border border-[#E5DBE6] bg-white p-6 text-center text-sm text-gray-600"
        >
          The backend is running both retrieval and answer pipelines. This may
          take a little while.
        </div>
      )}

      {comparison && (
        <>
          <section className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
              Comparison question
            </p>

            <h2 className="mt-2 break-words text-lg font-semibold text-gray-800">
              {comparison.question || question}
            </h2>

            <p className="mt-2 break-all text-xs text-gray-500">
              Comparison ID: {comparison.compare_id || 'Not available'}
            </p>

            {comparison.benchmark_run_id && (
              <p className="mt-1 break-all text-xs text-gray-500">
                Benchmark run: {comparison.benchmark_run_id}
              </p>
            )}
          </section>

          <section className="grid grid-cols-1 gap-5 xl:grid-cols-2">
            <AnswerCard
              title="Basic RAG"
              result={comparison.basic}
              attempt={basicAttempt}
              color="bg-[#E5DBE6] text-[#554188]"
            />

            <AnswerCard
              title="RELI-RAG"
              result={comparison.reli}
              attempt={reliAttempt}
              color="bg-[#DCE8F0] text-[#385A78]"
            />
          </section>

          <section className="rounded-2xl border border-[#E5DBE6] bg-[#F5F5F4] p-5">
            <h2 className="text-lg font-bold text-gray-800">
              Quality score comparison
            </h2>

            <p className="mt-1 text-sm leading-6 text-gray-500">
              These scores come from the evaluation of the attempt each query
              reports (its final attempt number), which is not necessarily the
              last attempt. Missing values are not estimated or fabricated.
            </p>

            <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-3">
              <ScoreCard
                label="Faithfulness"
                basicValue={basicEvaluation?.faithfulness}
                reliValue={reliEvaluation?.faithfulness}
              />

              <ScoreCard
                label="Answer relevance"
                basicValue={basicEvaluation?.answer_relevance}
                reliValue={reliEvaluation?.answer_relevance}
              />

              <ScoreCard
                label="Context relevance"
                basicValue={basicEvaluation?.context_relevance}
                reliValue={reliEvaluation?.context_relevance}
              />
            </div>
          </section>
        </>
      )}
    </div>
  )
}

export default Comparison

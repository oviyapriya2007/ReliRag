
import { useState } from "react";
import { USE_MOCK, compareAnswers } from "../../api/client";

const C = {
  purple: "#554188",
  lavender: "#F0EBFA",
  blue: "#738FBD",
  blueLight: "#EAF1FB",
  pink: "#DB88A4",
  pinkLight: "#FBEAF0",
  green: "#24734D",
  greenLight: "#E5F5EC",
  red: "#A33C4A",
  redLight: "#FCEBED",
  amber: "#94651A",
  amberLight: "#FFF4D9",
  ink: "#332D40",
  muted: "#777184",
  border: "#EAE5F0",
  canvas: "#FAF9FC",
  white: "#FFFFFF",
};

const panel = {
  background: C.white,
  border: `1px solid ${C.border}`,
  borderRadius: 20,
  boxShadow: "0 4px 18px rgba(85, 65, 136, 0.035)",
};

// Must match EVALUATOR_ERROR in backend/app/services/evaluator.py.
const EVALUATOR_ERROR = "evaluator_error";

// Use the attempt explicitly reported by the backend.
function getReportedAttempt(result) {
  const finalAttemptNumber = result?.final_attempt_number;

  if (finalAttemptNumber == null) return null;

  return (
    (result?.attempts ?? []).find(
      (attempt) =>
        Number(attempt?.attempt_number) === Number(finalAttemptNumber),
    ) ?? null
  );
}

function missingEvaluationMessage(result, attempt) {
  if (!result) return "No result was returned for this mode.";

  if (
    result.final_attempt_number === null ||
    result.final_attempt_number === undefined
  ) {
    return "The backend did not identify a reported attempt, so no evaluation is shown.";
  }

  if (!attempt) {
    return `Reported attempt ${result.final_attempt_number} was not found in the response, so no evaluation is shown.`;
  }

  return `Attempt ${attempt.attempt_number} was not evaluated, so no scores or verdict are available.`;
}

function verdictLabel(evaluation) {
  if (evaluation?.failure_type === EVALUATOR_ERROR) {
    return "Evaluator error";
  }

  if (evaluation?.passed === true) return "Passed";
  if (evaluation?.passed === false) return "Failed";

  return "Not available";
}

function verdictStyle(value) {
  const status = String(value ?? "").toUpperCase();

  if (["PASSED", "PASS", "SUPPORTED", "CORRECT", "ANSWERED"].includes(status)) {
    return { color: C.green, background: C.greenLight };
  }

  if (status === "CORRECTED") {
    return { color: C.amber, background: C.amberLight };
  }

  if (
    [
      "FAILED",
      "FAIL",
      "UNSUPPORTED",
      "INSUFFICIENT_EVIDENCE",
      "FAILED_AFTER_CORRECTION",
      "EVALUATOR ERROR",
    ].includes(status)
  ) {
    return { color: C.red, background: C.redLight };
  }

  return { color: C.muted, background: "#F2F0F5" };
}

function normalizedScore(value) {
  if (
    value === null ||
    value === undefined ||
    value === "" ||
    !Number.isFinite(Number(value))
  ) {
    return null;
  }

  const number = Number(value);
  return number >= 0 && number <= 1 ? number * 100 : number;
}

function formatScore(value) {
  const score = normalizedScore(value);
  return score === null ? "N/A" : `${score.toFixed(1)}%`;
}

function SectionHeading({ eyebrow, title, description, icon }) {
  return (
    <div className="flex flex-wrap items-start gap-3">
      {icon && (
        <div
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl text-xl"
          style={{ background: C.lavender, color: C.purple }}
        >
          {icon}
        </div>
      )}

      <div className="min-w-0 flex-1">
        {eyebrow && (
          <p
            className="text-xs font-bold uppercase tracking-[0.16em]"
            style={{ color: C.blue }}
          >
            {eyebrow}
          </p>
        )}

        <h2
          className="mt-1 text-xl font-bold tracking-tight"
          style={{ color: C.ink }}
        >
          {title}
        </h2>

        {description && (
          <p className="mt-1 text-sm leading-6" style={{ color: C.muted }}>
            {description}
          </p>
        )}
      </div>
    </div>
  );
}

function ScoreCard({ label, basicValue, reliValue }) {
  const basicNumber = normalizedScore(basicValue);
  const reliNumber = normalizedScore(reliValue);

  const difference =
    basicNumber !== null && reliNumber !== null
      ? reliNumber - basicNumber
      : null;

  const bars = [
    {
      label: "Basic RAG",
      value: basicNumber,
      color: "#B7A9C9",
      tint: "#F2EEF7",
    },
    {
      label: "Attest",
      value: reliNumber,
      color: C.blue,
      tint: C.blueLight,
    },
  ];

  return (
    <article
      className="min-w-0 rounded-2xl border p-4 sm:p-5"
      style={{ background: C.white, borderColor: C.border }}
    >
      <h3 className="text-sm font-bold" style={{ color: C.ink }}>
        {label}
      </h3>

      <div className="mt-4 grid grid-cols-2 gap-3">
        <div className="rounded-xl p-3" style={{ background: "#F2EEF7" }}>
          <p className="text-xs" style={{ color: C.muted }}>
            Basic RAG
          </p>
          <p className="mt-2 text-xl font-bold" style={{ color: "#78658F" }}>
            {formatScore(basicValue)}
          </p>
        </div>

        <div className="rounded-xl p-3" style={{ background: C.blueLight }}>
          <p className="text-xs" style={{ color: C.blue }}>
            Attest
          </p>
          <p className="mt-2 text-xl font-bold" style={{ color: "#496794" }}>
            {formatScore(reliValue)}
          </p>
        </div>
      </div>

      <div className="mt-5 space-y-4">
        {bars.map((bar) => {
          const width =
            bar.value === null ? 0 : Math.max(0, Math.min(100, bar.value));

          return (
            <div key={bar.label}>
              <div className="mb-1.5 flex justify-between gap-2 text-xs">
                <span style={{ color: C.muted }}>{bar.label}</span>
                <span className="font-semibold" style={{ color: C.ink }}>
                  {bar.value === null ? "N/A" : `${bar.value.toFixed(1)}%`}
                </span>
              </div>

              <div
                className="h-2.5 overflow-hidden rounded-full"
                style={{ background: bar.tint }}
                role="progressbar"
                aria-label={`${label} — ${bar.label}`}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={width}
              >
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{ width: `${width}%`, background: bar.color }}
                />
              </div>
            </div>
          );
        })}
      </div>

      <div
        className="mt-5 rounded-xl p-3"
        style={{
          background:
            difference === null
              ? C.canvas
              : difference > 0
                ? C.greenLight
                : difference < 0
                  ? C.redLight
                  : C.canvas,
        }}
      >
        <p
          className="text-xs font-bold"
          style={{
            color:
              difference === null
                ? C.muted
                : difference > 0
                  ? C.green
                  : difference < 0
                    ? C.red
                    : C.muted,
          }}
        >
          {difference === null
            ? "Difference unavailable — one or both scores are missing."
            : `${difference > 0 ? "+" : ""}${difference.toFixed(1)} percentage points`}
        </p>
      </div>
    </article>
  );
}

function MetricRow({ label, value }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2">
      <span className="text-sm" style={{ color: C.muted }}>
        {label}
      </span>
      <strong className="text-right text-sm" style={{ color: C.ink }}>
        {value}
      </strong>
    </div>
  );
}

function AnswerCard({ title, result, attempt, system }) {
  const evaluation = attempt?.evaluation ?? null;
  const isReli = system === "reli";

  const answerTint = isReli ? "#F7F5FC" : "#F7F9FC";
  const accent = isReli ? C.purple : C.blue;

  const status = result?.status || "Unknown";

  return (
    <article
      className="min-w-0 overflow-hidden rounded-2xl border"
      style={{ ...panel, borderColor: isReli ? "#DAD0EE" : "#D6E2F4" }}
    >
      <div
        className="p-5 sm:p-6"
        style={{ background: isReli ? C.lavender : C.blueLight }}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p
              className="text-xs font-bold uppercase tracking-[0.14em]"
              style={{ color: accent }}
            >
              {isReli ? "Correction-enabled pipeline" : "Baseline pipeline"}
            </p>

            <h2 className="mt-1 text-xl font-bold" style={{ color: C.ink }}>
              {title}
            </h2>
          </div>

          <span
            className="rounded-full px-3 py-1.5 text-xs font-bold"
            style={verdictStyle(status)}
          >
            {status}
          </span>
        </div>
      </div>

      <div className="p-5 sm:p-6">
        <h3 className="text-sm font-bold" style={{ color: C.ink }}>
          Generated answer
        </h3>

        <div
          className="mt-3 whitespace-pre-wrap break-words rounded-xl p-4 text-sm leading-7"
          style={{ background: answerTint, color: C.ink }}
        >
          {result?.final_answer || "No final answer was returned by the backend."}
        </div>

        <div
          className="mt-5 rounded-2xl border p-4"
          style={{ borderColor: C.border }}
        >
          <h3 className="text-sm font-bold" style={{ color: C.ink }}>
            Reported attempt evaluation
          </h3>

          {attempt && (
            <p className="mt-1 text-xs" style={{ color: C.muted }}>
              Attempt {attempt.attempt_number} of {result?.attempts?.length ?? 0}
            </p>
          )}

          {evaluation ? (
            <div className="mt-3 divide-y" style={{ borderColor: C.border }}>
              <MetricRow
                label="Faithfulness"
                value={formatScore(evaluation.faithfulness)}
              />
              <MetricRow
                label="Answer relevance"
                value={formatScore(evaluation.answer_relevance)}
              />
              <MetricRow
                label="Context relevance"
                value={formatScore(evaluation.context_relevance)}
              />

              <div className="pt-3">
                <p className="text-xs font-semibold" style={{ color: C.muted }}>
                  Evaluation result
                </p>
                <span
                  className="mt-2 inline-flex rounded-full px-3 py-1.5 text-xs font-bold"
                  style={verdictStyle(verdictLabel(evaluation))}
                >
                  {verdictLabel(evaluation)}
                </span>
              </div>

              {evaluation.failure_type && (
                <div className="pt-3">
                  <p className="text-xs font-semibold" style={{ color: C.muted }}>
                    Failure type
                  </p>
                  <p className="mt-1 break-words text-sm" style={{ color: C.ink }}>
                    {evaluation.failure_type}
                  </p>
                </div>
              )}

              {evaluation.feedback && (
                <div className="pt-3">
                  <p className="text-xs font-semibold" style={{ color: C.muted }}>
                    Evaluator feedback
                  </p>
                  <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-6" style={{ color: C.ink }}>
                    {evaluation.feedback}
                  </p>
                </div>
              )}
            </div>
          ) : (
            <p
              className="mt-3 rounded-xl p-3 text-sm leading-6"
              style={{ background: C.canvas, color: C.muted }}
            >
              {missingEvaluationMessage(result, attempt)}
            </p>
          )}
        </div>

        <div className="mt-5 space-y-1 border-t pt-4" style={{ borderColor: C.border }}>
          <p className="break-all text-xs" style={{ color: C.muted }}>
            Query ID: {result?.query_id ?? "Not available"}
          </p>
          <p className="text-xs" style={{ color: C.muted }}>
            Attempts recorded: {result?.attempts?.length ?? 0}
          </p>
          {result?.final_attempt_number != null && (
            <p className="text-xs" style={{ color: C.muted }}>
              Reported attempt: {result.final_attempt_number}
            </p>
          )}
        </div>
      </div>
    </article>
  );
}

function Comparison() {
  const [question, setQuestion] = useState("");
  const [documentIdsInput, setDocumentIdsInput] = useState("");
  const [topK, setTopK] = useState("5");
  const [comparison, setComparison] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleCompare(event) {
    event.preventDefault();
    setError("");
    setComparison(null);

    if (!question.trim()) {
      setError("Enter a question before starting the comparison.");
      return;
    }

    const k = Number(topK);

    if (!Number.isInteger(k) || k < 1 || k > 20) {
      setError("Top K must be a whole number between 1 and 20.");
      return;
    }

    const documentIds = documentIdsInput.trim()
      ? documentIdsInput
          .split(",")
          .map((id) => id.trim())
          .filter(Boolean)
          .map(Number)
      : null;

    if (
      documentIds &&
      documentIds.some((id) => !Number.isInteger(id) || id <= 0)
    ) {
      setError("Document IDs must be positive numbers separated by commas.");
      return;
    }

    setLoading(true);

    try {
      const result = await compareAnswers({
        question: question.trim(),
        documentIds,
        k,
      });

      setComparison(result);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Comparison failed. Check the backend and try again.",
      );
    } finally {
      setLoading(false);
    }
  }

  const basicAttempt = getReportedAttempt(comparison?.basic);
  const reliAttempt = getReportedAttempt(comparison?.reli);
  const basicEvaluation = basicAttempt?.evaluation ?? null;
  const reliEvaluation = reliAttempt?.evaluation ?? null;

  return (
    <div className="comparison-dashboard space-y-6">
      <header
        className="relative overflow-hidden p-6 sm:p-8"
        style={{
          ...panel,
          background:
            "linear-gradient(125deg, #F0EBFA 0%, #FDF7FA 58%, #EDF3FC 100%)",
        }}
      >
        <div
          className="pointer-events-none absolute -right-8 -top-12 h-40 w-40 rounded-full"
          style={{ background: "#FFFFFF75" }}
        />
        <div
          className="pointer-events-none absolute -bottom-14 right-28 h-28 w-28 rounded-full"
          style={{ background: "#DB88A425" }}
        />

        <div className="relative">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className="rounded-full px-3 py-1.5 text-xs font-bold"
              style={{ background: "#FFFFFFC9", color: C.purple }}
            >
              Attest
            </span>
            <span
              className="rounded-full px-3 py-1.5 text-xs font-semibold"
              style={{ background: "#FFFFFFA8", color: C.muted }}
            >
              Benchmark workspace
            </span>
          </div>

          <h1
            className="mt-4 text-3xl font-bold tracking-tight sm:text-4xl"
            style={{ color: C.purple }}
          >
            Comparison Lab
          </h1>

          <p className="mt-3 max-w-2xl text-sm leading-7 sm:text-base" style={{ color: C.muted }}>
            Compare Basic RAG and Attest using the same question and inspect their answers, evaluation scores, and reported attempt details.
          </p>

          <div className="mt-5 flex flex-wrap gap-2">
            <span
              className="rounded-full px-3 py-2 text-xs font-semibold"
              style={{ background: "#FFFFFFC9", color: C.purple }}
            >
              2 systems
            </span>
            <span
              className="rounded-full px-3 py-2 text-xs font-semibold"
              style={{ background: "#FFFFFFC9", color: C.purple }}
            >
              3 evaluation metrics
            </span>
            <span
              className="rounded-full px-3 py-2 text-xs font-semibold"
              style={{ background: "#FFFFFFC9", color: C.purple }}
            >
              Live backend comparison
            </span>
          </div>
        </div>
      </header>

      <section className="p-5 sm:p-6" style={panel}>
        <SectionHeading
          eyebrow="Configure experiment"
          title="Run a comparison"
          description="Choose your question, optionally restrict the document set, and configure the number of retrieval results."
          icon="⚙"
        />

        {USE_MOCK && (
          <div
            className="mt-5 rounded-xl border p-4 text-sm leading-6"
            style={{
              borderColor: "#F0DCA8",
              background: C.amberLight,
              color: C.amber,
            }}
          >
            <strong>Mock mode is enabled.</strong> Live comparison requires{" "}
            <code>VITE_USE_MOCK=false</code> in your frontend environment.
          </div>
        )}

        <form onSubmit={handleCompare} className="mt-6 space-y-5">
          <div>
            <label
              htmlFor="comparison-question"
              className="mb-2 block text-sm font-bold"
              style={{ color: C.ink }}
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
              className="w-full rounded-2xl border px-4 py-3 text-sm leading-6 outline-none transition focus:ring-2"
              style={{
                borderColor: C.border,
                color: C.ink,
                background: "#FDFCFD",
                "--tw-ring-color": "#A8C3D4",
              }}
            />

            <div className="mt-1 flex justify-end">
              <span className="text-xs" style={{ color: C.muted }}>
                {question.length}/2000 characters
              </span>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <div>
              <label
                htmlFor="comparison-documents"
                className="mb-2 block text-sm font-bold"
                style={{ color: C.ink }}
              >
                Document IDs
                <span className="ml-2 font-normal" style={{ color: C.muted }}>
                  Optional
                </span>
              </label>

              <input
                id="comparison-documents"
                value={documentIdsInput}
                onChange={(event) => setDocumentIdsInput(event.target.value)}
                placeholder="e.g. 1, 2"
                className="w-full rounded-2xl border px-4 py-3 text-sm outline-none transition focus:ring-2"
                style={{
                  borderColor: C.border,
                  color: C.ink,
                  background: "#FDFCFD",
                  "--tw-ring-color": "#A8C3D4",
                }}
              />

              <p className="mt-2 text-xs leading-5" style={{ color: C.muted }}>
                Leave blank to use all eligible documents. Enter numeric backend IDs, not filenames.
              </p>
            </div>

            <div>
              <label
                htmlFor="comparison-top-k"
                className="mb-2 block text-sm font-bold"
                style={{ color: C.ink }}
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
                className="w-full rounded-2xl border px-4 py-3 text-sm outline-none transition focus:ring-2"
                style={{
                  borderColor: C.border,
                  color: C.ink,
                  background: "#FDFCFD",
                  "--tw-ring-color": "#A8C3D4",
                }}
              />

              <p className="mt-2 text-xs leading-5" style={{ color: C.muted }}>
                Choose a whole number between 1 and 20.
              </p>
            </div>
          </div>

          {error && (
            <div
              role="alert"
              className="rounded-2xl border p-4 text-sm leading-6"
              style={{
                borderColor: "#F2CDD5",
                background: C.redLight,
                color: C.red,
              }}
            >
              <strong>Comparison could not run.</strong>
              <p className="mt-1">{error}</p>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={loading || USE_MOCK}
              className="inline-flex items-center justify-center gap-2 rounded-xl px-5 py-3 text-sm font-bold text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              style={{ background: C.purple }}
            >
              {loading ? (
                <>
                  <span
                    className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent"
                    aria-hidden="true"
                  />
                  Comparing answers...
                </>
              ) : (
                "⇄  Compare answers"
              )}
            </button>

            <span className="text-xs" style={{ color: C.muted }}>
              Both systems are evaluated using the returned backend results.
            </span>
          </div>
        </form>
      </section>

      {loading && (
        <section className="p-6 sm:p-8" style={panel} role="status">
          <div className="flex items-center gap-4">
            <div
              className="h-8 w-8 animate-spin rounded-full border-2 border-t-transparent"
              style={{ borderColor: C.purple, borderTopColor: "transparent" }}
            />
            <div>
              <h2 className="font-bold" style={{ color: C.ink }}>
                Running comparison
              </h2>
              <p className="mt-1 text-sm leading-6" style={{ color: C.muted }}>
                The backend is running both retrieval and answer pipelines. This may take a little while.
              </p>
            </div>
          </div>
        </section>
      )}

      {comparison && (
        <>
          <section className="p-5 sm:p-6" style={panel}>
            <SectionHeading
              eyebrow="Experiment summary"
              title="Comparison results"
              description="Review the shared question and identifiers returned by the backend."
              icon="▤"
            />

            <div
              className="mt-5 rounded-2xl p-4 sm:p-5"
              style={{ background: C.canvas }}
            >
              <p className="text-xs font-bold uppercase tracking-wide" style={{ color: C.blue }}>
                Comparison question
              </p>

              <h3 className="mt-2 break-words text-lg font-semibold leading-7" style={{ color: C.ink }}>
                {comparison.question || question}
              </h3>
            </div>

            <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div
                className="min-w-0 rounded-xl border p-4"
                style={{ borderColor: C.border }}
              >
                <p className="text-xs font-semibold" style={{ color: C.muted }}>
                  Comparison ID
                </p>
                <p className="mt-2 break-all text-sm font-semibold" style={{ color: C.purple }}>
                  {comparison.compare_id || "Not available"}
                </p>
              </div>

              <div
                className="min-w-0 rounded-xl border p-4"
                style={{ borderColor: C.border }}
              >
                <p className="text-xs font-semibold" style={{ color: C.muted }}>
                  Benchmark run
                </p>
                <p className="mt-2 break-all text-sm font-semibold" style={{ color: C.purple }}>
                  {comparison.benchmark_run_id || "Not available"}
                </p>
              </div>
            </div>
          </section>

          <section>
            <SectionHeading
              eyebrow="Side-by-side analysis"
              title="Generated answers"
              description="Inspect each system's answer, evaluator verdict, and reported attempt."
              icon="⇄"
            />

            <div className="mt-4 grid grid-cols-1 gap-5 xl:grid-cols-2">
              <AnswerCard
                title="Basic RAG"
                result={comparison.basic}
                attempt={basicAttempt}
                system="basic"
              />

              <AnswerCard
                title="Attest"
                result={comparison.reli}
                attempt={reliAttempt}
                system="reli"
              />
            </div>
          </section>

          <section className="p-5 sm:p-6" style={panel}>
            <SectionHeading
              eyebrow="Metric breakdown"
              title="Quality score comparison"
              description="Compare faithfulness, answer relevance, and context relevance. Missing values remain unavailable rather than being estimated."
              icon="▥"
            />

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

          <div
            className="flex items-start gap-3 rounded-2xl border p-4"
            style={{ borderColor: C.border, background: C.lavender }}
          >
            <span className="text-lg" style={{ color: C.purple }}>ⓘ</span>
            <p className="text-sm leading-6" style={{ color: C.ink }}>
              <strong>How to read these results:</strong> each system's scores come from the attempt identified by its backend-reported final attempt number. This may not be the last recorded attempt. A missing score or verdict is shown as unavailable, not treated as zero.
            </p>
          </div>
        </>
      )}
    </div>
  );
}

export default Comparison;

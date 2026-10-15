import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getQuery, USE_MOCK } from "../../api/client";

const PURPLE = "#554188";
const BLUE = "#738fbd";
const BORDER = "#E5DBE6";
const GREEN = "#166534";
const RED = "#991B1B";

const cardStyle = {
  borderColor: BORDER,
  borderRadius: "16px",
};

const PIPELINE_STAGES = [
  { key: "retrieve", label: "Retrieve" },
  { key: "generate", label: "Generate" },
  { key: "evaluate", label: "Evaluate" },
  { key: "correct", label: "Correct" },
  { key: "reevaluate", label: "Re-evaluate" },
];

const DEFAULT_SETTINGS = {
  topK: 5,
  evaluatorThreshold: 0.7,
  similarityGate: 0.5,
};

function formatLabel(value) {
  if (value === null || value === undefined || value === "") {
    return "Not available";
  }

  return String(value).replaceAll("_", " ");
}

function formatScore(value) {
  if (
    value === null ||
    value === undefined ||
    value === "" ||
    !Number.isFinite(Number(value))
  ) {
    return "N/A";
  }

  const score = Number(value);
  return `${Math.round(score <= 1 ? score * 100 : score)}%`;
}

function formatVerdict(verdict) {
  return formatLabel(verdict || "Not evaluated").toUpperCase();
}

function verdictStyle(verdict) {
  const value = String(verdict ?? "").toUpperCase();

  if (["PASSED", "PASS"].includes(value)) {
    return { color: GREEN, backgroundColor: "#DCFCE7" };
  }

  if (["CORRECTED"].includes(value)) {
    return { color: "#92400E", backgroundColor: "#FEF3C7" };
  }

  if (
    ["FAILED_AFTER_CORRECTION", "FAILED", "FAIL"].includes(value)
  ) {
    return { color: RED, backgroundColor: "#FEE2E2" };
  }

  return { color: "#57534E", backgroundColor: "#F5F5F4" };
}

function ScoreCard({ title, value, description, color }) {
  return (
    <article
      className="rounded-xl border bg-white p-4"
      style={{ borderColor: color, borderRadius: "12px" }}
    >
      <p className="text-sm font-semibold" style={{ color }}>
        {title}
      </p>
      <p className="mt-2 text-3xl font-bold" style={{ color }}>
        {formatScore(value)}
      </p>
      {description && (
        <p className="mt-2 text-xs leading-5 text-gray-500">
          {description}
        </p>
      )}
    </article>
  );
}

function getAttemptScore(attempt, key) {
  const value = attempt?.evaluation?.[key];

  if (
    value === null ||
    value === undefined ||
    value === "" ||
    !Number.isFinite(Number(value))
  ) {
    return null;
  }

  const score = Number(value);
  return score <= 1 ? score * 100 : score;
}

function ScoreComparison({ title, metric, before, after }) {
  const beforeScore = getAttemptScore(before, metric);
  const afterScore = getAttemptScore(after, metric);

  const difference =
    beforeScore === null || afterScore === null
      ? null
      : Math.round((afterScore - beforeScore) * 10) / 10;

  return (
    <article
      className="rounded-xl border bg-white p-4"
      style={{ borderColor: BORDER }}
    >
      <h3 className="text-sm font-semibold text-gray-700">{title}</h3>

      <div className="mt-3 grid grid-cols-2 gap-3">
        <div className="rounded-lg bg-red-50 p-3">
          <p className="text-xs text-red-700">Before</p>
          <p className="mt-1 text-xl font-bold text-red-800">
            {formatScore(beforeScore)}
          </p>
        </div>

        <div className="rounded-lg bg-green-50 p-3">
          <p className="text-xs text-green-700">After</p>
          <p className="mt-1 text-xl font-bold text-green-800">
            {formatScore(afterScore)}
          </p>
        </div>
      </div>

      {difference !== null && (
        <p
          className="mt-3 text-xs font-semibold"
          style={{
            color:
              difference > 0
                ? GREEN
                : difference < 0
                  ? RED
                  : "#57534E",
          }}
        >
          {difference > 0 ? "+" : ""}
          {difference} percentage points
        </p>
      )}
    </article>
  );
}

function AnswerComparison({ before, after }) {
  const beforeText = before?.answer ?? "";
  const afterText = after?.answer ?? "";

  const splitSentences = (text) =>
    text
      .split(/(?<=[.!?])\s+/)
      .map((sentence) => sentence.trim())
      .filter(Boolean);

  const beforeSentences = splitSentences(beforeText);
  const afterSentences = splitSentences(afterText);

  const removed = beforeSentences.filter(
    (sentence) => !afterSentences.includes(sentence)
  );

  const added = afterSentences.filter(
    (sentence) => !beforeSentences.includes(sentence)
  );

  return (
    <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
      <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
        Before / After comparison
      </h2>
      <p className="mt-2 text-sm text-gray-500">
        Compare the original answer with the latest correction attempt.
        Differences below are based on complete sentences.
      </p>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <article className="rounded-xl border border-red-200 bg-red-50/40 p-4">
          <h3 className="font-bold text-red-800">Original answer</h3>
          <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-gray-700">
            {beforeText || "No original answer was returned."}
          </p>
        </article>

        <article className="rounded-xl border border-green-200 bg-green-50/40 p-4">
          <h3 className="font-bold text-green-800">Latest answer</h3>
          <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-gray-700">
            {afterText || "No latest answer was returned."}
          </p>
        </article>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-xl border p-4" style={{ borderColor: BORDER }}>
          <h3 className="text-sm font-bold text-red-800">
            Removed or changed sentences
          </h3>

          {removed.length ? (
            <ul className="mt-3 space-y-2">
              {removed.map((sentence, index) => (
                <li
                  key={`${index}-${sentence}`}
                  className="rounded-lg bg-red-50 p-3 text-sm leading-6 text-red-800"
                >
                  <span className="line-through">{sentence}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-gray-500">
              No removed sentences detected.
            </p>
          )}
        </div>

        <div className="rounded-xl border p-4" style={{ borderColor: BORDER }}>
          <h3 className="text-sm font-bold text-green-800">
            Added or changed sentences
          </h3>

          {added.length ? (
            <ul className="mt-3 space-y-2">
              {added.map((sentence, index) => (
                <li
                  key={`${index}-${sentence}`}
                  className="rounded-lg bg-green-50 p-3 text-sm leading-6 text-green-800"
                >
                  {sentence}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-gray-500">
              No added sentences detected.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

function PipelineStepper({ attempts }) {
  const hasCorrection = attempts.length > 1;
  const latest = attempts[attempts.length - 1];
  const first = attempts[0];
  const latestEvaluation = latest?.evaluation;
  const firstEvaluation = first?.evaluation;

  const stages = [
    {
      ...PIPELINE_STAGES[0],
      done: Boolean(
        first?.retrieval?.length || first?.retrieved_evidence?.length
      ),
      detail:
        first?.timings?.retrieve_ms != null
          ? `${first.timings.retrieve_ms} ms`
          : "Timing unavailable",
    },
    {
      ...PIPELINE_STAGES[1],
      done: Boolean(first?.answer),
      detail:
        first?.timings?.generate_ms != null
          ? `${first.timings.generate_ms} ms`
          : "Timing unavailable",
    },
    {
      ...PIPELINE_STAGES[2],
      done: Boolean(firstEvaluation),
      detail: firstEvaluation
        ? formatVerdict(
            firstEvaluation.passed === true
              ? "PASSED"
              : firstEvaluation.passed === false
                ? "FAILED"
                : "NOT EVALUATED"
          )
        : "Evaluation unavailable",
    },
    {
      ...PIPELINE_STAGES[3],
      done: hasCorrection,
      detail: hasCorrection
        ? formatLabel(latest?.strategy || "Correction attempt recorded")
        : "No separate correction attempt recorded",
    },
    {
      ...PIPELINE_STAGES[4],
      done: hasCorrection && Boolean(latestEvaluation),
      detail:
        hasCorrection && latestEvaluation
          ? formatVerdict(
              latestEvaluation.passed === true
                ? "PASSED"
                : latestEvaluation.passed === false
                  ? "FAILED"
                  : "NOT EVALUATED"
            )
          : "Re-evaluation unavailable",
    },
  ];

  return (
    <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
      <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
        Correction pipeline
      </h2>
      <p className="mt-2 text-sm text-gray-500">
        Stage indicators are inferred from the attempt data returned by the
        backend. Unavailable timings are not estimated.
      </p>

      <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {stages.map((stage, index) => (
          <article
            key={stage.key}
            className="rounded-xl border p-3"
            style={{
              borderColor: stage.done ? "#86EFAC" : BORDER,
              backgroundColor: stage.done ? "#F0FDF4" : "#FFFFFF",
            }}
          >
            <div className="flex items-center gap-2">
              <span
                className="flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold"
                style={{
                  backgroundColor: stage.done ? "#DCFCE7" : "#F5F5F4",
                  color: stage.done ? GREEN : "#57534E",
                }}
              >
                {stage.done ? "✓" : index + 1}
              </span>
              <h3 className="text-sm font-bold text-gray-800">
                {stage.label}
              </h3>
            </div>
            <p className="mt-3 text-xs leading-5 text-gray-600">
              {stage.detail}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}

function CorrectionReason({ first, latest }) {
  const evaluation = first?.evaluation;
  const latestEvaluation = latest?.evaluation;

  const failureType =
    evaluation?.failure_type ??
    latestEvaluation?.failure_type ??
    first?.failure_type ??
    latest?.failure_type;

  const feedback =
    evaluation?.feedback ??
    latestEvaluation?.feedback ??
    first?.feedback ??
    latest?.feedback;

  const originalQuestion = first?.retrieval_query ?? null;
  const rewrittenQuestion = latest?.retrieval_query ?? null;

  return (
    <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
      <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
        Correction reason
      </h2>
      <p className="mt-2 text-sm text-gray-500">
        Review the evaluator's reported failure and the retrieval queries
        associated with the attempts.
      </p>

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-xl border p-4" style={{ borderColor: BORDER }}>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Failure type
          </p>
          <p className="mt-2 text-sm font-semibold text-gray-800">
            {formatLabel(failureType)}
          </p>
        </div>

        <div className="rounded-xl border p-4" style={{ borderColor: BORDER }}>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Evaluator feedback
          </p>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-700">
            {feedback || "No evaluator feedback was returned."}
          </p>
        </div>

        <div className="rounded-xl border p-4" style={{ borderColor: BORDER }}>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Original retrieval query
          </p>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-700">
            {originalQuestion || "Not available"}
          </p>
        </div>

        <div className="rounded-xl border p-4" style={{ borderColor: BORDER }}>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Latest retrieval query
          </p>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-700">
            {rewrittenQuestion || "Not available"}
          </p>
        </div>
      </div>

      {first && latest && first === latest && (
        <p className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
          Only one attempt is available. A separate correction attempt has
          not been returned for this query.
        </p>
      )}
    </section>
  );
}

function SettingsPanel() {
  const [settings, setSettings] = useState(() => {
    try {
      const saved = localStorage.getItem("relirag_evaluation_settings");
      const parsed = saved ? JSON.parse(saved) : {};

      return {
        ...DEFAULT_SETTINGS,
        ...parsed,
      };
    } catch {
      return DEFAULT_SETTINGS;
    }
  });

  const updateSetting = (key, value) => {
    setSettings((current) => {
      const updated = { ...current, [key]: value };

      try {
        localStorage.setItem(
          "relirag_evaluation_settings",
          JSON.stringify(updated)
        );
      } catch {
        // Keep the setting available for the current page session.
      }

      return updated;
    });
  };

  const resetSettings = () => {
    setSettings(DEFAULT_SETTINGS);

    try {
      localStorage.setItem(
        "relirag_evaluation_settings",
        JSON.stringify(DEFAULT_SETTINGS)
      );
    } catch {
      // Retain the default state if storage is unavailable.
    }
  };

  return (
    <details className="border bg-white p-5 shadow-sm" style={cardStyle}>
      <summary
        className="cursor-pointer text-xl font-bold"
        style={{ color: PURPLE }}
      >
        Evaluation settings
      </summary>

      <p className="mt-2 text-sm text-gray-500">
        These preferences are saved in this browser. Top-k is sent with new
        queries from Ask. The evaluator threshold and similarity gate are
        frontend preferences and do not change backend processing.
      </p>

      <div className="mt-5 space-y-5">
        <label className="block">
          <span className="flex items-center justify-between gap-3 text-sm font-semibold text-gray-700">
            Top-k retrieval
            <span>{settings.topK}</span>
          </span>
          <input
            type="range"
            min="1"
            max="10"
            step="1"
            value={settings.topK}
            onChange={(event) =>
              updateSetting("topK", Number(event.target.value))
            }
            className="mt-3 w-full accent-purple-700"
          />
          <span className="text-xs text-gray-500">
            Number of passages requested during retrieval for new queries.
          </span>
        </label>

        <label className="block">
          <span className="flex items-center justify-between gap-3 text-sm font-semibold text-gray-700">
            Evaluator threshold
            <span>{settings.evaluatorThreshold.toFixed(2)}</span>
          </span>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={settings.evaluatorThreshold}
            onChange={(event) =>
              updateSetting("evaluatorThreshold", Number(event.target.value))
            }
            className="mt-3 w-full accent-purple-700"
          />
          <span className="text-xs text-gray-500">
            Minimum score used by the frontend threshold assessment below.
          </span>
        </label>

        <label className="block">
          <span className="flex items-center justify-between gap-3 text-sm font-semibold text-gray-700">
            Similarity gate
            <span>{settings.similarityGate.toFixed(2)}</span>
          </span>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={settings.similarityGate}
            onChange={(event) =>
              updateSetting("similarityGate", Number(event.target.value))
            }
            className="mt-3 w-full accent-purple-700"
          />
          <span className="text-xs text-gray-500">
            Preferred minimum similarity for inspecting retrieved evidence.
            This setting does not filter backend retrieval.
          </span>
        </label>

        <button
          type="button"
          onClick={resetSettings}
          className="rounded-xl border px-4 py-2 text-sm font-semibold"
          style={{ color: PURPLE, borderColor: BORDER }}
        >
          Reset settings
        </button>
      </div>
    </details>
  );
}

function Evaluation() {
  const { id } = useParams();

  const [query, setQuery] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedClaim, setSelectedClaim] = useState(null);

  const queryId = id || sessionStorage.getItem("relirag_last_query_id");

  useEffect(() => {
    let cancelled = false;

    async function loadQuery() {
      setLoading(true);
      setError("");
      setQuery(null);
      setSelectedClaim(null);

      if (!queryId) {
        setError(
          "No saved query is available. Open Ask, submit a question, and try again."
        );
        setLoading(false);
        return;
      }

      if (USE_MOCK) {
        setError(
          "Evaluation details require real backend data. Turn mock mode off."
        );
        setLoading(false);
        return;
      }

      try {
        const response = await getQuery(queryId);

        if (cancelled) return;

        setQuery(response);

        const actualId = response?.query_id ?? queryId;
        sessionStorage.setItem("relirag_last_query_id", String(actualId));
      } catch (err) {
        if (!cancelled) {
          setError(err?.message || "Failed to load evaluation details.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadQuery();

    return () => {
      cancelled = true;
    };
  }, [queryId]);

  const attempts = query?.attempts ?? [];
  const attempt = attempts[attempts.length - 1] ?? null;
  const initialAttempt = attempts[0] ?? null;
  const correctedAttempt =
    attempts.length > 1 ? attempts[attempts.length - 1] : null;

  const question =
    query?.question ??
    query?.original_question ??
    "Question not available";

  const answer =
    query?.final_answer ??
    attempt?.answer ??
    query?.answer ??
    "";

  const evaluation = attempt?.evaluation ?? query?.evaluation ?? {};

  const claims =
    evaluation?.claim_analysis ??
    evaluation?.claims ??
    attempt?.claim_analysis ??
    query?.claim_analysis ??
    [];

  const evidence =
    attempt?.retrieval ??
    attempt?.retrieved_evidence ??
    query?.retrieval ??
    query?.retrieved_evidence ??
    [];

  const citations = attempt?.citations ?? query?.citations ?? [];

  const scores = [
    {
      title: "Faithfulness",
      value: evaluation?.faithfulness,
      color: "#EF4444",
      description:
        "Measures whether the answer is supported by retrieved evidence.",
    },
    {
      title: "Answer relevance",
      value: evaluation?.answer_relevance,
      color: "#22C55E",
      description:
        "Measures how well the answer addresses the question.",
    },
    {
      title: "Context relevance",
      value: evaluation?.context_relevance,
      color: "#3B82F6",
      description:
        "Measures how relevant the retrieved evidence is to the question.",
    },
  ];

  // Read the saved evaluator threshold.
  const evaluatorThreshold = (() => {
    try {
      const saved = JSON.parse(
        localStorage.getItem("relirag_evaluation_settings") || "{}"
      );
      const value = Number(saved.evaluatorThreshold ?? 0.7);

      return Number.isFinite(value) && value >= 0 && value <= 1
        ? value
        : 0.7;
    } catch {
      return 0.7;
    }
  })();

  // Compare the backend scores against the saved threshold.
  // This is a frontend assessment, not a new backend evaluation.
  const thresholdResults = scores.map((score) => {
    const raw = score.value;

    if (
      raw === null ||
      raw === undefined ||
      raw === "" ||
      !Number.isFinite(Number(raw))
    ) {
      return { ...score, passed: null };
    }

    const numericScore = Number(raw);
    const normalizedScore =
      numericScore <= 1 ? numericScore : numericScore / 100;

    return {
      ...score,
      passed: normalizedScore >= evaluatorThreshold,
    };
  });

  const availableThresholdResults = thresholdResults.filter(
    (score) => score.passed !== null
  );

  const thresholdCheckPassed =
    availableThresholdResults.length === scores.length &&
    availableThresholdResults.every((score) => score.passed);

  return (
    <div className="space-y-6">
      <header>
        <p className="text-sm font-medium" style={{ color: BLUE }}>
          RELI-RAG
        </p>
        <h1 className="mt-1 text-3xl font-bold" style={{ color: PURPLE }}>
          Evaluation Details
        </h1>
        <p className="mt-2 text-sm text-gray-500">
          Review answer quality, correction attempts, individual claims,
          and the evidence retrieved by the RAG pipeline.
        </p>
      </header>

      <SettingsPanel />

      {loading && (
        <section className="border bg-white p-5" style={cardStyle}>
          <p className="text-sm text-gray-500">
            Loading evaluation details from the backend...
          </p>
        </section>
      )}

      {!loading && error && (
        <section
          className="border border-red-200 bg-red-50 p-5"
          style={{ borderRadius: "16px" }}
        >
          <h2 className="font-bold text-red-800">
            Could not load evaluation
          </h2>
          <p className="mt-2 text-sm text-red-700">{error}</p>
          <Link
            to="/ask"
            className="mt-4 inline-block rounded-xl px-4 py-2 text-sm font-semibold text-white"
            style={{ backgroundColor: PURPLE }}
          >
            Return to Ask
          </Link>
        </section>
      )}

      {!loading && !error && query && (
        <>
          <PipelineStepper attempts={attempts} />

          {initialAttempt && correctedAttempt && (
            <>
              <AnswerComparison
                before={initialAttempt}
                after={correctedAttempt}
              />

              <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
                <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
                  Score improvement
                </h2>
                <p className="mt-2 text-sm text-gray-500">
                  A comparison of the first and latest evaluation attempts.
                </p>
                <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
                  <ScoreComparison
                    title="Faithfulness"
                    metric="faithfulness"
                    before={initialAttempt}
                    after={correctedAttempt}
                  />
                  <ScoreComparison
                    title="Answer relevance"
                    metric="answer_relevance"
                    before={initialAttempt}
                    after={correctedAttempt}
                  />
                  <ScoreComparison
                    title="Context relevance"
                    metric="context_relevance"
                    before={initialAttempt}
                    after={correctedAttempt}
                  />
                </div>
              </section>
            </>
          )}

          <CorrectionReason first={initialAttempt} latest={attempt} />

          <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
            <p
              className="text-xs font-semibold uppercase tracking-wide"
              style={{ color: BLUE }}
            >
              Evaluated question
            </p>
            <h2 className="mt-2 text-xl font-bold leading-7" style={{ color: PURPLE }}>
              {question}
            </h2>

            <div className="mt-5 border-t pt-4" style={{ borderColor: BORDER }}>
              <h3 className="text-sm font-bold" style={{ color: PURPLE }}>
                Latest generated answer
              </h3>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-gray-700">
                {answer || "No answer was returned."}
              </p>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              <span
                className="inline-block rounded-full px-3 py-1 text-xs font-semibold"
                style={{ color: PURPLE, backgroundColor: "#E5DBE6" }}
              >
                Query status: {formatLabel(query?.status)}
              </span>
              {attempt?.status && (
                <span
                  className="inline-block rounded-full px-3 py-1 text-xs font-semibold"
                  style={verdictStyle(attempt.status)}
                >
                  Attempt: {formatLabel(attempt.status)}
                </span>
              )}
            </div>
          </section>

          <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
            <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
              Evaluation scores
            </h2>
            <p className="mt-2 text-sm text-gray-500">
              N/A means the backend did not return that score.
            </p>
            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
              {scores.map((score) => (
                <ScoreCard
                  key={score.title}
                  title={score.title}
                  value={score.value}
                  color={score.color}
                  description={score.description}
                />
              ))}
            </div>
          </section>

          {/* New frontend-only evaluator threshold assessment. */}
          <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
            <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
              Evaluator Threshold Check
            </h2>
            <p className="mt-2 text-sm text-gray-500">
              Compares the backend evaluation scores with your saved
              threshold. This does not change the backend verdict or rerun
              the evaluator.
            </p>

            <div
              className="mt-4 rounded-xl border p-4"
              style={{ borderColor: BORDER }}
            >
              <p className="text-sm text-gray-600">
                Required minimum score
              </p>
              <p className="mt-1 text-2xl font-bold" style={{ color: PURPLE }}>
                {Math.round(evaluatorThreshold * 100)}%
              </p>
            </div>

            <div className="mt-4 space-y-3">
              {thresholdResults.map((score) => (
                <div
                  key={score.title}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4"
                  style={{ borderColor: BORDER }}
                >
                  <div>
                    <p className="font-semibold text-gray-800">
                      {score.title}
                    </p>
                    <p className="mt-1 text-sm text-gray-500">
                      Score: {formatScore(score.value)}
                    </p>
                  </div>

                  <span
                    className="rounded-full px-3 py-1 text-xs font-semibold"
                    style={
                      score.passed === null
                        ? { color: "#57534E", backgroundColor: "#F5F5F4" }
                        : score.passed
                          ? { color: GREEN, backgroundColor: "#DCFCE7" }
                          : { color: RED, backgroundColor: "#FEE2E2" }
                    }
                  >
                    {score.passed === null
                      ? "NOT AVAILABLE"
                      : score.passed
                        ? "PASS"
                        : "BELOW THRESHOLD"}
                  </span>
                </div>
              ))}
            </div>

            <div
              className="mt-4 rounded-xl p-4"
              style={
                availableThresholdResults.length !== scores.length
                  ? { color: "#57534E", backgroundColor: "#F5F5F4" }
                  : thresholdCheckPassed
                    ? { color: GREEN, backgroundColor: "#DCFCE7" }
                    : { color: RED, backgroundColor: "#FEE2E2" }
              }
            >
              <p className="font-bold">
                {availableThresholdResults.length !== scores.length
                  ? "Threshold check incomplete"
                  : thresholdCheckPassed
                    ? "All three scores meet the threshold"
                    : "One or more scores are below the threshold"}
              </p>
              <p className="mt-1 text-sm">
                {availableThresholdResults.length !== scores.length
                  ? "The overall check requires all three evaluation scores."
                  : "This is a frontend assessment, not a new backend evaluation."}
              </p>
            </div>
          </section>

          <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
            <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
              Claim analysis
            </h2>
            <p className="mt-2 text-sm text-gray-500">
              Examine individual answer claims and their evaluation verdicts.
            </p>

            {Array.isArray(claims) && claims.length > 0 ? (
              <div className="mt-4 space-y-3">
                {claims.map((claim, index) => {
                  const text =
                    typeof claim === "string"
                      ? claim
                      : claim.claim ??
                        claim.text ??
                        claim.statement ??
                        `Claim ${index + 1}`;

                  const verdict =
                    typeof claim === "object"
                      ? claim.verdict ?? claim.status ?? claim.result
                      : null;

                  const isSelected = selectedClaim === index;

                  return (
                    <article
                      key={claim.id ?? index}
                      className="rounded-xl border p-4"
                      style={{
                        borderColor: isSelected ? PURPLE : BORDER,
                        backgroundColor: isSelected ? "#F7F4FB" : "#FFFFFF",
                      }}
                    >
                      <button
                        type="button"
                        onClick={() =>
                          setSelectedClaim(isSelected ? null : index)
                        }
                        className="flex w-full flex-wrap items-start justify-between gap-3 text-left"
                      >
                        <span className="flex-1 text-sm leading-6 text-gray-700">
                          <span className="mr-2 font-semibold" style={{ color: PURPLE }}>
                            Claim {index + 1}
                          </span>
                          {text}
                        </span>

                        {verdict && (
                          <span
                            className="rounded-full px-3 py-1 text-xs font-semibold"
                            style={verdictStyle(verdict)}
                          >
                            {formatVerdict(verdict)}
                          </span>
                        )}
                      </button>

                      {isSelected && typeof claim === "object" && (
                        <div className="mt-4 border-t pt-3" style={{ borderColor: BORDER }}>
                          {claim.reason && (
                            <p className="text-sm leading-6 text-gray-600">
                              <strong style={{ color: PURPLE }}>Reason: </strong>
                              {claim.reason}
                            </p>
                          )}

                          {claim.evidence && (
                            <p className="mt-2 text-sm leading-6 text-gray-600">
                              <strong style={{ color: PURPLE }}>Evidence: </strong>
                              {typeof claim.evidence === "string"
                                ? claim.evidence
                                : JSON.stringify(claim.evidence)}
                            </p>
                          )}

                          <details className="mt-3">
                            <summary className="cursor-pointer text-xs font-semibold" style={{ color: PURPLE }}>
                              View claim data
                            </summary>
                            <pre className="mt-2 overflow-auto rounded-lg bg-gray-900 p-3 text-xs text-gray-100">
                              {JSON.stringify(claim, null, 2)}
                            </pre>
                          </details>
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
            ) : (
              <div className="mt-4 rounded-xl p-4" style={{ backgroundColor: "#F5F5F4" }}>
                <p className="text-sm text-gray-600">
                  No individual claim analysis was returned for this query.
                </p>
              </div>
            )}
          </section>

          <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
            <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
              Retrieved evidence
            </h2>
            <p className="mt-2 text-sm text-gray-500">
              Passages retrieved from your selected documents and supplied
              to the answer-generation process.
            </p>

            {Array.isArray(evidence) && evidence.length > 0 ? (
              <div className="mt-4 space-y-3">
                {evidence.map((item, index) => (
                  <article
                    key={item.chunk_id ?? item.id ?? index}
                    className="rounded-xl border p-4"
                    style={{ borderColor: BORDER }}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <h3 className="text-sm font-semibold text-gray-800">
                          {item.filename ??
                            item.document_name ??
                            item.source ??
                            `Evidence ${index + 1}`}
                        </h3>
                        {item.page_number != null && (
                          <p className="mt-1 text-xs text-gray-500">
                            Page {item.page_number}
                          </p>
                        )}
                      </div>

                      {typeof item.similarity === "number" && (
                        <span
                          className="rounded-full px-3 py-1 text-xs font-semibold"
                          style={{ color: PURPLE, backgroundColor: "#E5DBE6" }}
                        >
                          Similarity: {item.similarity.toFixed(3)}
                        </span>
                      )}
                    </div>

                    <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-gray-600">
                      {item.content ??
                        item.text ??
                        item.chunk_text ??
                        "No evidence text was returned."}
                    </p>

                    <div className="mt-3 flex flex-wrap gap-3 text-xs text-gray-500">
                      <span>Rank: {item.rank ?? index + 1}</span>
                      <span>Chunk ID: {item.chunk_id ?? "N/A"}</span>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="mt-4 rounded-xl p-4" style={{ backgroundColor: "#F5F5F4" }}>
                <p className="text-sm text-gray-600">
                  No retrieved evidence was returned for this query.
                </p>
              </div>
            )}

            {Array.isArray(citations) && citations.length > 0 && (
              <div className="mt-5 border-t pt-4" style={{ borderColor: BORDER }}>
                <h3 className="text-sm font-bold" style={{ color: PURPLE }}>
                  Answer citations
                </h3>
                <ul className="mt-2 list-inside list-disc space-y-2 text-sm text-gray-600">
                  {citations.map((citation, index) => (
                    <li key={index}>
                      {typeof citation === "string"
                        ? citation
                        : citation.text ??
                          citation.filename ??
                          JSON.stringify(citation)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          <footer className="flex flex-wrap gap-3">
            <Link
              to="/ask"
              className="rounded-xl border px-4 py-2 text-sm font-semibold"
              style={{ color: PURPLE, borderColor: BORDER }}
            >
              Back to Ask
            </Link>

            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded-xl px-4 py-2 text-sm font-semibold text-white"
              style={{ backgroundColor: PURPLE }}
            >
              Refresh evaluation
            </button>
          </footer>
        </>
      )}
    </div>
  );
}

export default Evaluation;
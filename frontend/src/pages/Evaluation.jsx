
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
  return `${Math.round((score <= 1 ? score * 100 : score) * 10) / 10}%`;
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

  const score = Number(value);
  return score <= 1 ? score * 100 : score;
}

function verdictStyle(verdict) {
  const value = String(verdict ?? "").toUpperCase();

  if (
    ["PASSED", "PASS", "SUPPORTED", "CORRECT", "ANSWERED"].includes(value)
  ) {
    return { color: GREEN, backgroundColor: "#DCFCE7" };
  }

  if (["CORRECTED"].includes(value)) {
    return { color: "#92400E", backgroundColor: "#FEF3C7" };
  }

  if (
    [
      "FAILED_AFTER_CORRECTION",
      "FAILED",
      "FAIL",
      "UNSUPPORTED",
      "INSUFFICIENT_EVIDENCE",
    ].includes(value)
  ) {
    return { color: RED, backgroundColor: "#FEE2E2" };
  }

  return { color: "#57534E", backgroundColor: "#F5F5F4" };
}

function ScoreCard({ title, value, description, color }) {
  const score = normalizedScore(value);

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

      <div
        className="mt-3 h-2 overflow-hidden rounded-full bg-gray-100"
        role="progressbar"
        aria-label={title}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={score === null ? 0 : Math.max(0, Math.min(100, score))}
      >
        <div
          className="h-full rounded-full"
          style={{
            width: `${score === null ? 0 : Math.max(0, Math.min(100, score))}%`,
            backgroundColor: color,
          }}
        />
      </div>

      {description && (
        <p className="mt-2 text-xs leading-5 text-gray-500">
          {description}
        </p>
      )}
    </article>
  );
}

function getAttemptScore(attempt, key) {
  return normalizedScore(attempt?.evaluation?.[key]);
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
            {beforeScore === null ? "N/A" : `${beforeScore.toFixed(1)}%`}
          </p>
        </div>

        <div className="rounded-lg bg-green-50 p-3">
          <p className="text-xs text-green-700">After</p>
          <p className="mt-1 text-xl font-bold text-green-800">
            {afterScore === null ? "N/A" : `${afterScore.toFixed(1)}%`}
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
          {difference.toFixed(1)} percentage points
        </p>
      )}
    </article>
  );
}

function AttemptHistory({ attempts, finalAttempt }) {
  return (
    <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
      <div>
        <p
          className="text-xs font-semibold uppercase tracking-wide"
          style={{ color: BLUE }}
        >
          Evaluation history
        </p>

        <h2 className="mt-1 text-xl font-bold" style={{ color: PURPLE }}>
          Attempts & Answers
        </h2>

        <p className="mt-2 text-sm text-gray-500">
          Review each answer in chronological order, including its evaluation
          scores and correction status.
        </p>
      </div>

      {attempts.length > 0 ? (
        <div className="mt-5 space-y-5">
          {attempts.map((item, index) => {
            const evaluation = item?.evaluation ?? {};
            const isFinal =
              finalAttempt != null &&
              Number(item.attempt_number) ===
                Number(finalAttempt.attempt_number);

            const attemptNumber = item.attempt_number ?? index + 1;

            const attemptScores = [
              { label: "Faithfulness", value: evaluation.faithfulness },
              {
                label: "Answer relevance",
                value: evaluation.answer_relevance,
              },
              {
                label: "Context relevance",
                value: evaluation.context_relevance,
              },
            ];

            const status =
              evaluation.passed === true
                ? "PASSED"
                : evaluation.passed === false
                  ? "FAILED"
                  : item.status ?? "NOT EVALUATED";

            return (
              <article
                key={item.id ?? attemptNumber}
                className="overflow-hidden rounded-xl border"
                style={{
                  borderColor: isFinal ? PURPLE : BORDER,
                }}
              >
                <div
                  className="flex flex-wrap items-center justify-between gap-3 p-4"
                  style={{
                    backgroundColor: isFinal ? "#F0EBFA" : "#FAF9FC",
                  }}
                >
                  <div>
                    <h3 className="font-bold" style={{ color: PURPLE }}>
                      Attempt {attemptNumber}
                      {isFinal ? " — Final attempt" : ""}
                    </h3>

                    {item.model && (
                      <p className="mt-1 text-xs text-gray-500">
                        Model: {item.model}
                      </p>
                    )}
                  </div>

                  <span
                    className="rounded-full px-3 py-1 text-xs font-semibold"
                    style={verdictStyle(status)}
                  >
                    {formatLabel(status).toUpperCase()}
                  </span>
                </div>

                <div className="p-4">
                  <h4 className="text-sm font-semibold text-gray-700">
                    Answer
                  </h4>

                  <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-gray-700">
                    {item.answer || "No answer was returned for this attempt."}
                  </p>

                  {evaluation.feedback && (
                    <div className="mt-4 rounded-lg bg-gray-50 p-3">
                      <p className="text-xs font-semibold text-gray-600">
                        Evaluator feedback
                      </p>
                      <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-gray-600">
                        {evaluation.feedback}
                      </p>
                    </div>
                  )}

                  <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
                    {attemptScores.map((score) => (
                      <div
                        key={score.label}
                        className="rounded-lg border p-3"
                        style={{ borderColor: BORDER }}
                      >
                        <p className="text-xs text-gray-500">
                          {score.label}
                        </p>
                        <p
                          className="mt-1 text-lg font-bold"
                          style={{ color: PURPLE }}
                        >
                          {formatScore(score.value)}
                        </p>
                      </div>
                    ))}
                  </div>

                  {item.retrieval_query && (
                    <details className="mt-4">
                      <summary
                        className="cursor-pointer text-sm font-semibold"
                        style={{ color: PURPLE }}
                      >
                        View retrieval query
                      </summary>
                      <p className="mt-2 whitespace-pre-wrap rounded-lg bg-gray-50 p-3 text-sm leading-6 text-gray-600">
                        {item.retrieval_query}
                      </p>
                    </details>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <p className="mt-4 rounded-lg bg-gray-50 p-4 text-sm text-gray-600">
          No individual attempts were returned by the backend.
        </p>
      )}
    </section>
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
        Before / After Comparison
      </h2>

      <p className="mt-2 text-sm text-gray-500">
        Compare the first answer with the final correction attempt. Sentence
        differences are based on exact text matching.
      </p>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <article className="rounded-xl border border-red-200 bg-red-50/40 p-4">
          <h3 className="font-bold text-red-800">Before — Original answer</h3>
          <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-gray-700">
            {beforeText || "No original answer was returned."}
          </p>
        </article>

        <article className="rounded-xl border border-green-200 bg-green-50/40 p-4">
          <h3 className="font-bold text-green-800">After — Final answer</h3>
          <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-gray-700">
            {afterText || "No final answer was returned."}
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

function BasicVsReliComparison({ query }) {
  const comparison =
    query?.comparison ??
    query?.comparison_results ??
    query?.comparison_data ??
    null;

  function readScore(metric, system) {
    const value =
      comparison?.[metric]?.[system] ??
      comparison?.[system]?.[metric] ??
      null;

    return normalizedScore(value);
  }

  const metrics = [
    { title: "Faithfulness", key: "faithfulness" },
    { title: "Answer relevance", key: "answer_relevance" },
    { title: "Context relevance", key: "context_relevance" },
  ];

  return (
    <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
      <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
        Basic RAG vs RELI-RAG
      </h2>

      <p className="mt-2 text-sm text-gray-500">
        This section requires actual scores for both systems. An earlier
        correction attempt is not the same as a Basic RAG result.
      </p>

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
        {metrics.map((metric) => {
          const basic = readScore(metric.key, "basic_rag");
          const reli = readScore(metric.key, "reli_rag");

          const difference =
            basic === null || reli === null
              ? null
              : Math.round((reli - basic) * 10) / 10;

          return (
            <article
              key={metric.key}
              className="rounded-xl border p-4"
              style={{ borderColor: BORDER }}
            >
              <h3 className="font-semibold text-gray-700">
                {metric.title}
              </h3>

              <div className="mt-3 grid grid-cols-2 gap-3">
                <div className="rounded-lg bg-blue-50 p-3">
                  <p className="text-xs text-blue-700">Basic RAG</p>
                  <p className="mt-1 text-lg font-bold text-blue-800">
                    {basic === null ? "N/A" : `${basic.toFixed(1)}%`}
                  </p>
                </div>

                <div className="rounded-lg p-3" style={{ backgroundColor: "#F0EBFA" }}>
                  <p className="text-xs" style={{ color: PURPLE }}>
                    RELI-RAG
                  </p>
                  <p className="mt-1 text-lg font-bold" style={{ color: PURPLE }}>
                    {reli === null ? "N/A" : `${reli.toFixed(1)}%`}
                  </p>
                </div>
              </div>

              {difference === null ? (
                <p className="mt-3 text-xs text-gray-500">
                  Comparison scores were not returned by the backend.
                </p>
              ) : (
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
                  Difference: {difference > 0 ? "+" : ""}
                  {difference.toFixed(1)} percentage points
                </p>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function CorrectionReason({ first, latest }) {
  const firstEvaluation = first?.evaluation;
  const latestEvaluation = latest?.evaluation;

  const failureType =
    firstEvaluation?.failure_type ??
    latestEvaluation?.failure_type ??
    first?.failure_type ??
    latest?.failure_type;

  const feedback =
    latestEvaluation?.feedback ??
    firstEvaluation?.feedback ??
    latest?.feedback ??
    first?.feedback;

  return (
    <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
      <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
        Correction Reason
      </h2>

      <p className="mt-2 text-sm text-gray-500">
        Understand the evaluator's reported failure and how the retrieval
        query changed across attempts.
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
            {first?.retrieval_query || "Not available"}
          </p>
        </div>

        <div className="rounded-xl border p-4" style={{ borderColor: BORDER }}>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Final retrieval query
          </p>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-700">
            {latest?.retrieval_query || "Not available"}
          </p>
        </div>
      </div>

      {first && latest && first === latest && (
        <p className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
          Only one attempt is available. No separate correction attempt was
          returned for this query.
        </p>
      )}
    </section>
  );
}

function Evaluation() {
  const { id, queryId: queryIdParam } = useParams();

  const [savedQueryId] = useState(() => {
    try {
      return sessionStorage.getItem("relirag_last_query_id") || "";
    } catch {
      return "";
    }
  });

  const queryId = id || queryIdParam || savedQueryId;

  const [query, setQuery] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedClaim, setSelectedClaim] = useState(null);

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

        try {
          sessionStorage.setItem(
            "relirag_last_query_id",
            String(actualId)
          );
        } catch {
          // The URL query ID can still be used without session storage.
        }
      } catch (err) {
        if (!cancelled) {
          setError(err?.message || "Failed to load evaluation details.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    loadQuery();

    return () => {
      cancelled = true;
    };
  }, [queryId]);

  const attempts = Array.isArray(query?.attempts) ? query.attempts : [];

  const initialAttempt = attempts[0] ?? null;

  const finalAttemptNumber = query?.final_attempt_number;

  const finalAttempt =
    attempts.find(
      (item) =>
        finalAttemptNumber != null &&
        Number(item.attempt_number) === Number(finalAttemptNumber)
    ) ??
    attempts[attempts.length - 1] ??
    null;

  const question =
    query?.question ??
    query?.original_question ??
    "Question not available";

  const finalAnswer =
    query?.final_answer ??
    finalAttempt?.answer ??
    query?.answer ??
    "";

  const evaluation = finalAttempt?.evaluation ?? query?.evaluation ?? {};

  const claims = Array.isArray(evaluation?.claims)
    ? evaluation.claims
    : Array.isArray(evaluation?.claim_analysis)
      ? evaluation.claim_analysis
      : Array.isArray(finalAttempt?.claim_analysis)
        ? finalAttempt.claim_analysis
        : Array.isArray(query?.claim_analysis)
          ? query.claim_analysis
          : [];

  const retrievalSource =
    finalAttempt?.retrieval ??
    finalAttempt?.retrieved_evidence ??
    query?.retrieval ??
    query?.retrieved_evidence ??
    [];

  const evidence = Array.isArray(retrievalSource)
    ? retrievalSource
    : Array.isArray(retrievalSource?.chunks)
      ? retrievalSource.chunks
      : Array.isArray(retrievalSource?.results)
        ? retrievalSource.results
        : [];

  const citations = Array.isArray(finalAttempt?.citations)
    ? finalAttempt.citations
    : Array.isArray(query?.citations)
      ? query.citations
      : [];

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
      description: "Measures how well the answer addresses the question.",
    },
    {
      title: "Context relevance",
      value: evaluation?.context_relevance,
      color: "#3B82F6",
      description:
        "Measures how relevant the retrieved evidence is to the question.",
    },
  ];

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

  const thresholdResults = scores.map((score) => {
    const normalized = normalizedScore(score.value);

    return {
      ...score,
      passed:
        normalized === null
          ? null
          : normalized >= evaluatorThreshold * 100,
    };
  });

  const availableThresholdResults = thresholdResults.filter(
    (score) => score.passed !== null
  );

  const thresholdCheckPassed =
    availableThresholdResults.length === scores.length &&
    availableThresholdResults.every((score) => score.passed);

  const finalVerdict =
    evaluation?.passed === true
      ? "PASSED"
      : evaluation?.passed === false
        ? "FAILED"
        : finalAttempt?.status ?? query?.status ?? "NOT EVALUATED";

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
          Investigate every answer attempt, review the final evaluation, and
          understand how the correction process changes answer quality.
        </p>
      </header>

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
          {/* 1. ATTEMPTS AND ANSWERS */}
          <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
            <p
              className="text-xs font-semibold uppercase tracking-wide"
              style={{ color: BLUE }}
            >
              Question
            </p>

            <h2 className="mt-2 text-lg font-bold leading-7" style={{ color: PURPLE }}>
              {question}
            </h2>

            <div className="mt-3 flex flex-wrap gap-2">
              <span
                className="rounded-full px-3 py-1 text-xs font-semibold"
                style={{ backgroundColor: "#E5DBE6", color: PURPLE }}
              >
                Query ID: {query?.query_id ?? queryId}
              </span>

              <span
                className="rounded-full px-3 py-1 text-xs font-semibold"
                style={verdictStyle(query?.status)}
              >
                Query status: {formatLabel(query?.status)}
              </span>

              <span
                className="rounded-full px-3 py-1 text-xs font-semibold"
                style={{ backgroundColor: "#F5F5F4", color: "#57534E" }}
              >
                {attempts.length} attempt{attempts.length === 1 ? "" : "s"}
              </span>
            </div>
          </section>

          <AttemptHistory
            attempts={attempts}
            finalAttempt={finalAttempt}
          />

          {/* 2. FINAL ANSWER AND SCORES */}
          <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
            <p
              className="text-xs font-semibold uppercase tracking-wide"
              style={{ color: BLUE }}
            >
              Final result
            </p>

            <h2 className="mt-1 text-xl font-bold" style={{ color: PURPLE }}>
              Final Answer
            </h2>

            <div
              className="mt-4 rounded-xl border p-4"
              style={{ borderColor: BORDER }}
            >
              <p className="whitespace-pre-wrap text-sm leading-7 text-gray-700">
                {finalAnswer || "No final answer was returned."}
              </p>
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <span className="text-sm text-gray-500">
                Backend verdict:
              </span>

              <span
                className="rounded-full px-3 py-1 text-xs font-semibold"
                style={verdictStyle(finalVerdict)}
              >
                {formatLabel(finalVerdict).toUpperCase()}
              </span>

              {finalAttempt?.attempt_number != null && (
                <span className="rounded-full bg-gray-100 px-3 py-1 text-xs font-semibold text-gray-600">
                  Final attempt #{finalAttempt.attempt_number}
                </span>
              )}
            </div>

            <h3 className="mt-6 text-lg font-bold" style={{ color: PURPLE }}>
              Final Evaluation Scores
            </h3>

            <p className="mt-1 text-sm text-gray-500">
              Scores returned by the backend evaluator for the final attempt.
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

            {evaluation?.feedback && (
              <div
                className="mt-4 rounded-xl border p-4"
                style={{ borderColor: BORDER }}
              >
                <h3 className="font-semibold" style={{ color: PURPLE }}>
                  Final evaluator feedback
                </h3>

                <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-600">
                  {evaluation.feedback}
                </p>
              </div>
            )}
          </section>

          {/* 3. BEFORE / AFTER COMPARISON */}
          {initialAttempt && finalAttempt && (
            <>
              {attempts.length > 1 ? (
                <AnswerComparison
                  before={initialAttempt}
                  after={finalAttempt}
                />
              ) : (
                <section
                  className="border bg-white p-5 shadow-sm"
                  style={cardStyle}
                >
                  <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
                    Before / After Comparison
                  </h2>

                  <p className="mt-2 text-sm text-gray-500">
                    Only one attempt was returned. A before-and-after
                    correction comparison requires at least two attempts.
                  </p>
                </section>
              )}

              {attempts.length > 1 && (
                <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
                  <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
                    Score Improvement
                  </h2>

                  <p className="mt-2 text-sm text-gray-500">
                    Compare the original attempt's scores with the final
                    attempt's scores. These are correction results, not
                    Basic RAG versus RELI-RAG results.
                  </p>

                  <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
                    <ScoreComparison
                      title="Faithfulness"
                      metric="faithfulness"
                      before={initialAttempt}
                      after={finalAttempt}
                    />

                    <ScoreComparison
                      title="Answer relevance"
                      metric="answer_relevance"
                      before={initialAttempt}
                      after={finalAttempt}
                    />

                    <ScoreComparison
                      title="Context relevance"
                      metric="context_relevance"
                      before={initialAttempt}
                      after={finalAttempt}
                    />
                  </div>
                </section>
              )}
            </>
          )}

          {/* 4. DETAILED DIAGNOSTICS */}
          <CorrectionReason
            first={initialAttempt}
            latest={finalAttempt}
          />

          <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
            <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
              Evaluator Threshold Check
            </h2>

            <p className="mt-2 text-sm text-gray-500">
              This frontend check compares the returned scores with your saved
              threshold. It does not rerun the backend evaluator.
            </p>

            <div
              className="mt-4 rounded-xl border p-4"
              style={{ borderColor: BORDER }}
            >
              <p className="text-sm text-gray-600">Required minimum score</p>

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
                    ? "All three scores meet the frontend threshold"
                    : "One or more scores are below the frontend threshold"}
              </p>
            </div>
          </section>

          <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
            <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
              Claim Analysis
            </h2>

            <p className="mt-2 text-sm text-gray-500">
              Expand a claim to inspect the evaluator's verdict and supporting
              evidence.
            </p>

            {claims.length > 0 ? (
              <div className="mt-4 space-y-3">
                {claims.map((claim, index) => {
                  const text =
                    typeof claim === "string"
                      ? claim
                      : claim.claim_text ??
                        claim.claim ??
                        claim.text ??
                        claim.statement ??
                        `Claim ${index + 1}`;

                  const verdict =
                    typeof claim === "object" && claim !== null
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
                        aria-expanded={isSelected}
                        className="flex w-full flex-wrap items-start justify-between gap-3 text-left"
                      >
                        <span className="flex-1 text-sm leading-6 text-gray-700">
                          <span
                            className="mr-2 font-semibold"
                            style={{ color: PURPLE }}
                          >
                            Claim {index + 1}
                          </span>
                          {text}
                        </span>

                        {verdict && (
                          <span
                            className="rounded-full px-3 py-1 text-xs font-semibold"
                            style={verdictStyle(verdict)}
                          >
                            {formatLabel(verdict).toUpperCase()}
                          </span>
                        )}
                      </button>

                      {isSelected &&
                        typeof claim === "object" &&
                        claim !== null && (
                          <div
                            className="mt-4 border-t pt-3"
                            style={{ borderColor: BORDER }}
                          >
                            {claim.evidence_chunk_id != null && (
                              <p className="text-sm text-gray-600">
                                <strong style={{ color: PURPLE }}>
                                  Evidence chunk ID:{" "}
                                </strong>
                                {claim.evidence_chunk_id}
                              </p>
                            )}

                            {claim.evidence_quote && (
                              <p className="mt-2 text-sm leading-6 text-gray-600">
                                <strong style={{ color: PURPLE }}>
                                  Evidence quote:{" "}
                                </strong>
                                {claim.evidence_quote}
                              </p>
                            )}

                            {claim.reason && (
                              <p className="mt-2 text-sm leading-6 text-gray-600">
                                <strong style={{ color: PURPLE }}>
                                  Reason:{" "}
                                </strong>
                                {claim.reason}
                              </p>
                            )}

                            <details className="mt-3">
                              <summary
                                className="cursor-pointer text-xs font-semibold"
                                style={{ color: PURPLE }}
                              >
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
                  No individual claim analysis was returned for this attempt.
                </p>
              </div>
            )}
          </section>

          <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
            <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
              Retrieved Evidence
            </h2>

            <p className="mt-2 text-sm text-gray-500">
              Passages retrieved by the RAG pipeline for the final attempt.
            </p>

            {evidence.length > 0 ? (
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

                      {item.similarity != null &&
                        Number.isFinite(Number(item.similarity)) && (
                          <span
                            className="rounded-full px-3 py-1 text-xs font-semibold"
                            style={{
                              color: PURPLE,
                              backgroundColor: "#E5DBE6",
                            }}
                          >
                            Similarity: {Number(item.similarity).toFixed(3)}
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

            {citations.length > 0 && (
              <div
                className="mt-5 border-t pt-4"
                style={{ borderColor: BORDER }}
              >
                <h3 className="text-sm font-bold" style={{ color: PURPLE }}>
                  Answer Citations
                </h3>

                <ul className="mt-2 list-inside list-disc space-y-2 text-sm text-gray-600">
                  {citations.map((citation, index) => (
                    <li key={index}>
                      {typeof citation === "string" ||
                      typeof citation === "number"
                        ? String(citation)
                        : citation.text ??
                          citation.filename ??
                          JSON.stringify(citation)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          {/* 5. BASIC RAG VS RELI-RAG */}
          <BasicVsReliComparison query={query} />

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
              Refresh Evaluation
            </button>

            <Link
              to="/analytics"
              className="rounded-xl border px-4 py-2 text-sm font-semibold"
              style={{ color: PURPLE, borderColor: BORDER }}
            >
              View Analytics
            </Link>
          </footer>
        </>
      )}
    </div>
  );
}

export default Evaluation;

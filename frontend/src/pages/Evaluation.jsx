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
  similarityGate: 0.5,
};

const SCORE_METRICS = [
  {
    key: "faithfulness",
    title: "Faithfulness",
    color: "#EF4444",
    description:
      "Measures whether the answer is supported by retrieved evidence.",
  },
  {
    key: "answer_relevance",
    title: "Answer relevance",
    color: "#22C55E",
    description: "Measures how well the answer addresses the question.",
  },
  {
    key: "context_relevance",
    title: "Context relevance",
    color: "#3B82F6",
    description:
      "Measures how relevant the retrieved evidence is to the question.",
  },
];

// Must match EVALUATOR_ERROR in backend/app/services/evaluator.py.
const EVALUATOR_ERROR = "evaluator_error";

// Must match determine_failure_type in backend/app/services/evaluator.py.
const FAILURE_TYPE_METRIC = {
  unsupported_claim: "faithfulness",
  missing_info: "answer_relevance",
  irrelevant_retrieval: "context_relevance",
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

  if (["PASSED", "PASS", "SUPPORTED"].includes(value)) {
    return { color: GREEN, backgroundColor: "#DCFCE7" };
  }

  if (["CORRECTED", "PARTIALLY_SUPPORTED"].includes(value)) {
    return { color: "#92400E", backgroundColor: "#FEF3C7" };
  }

  if (
    ["FAILED_AFTER_CORRECTION", "FAILED", "FAIL", "UNSUPPORTED"].includes(
      value
    )
  ) {
    return { color: RED, backgroundColor: "#FEE2E2" };
  }

  return { color: "#57534E", backgroundColor: "#F5F5F4" };
}

function evaluationVerdict(evaluation) {
  if (!evaluation) return "NOT_EVALUATED";
  if (evaluation.failure_type === EVALUATOR_ERROR) return "EVALUATOR_ERROR";
  if (evaluation.passed === true) return "PASSED";
  if (evaluation.passed === false) return "FAILED";
  return "NOT_DETERMINED";
}

function attemptTitle(attempt) {
  return `Attempt ${attempt?.attempt_number ?? "—"}`;
}

function isReportedAttempt(attempt, finalAttemptNumber) {
  return (
    finalAttemptNumber !== null &&
    finalAttemptNumber !== undefined &&
    attempt?.attempt_number === finalAttemptNumber
  );
}

function Badge({ children, style }) {
  return (
    <span
      className="inline-block rounded-full px-3 py-1 text-xs font-semibold"
      style={style}
    >
      {children}
    </span>
  );
}

function ReportedBadge() {
  return (
    <Badge style={{ color: "#FFFFFF", backgroundColor: PURPLE }}>
      Reported by query
    </Badge>
  );
}

function ScoreCard({ title, value, description, color, failureCause }) {
  return (
    <article
      className="rounded-xl border bg-white p-4"
      style={{ borderColor: color, borderRadius: "12px" }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold" style={{ color }}>
          {title}
        </p>
        {failureCause && (
          <Badge style={{ color: RED, backgroundColor: "#FEE2E2" }}>
            Failure cause
          </Badge>
        )}
      </div>
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

function ScoreComparison({ title, metric, attempts, finalAttemptNumber }) {
  return (
    <article
      className="rounded-xl border bg-white p-4"
      style={{ borderColor: BORDER }}
    >
      <h3 className="text-sm font-semibold text-gray-700">{title}</h3>

      <ul className="mt-3 space-y-2">
        {attempts.map((attempt, index) => {
          const score = getAttemptScore(attempt, metric);
          const previous =
            index > 0 ? getAttemptScore(attempts[index - 1], metric) : null;
          const difference =
            score === null || previous === null
              ? null
              : Math.round((score - previous) * 10) / 10;
          const reported = isReportedAttempt(attempt, finalAttemptNumber);

          return (
            <li
              key={attempt?.attempt_number ?? index}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg p-3"
              style={{
                backgroundColor: reported ? "#F7F4FB" : "#F5F5F4",
                border: `1px solid ${reported ? PURPLE : "transparent"}`,
              }}
            >
              <span className="text-xs font-semibold text-gray-600">
                {attemptTitle(attempt)}
                {reported && (
                  <span className="ml-1" style={{ color: PURPLE }}>
                    · reported
                  </span>
                )}
              </span>

              <span className="flex items-baseline gap-2">
                <span
                  className="text-xl font-bold"
                  style={{ color: PURPLE }}
                >
                  {formatScore(attempt?.evaluation?.[metric])}
                </span>
                {difference !== null && (
                  <span
                    className="text-xs font-semibold"
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
                    {difference} pp
                  </span>
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </article>
  );
}

function AnswerComparison({ before, after, finalAttemptNumber }) {
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
        First / last attempt comparison
      </h2>
      <p className="mt-2 text-sm text-gray-500">
        Compare the first attempt with the last attempt returned by the
        backend. Differences below are based on complete sentences. Every
        attempt is listed in full under Attempt history.
      </p>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <article className="rounded-xl border border-red-200 bg-red-50/40 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-bold text-red-800">
              {attemptTitle(before)} (first)
            </h3>
            {isReportedAttempt(before, finalAttemptNumber) && (
              <ReportedBadge />
            )}
          </div>
          <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-gray-700">
            {beforeText || "No answer was returned for this attempt."}
          </p>
        </article>

        <article className="rounded-xl border border-green-200 bg-green-50/40 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-bold text-green-800">
              {attemptTitle(after)} (last)
            </h3>
            {isReportedAttempt(after, finalAttemptNumber) && (
              <ReportedBadge />
            )}
          </div>
          <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-gray-700">
            {afterText || "No answer was returned for this attempt."}
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
  const first = attempts[0];
  const corrections = attempts.slice(1);
  const firstEvaluation = first?.evaluation;
  const evaluatedCorrections = corrections.filter(
    (attempt) => attempt?.evaluation
  );

  const stages = [
    {
      ...PIPELINE_STAGES[0],
      done: Boolean(first?.retrieval?.length),
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
        ? formatVerdict(evaluationVerdict(firstEvaluation))
        : "Evaluation unavailable",
    },
    {
      ...PIPELINE_STAGES[3],
      done: corrections.length > 0,
      detail: corrections.length
        ? corrections
            .map(
              (attempt) =>
                `${attemptTitle(attempt)}: ${
                  attempt?.strategy
                    ? formatLabel(attempt.strategy)
                    : "strategy not recorded"
                }`
            )
            .join(" · ")
        : "No separate correction attempt recorded",
    },
    {
      ...PIPELINE_STAGES[4],
      done: evaluatedCorrections.length > 0,
      detail: corrections.length
        ? corrections
            .map(
              (attempt) =>
                `${attemptTitle(attempt)}: ${formatVerdict(
                  evaluationVerdict(attempt?.evaluation)
                )}`
            )
            .join(" · ")
        : "Re-evaluation unavailable",
    },
  ];

  return (
    <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
      <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
        Correction pipeline
      </h2>
      <p className="mt-2 text-sm text-gray-500">
        Stage indicators are inferred from the {attempts.length} attempt
        {attempts.length === 1 ? "" : "s"} returned by the backend.
        Unavailable timings are not estimated.
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

function CorrectionReason({ attempts }) {
  const corrections = attempts.slice(1).map((attempt, index) => ({
    attempt,
    preceding: attempts[index],
  }));

  return (
    <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
      <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
        Correction reason
      </h2>
      <p className="mt-2 text-sm text-gray-500">
        For each correction attempt, review the evaluation of the attempt
        before it and the retrieval queries the two attempts used.
      </p>

      {corrections.length === 0 && (
        <p className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
          Only one attempt is available. A separate correction attempt has
          not been returned for this query.
        </p>
      )}

      {corrections.map(({ attempt, preceding }, index) => (
        <div
          key={attempt?.attempt_number ?? index}
          className="mt-4 rounded-xl border p-4"
          style={{ borderColor: BORDER }}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-bold" style={{ color: PURPLE }}>
              {attemptTitle(preceding)} → {attemptTitle(attempt)}
            </h3>
            <Badge style={{ color: PURPLE, backgroundColor: "#E5DBE6" }}>
              Strategy: {formatLabel(attempt?.strategy)}
            </Badge>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="rounded-xl border p-4" style={{ borderColor: BORDER }}>
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                Failure type ({attemptTitle(preceding)})
              </p>
              <p className="mt-2 text-sm font-semibold text-gray-800">
                {preceding?.evaluation
                  ? formatLabel(preceding.evaluation.failure_type)
                  : "Not evaluated"}
              </p>
            </div>

            <div className="rounded-xl border p-4" style={{ borderColor: BORDER }}>
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                Evaluator feedback ({attemptTitle(preceding)})
              </p>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-700">
                {preceding?.evaluation?.feedback ||
                  "No evaluator feedback was returned."}
              </p>
            </div>

            <div className="rounded-xl border p-4" style={{ borderColor: BORDER }}>
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                Retrieval query ({attemptTitle(preceding)})
              </p>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-700">
                {preceding?.retrieval_query || "Not available"}
              </p>
            </div>

            <div className="rounded-xl border p-4" style={{ borderColor: BORDER }}>
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                Retrieval query ({attemptTitle(attempt)})
              </p>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-700">
                {attempt?.retrieval_query || "Not available"}
              </p>
            </div>
          </div>
        </div>
      ))}
    </section>
  );
}

function ClaimList({ claims, evidence }) {
  const [selectedClaim, setSelectedClaim] = useState(null);

  if (!Array.isArray(claims) || claims.length === 0) {
    return (
      <div className="mt-4 rounded-xl p-4" style={{ backgroundColor: "#F5F5F4" }}>
        <p className="text-sm text-gray-600">
          No individual claim analysis was returned for this attempt.
        </p>
      </div>
    );
  }

  return (
    <div className="mt-4 space-y-3">
      {claims.map((claim, index) => {
        const isSelected = selectedClaim === index;
        const hasChunk =
          claim.evidence_chunk_id !== null &&
          claim.evidence_chunk_id !== undefined;
        const source = hasChunk
          ? evidence.find((item) => item.chunk_id === claim.evidence_chunk_id)
          : null;

        return (
          <article
            key={index}
            className="rounded-xl border p-4"
            style={{
              borderColor: isSelected ? PURPLE : BORDER,
              backgroundColor: isSelected ? "#F7F4FB" : "#FFFFFF",
            }}
          >
            <button
              type="button"
              onClick={() => setSelectedClaim(isSelected ? null : index)}
              className="flex w-full flex-wrap items-start justify-between gap-3 text-left"
            >
              <span className="flex-1 text-sm leading-6 text-gray-700">
                <span className="mr-2 font-semibold" style={{ color: PURPLE }}>
                  Claim {index + 1}
                </span>
                {claim.claim_text || "Claim text not available"}
              </span>

              <Badge style={verdictStyle(claim.verdict)}>
                {formatVerdict(claim.verdict)}
              </Badge>
            </button>

            {isSelected && (
              <div className="mt-4 border-t pt-3" style={{ borderColor: BORDER }}>
                {claim.evidence_quote || hasChunk ? (
                  <>
                    {claim.evidence_quote && (
                      <p className="text-sm leading-6 text-gray-600">
                        <strong style={{ color: PURPLE }}>Evidence: </strong>
                        “{claim.evidence_quote}”
                      </p>
                    )}
                    {hasChunk && (
                      <p className="mt-2 text-xs text-gray-500">
                        Chunk ID: {claim.evidence_chunk_id}
                        {source &&
                          ` · [${source.rank}] ${source.filename}${
                            source.page_number != null
                              ? `, page ${source.page_number}`
                              : ""
                          }`}
                      </p>
                    )}
                  </>
                ) : (
                  <p className="text-sm text-gray-500">
                    No verified evidence in the retrieved passages.
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
  );
}

function EvidenceList({ evidence, citations }) {
  return (
    <>
      {Array.isArray(evidence) && evidence.length > 0 ? (
        <div className="mt-4 space-y-3">
          {evidence.map((item, index) => (
            <article
              key={`${item.chunk_id ?? index}-${item.rank ?? index}`}
              className="rounded-xl border p-4"
              style={{ borderColor: BORDER }}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-gray-800">
                    {item.filename ?? `Evidence ${index + 1}`}
                  </h3>
                  {item.page_number != null && (
                    <p className="mt-1 text-xs text-gray-500">
                      Page {item.page_number}
                    </p>
                  )}
                </div>

                {typeof item.similarity === "number" && (
                  <Badge style={{ color: PURPLE, backgroundColor: "#E5DBE6" }}>
                    Similarity: {item.similarity.toFixed(3)}
                  </Badge>
                )}
              </div>

              <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-gray-600">
                {item.content ?? "No evidence text was returned."}
              </p>

              <div className="mt-3 flex flex-wrap gap-3 text-xs text-gray-500">
                <span>Rank: {item.rank ?? "N/A"}</span>
                <span>Chunk ID: {item.chunk_id ?? "N/A"}</span>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="mt-4 rounded-xl p-4" style={{ backgroundColor: "#F5F5F4" }}>
          <p className="text-sm text-gray-600">
            No retrieved evidence was returned for this attempt.
          </p>
        </div>
      )}

      {Array.isArray(citations) && citations.length > 0 && (
        <div className="mt-5 border-t pt-4" style={{ borderColor: BORDER }}>
          <h3 className="text-sm font-bold" style={{ color: PURPLE }}>
            Answer citations
          </h3>
          <ul className="mt-2 list-inside list-disc space-y-2 text-sm text-gray-600">
            {citations.map((citation) => {
              // Citation numbers are 1-based positions in this attempt's retrieval list.
              const source = Array.isArray(evidence)
                ? evidence[citation - 1]
                : null;

              return (
                <li key={citation}>
                  [{citation}]
                  {source &&
                    ` ${source.filename}${
                      source.page_number != null
                        ? `, page ${source.page_number}`
                        : ""
                    } · Chunk ID ${source.chunk_id}`}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </>
  );
}

function AttemptCard({ attempt, finalAttemptNumber }) {
  const evaluation = attempt?.evaluation ?? null;
  const verdict = evaluationVerdict(evaluation);
  const reported = isReportedAttempt(attempt, finalAttemptNumber);
  const retrieval = attempt?.retrieval ?? [];
  const claims = evaluation?.claims ?? [];
  const timings = attempt?.timings ?? {};

  const timingDetails = [
    timings.retrieve_ms != null && `Retrieve ${timings.retrieve_ms} ms`,
    timings.generate_ms != null && `Generate ${timings.generate_ms} ms`,
    timings.evaluate_ms != null && `Evaluate ${timings.evaluate_ms} ms`,
    timings.input_tokens != null && `${timings.input_tokens} input tokens`,
    timings.output_tokens != null && `${timings.output_tokens} output tokens`,
  ].filter(Boolean);

  return (
    <article
      className="rounded-xl border p-4"
      style={{
        borderColor: reported ? PURPLE : BORDER,
        backgroundColor: reported ? "#FCFBFE" : "#FFFFFF",
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg font-bold" style={{ color: PURPLE }}>
          {attemptTitle(attempt)}
        </h3>
        <div className="flex flex-wrap gap-2">
          {reported && <ReportedBadge />}
          <Badge style={{ color: PURPLE, backgroundColor: "#E5DBE6" }}>
            Strategy: {formatLabel(attempt?.strategy)}
          </Badge>
          <Badge style={verdictStyle(attempt?.status)}>
            Status: {formatLabel(attempt?.status)}
          </Badge>
          <Badge style={verdictStyle(verdict)}>
            Evaluation: {formatVerdict(verdict)}
          </Badge>
        </div>
      </div>

      <dl className="mt-3 grid grid-cols-1 gap-2 text-xs text-gray-500 md:grid-cols-2">
        <div>
          <dt className="font-semibold uppercase tracking-wide">
            Retrieval query
          </dt>
          <dd className="mt-1 whitespace-pre-wrap text-sm text-gray-700">
            {attempt?.retrieval_query || "Not available"}
          </dd>
        </div>
        <div>
          <dt className="font-semibold uppercase tracking-wide">Model</dt>
          <dd className="mt-1 text-sm text-gray-700">
            {attempt?.model || "Not available"}
          </dd>
          {timingDetails.length > 0 && (
            <dd className="mt-1">{timingDetails.join(" · ")}</dd>
          )}
        </div>
      </dl>

      <div className="mt-4 border-t pt-4" style={{ borderColor: BORDER }}>
        <h4 className="text-sm font-bold" style={{ color: PURPLE }}>
          Answer
        </h4>
        <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-gray-700">
          {attempt?.answer || "No answer was returned for this attempt."}
        </p>
      </div>

      <div className="mt-4 border-t pt-4" style={{ borderColor: BORDER }}>
        <h4 className="text-sm font-bold" style={{ color: PURPLE }}>
          Attempt evaluation
        </h4>

        {evaluation ? (
          <>
            <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
              {SCORE_METRICS.map((metric) => (
                <ScoreCard
                  key={metric.key}
                  title={metric.title}
                  value={evaluation[metric.key]}
                  color={metric.color}
                  failureCause={
                    FAILURE_TYPE_METRIC[evaluation.failure_type] === metric.key
                  }
                />
              ))}
            </div>

            <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
              <div className="rounded-xl border p-4" style={{ borderColor: BORDER }}>
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                  Failure type
                </p>
                <p className="mt-2 text-sm font-semibold text-gray-800">
                  {evaluation.failure_type
                    ? formatLabel(evaluation.failure_type)
                    : "None reported"}
                </p>
              </div>

              <div className="rounded-xl border p-4" style={{ borderColor: BORDER }}>
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                  Evaluator feedback
                </p>
                <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-700">
                  {evaluation.feedback || "No evaluator feedback was returned."}
                </p>
              </div>
            </div>
          </>
        ) : (
          <div className="mt-3 rounded-xl p-4" style={{ backgroundColor: "#F5F5F4" }}>
            <p className="text-sm text-gray-600">
              This attempt was not evaluated, so no scores or feedback are
              available.
            </p>
          </div>
        )}
      </div>

      {evaluation && (
        <details className="mt-4 border-t pt-4" style={{ borderColor: BORDER }}>
          <summary className="cursor-pointer text-sm font-bold" style={{ color: PURPLE }}>
            Claims ({claims.length})
          </summary>
          <ClaimList claims={claims} evidence={retrieval} />
        </details>
      )}

      <details className="mt-4 border-t pt-4" style={{ borderColor: BORDER }}>
        <summary className="cursor-pointer text-sm font-bold" style={{ color: PURPLE }}>
          Retrieved chunks ({retrieval.length})
        </summary>
        <EvidenceList evidence={retrieval} citations={attempt?.citations} />
      </details>
    </article>
  );
}

function AttemptHistory({ attempts, finalAttemptNumber }) {
  return (
    <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
      <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
        Attempt history ({attempts.length})
      </h2>
      <p className="mt-2 text-sm text-gray-500">
        Every attempt returned by the backend, in the order received. Each
        attempt shows its own evaluation; the attempt marked “Reported by
        query” is the one the query’s final answer and status come from.
      </p>

      {attempts.length === 0 ? (
        <div className="mt-4 rounded-xl p-4" style={{ backgroundColor: "#F5F5F4" }}>
          <p className="text-sm text-gray-600">
            No attempts were returned for this query.
          </p>
        </div>
      ) : (
        <div className="mt-4 space-y-4">
          {attempts.map((attempt, index) => (
            <AttemptCard
              key={attempt?.attempt_number ?? index}
              attempt={attempt}
              finalAttemptNumber={finalAttemptNumber}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function SettingsPanel() {
  const [settings, setSettings] = useState(() => {
    try {
      const saved = localStorage.getItem("relirag_evaluation_settings");
      const parsed = saved ? JSON.parse(saved) : {};
      // Older versions saved an evaluator threshold that no longer exists.
      delete parsed.evaluatorThreshold;

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
        queries from Ask. The similarity gate is a frontend preference and
        does not change backend processing. Pass/fail verdicts always come
        from the backend evaluator.
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

  const queryId = id || sessionStorage.getItem("relirag_last_query_id");

  useEffect(() => {
    let cancelled = false;

    async function loadQuery() {
      setLoading(true);
      setError("");
      setQuery(null);

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

  const attempts = Array.isArray(query?.attempts) ? query.attempts : [];
  const firstAttempt = attempts[0] ?? null;
  const lastAttempt = attempts.length > 1 ? attempts[attempts.length - 1] : null;

  // The query's final answer and status come from final_attempt_number,
  // which is not necessarily the last attempt.
  const finalAttemptNumber = query?.final_attempt_number ?? null;
  const finalAttempt =
    attempts.find((attempt) =>
      isReportedAttempt(attempt, finalAttemptNumber)
    ) ?? null;
  const finalEvaluation = finalAttempt?.evaluation ?? null;
  const finalAttemptLabel = finalAttempt
    ? attemptTitle(finalAttempt)
    : "the reported attempt";

  const question = query?.question ?? "Question not available";
  const answer = query?.final_answer ?? "";

  const failureMetric = FAILURE_TYPE_METRIC[finalEvaluation?.failure_type];
  const scores = SCORE_METRICS.map((metric) => ({
    ...metric,
    value: finalEvaluation?.[metric.key],
    failureCause: failureMetric === metric.key,
  }));

  const finalVerdict = evaluationVerdict(finalEvaluation);

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
                Final answer
                {finalAttempt && (
                  <span className="ml-2 text-xs font-semibold text-gray-500">
                    from {finalAttemptLabel}
                  </span>
                )}
              </h3>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-gray-700">
                {answer || "No final answer was returned."}
              </p>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              <Badge style={{ color: PURPLE, backgroundColor: "#E5DBE6" }}>
                Query status: {formatLabel(query?.status)}
              </Badge>
              {query?.mode && (
                <Badge style={{ color: PURPLE, backgroundColor: "#E5DBE6" }}>
                  Mode: {formatLabel(query.mode)}
                </Badge>
              )}
              <Badge style={{ color: PURPLE, backgroundColor: "#E5DBE6" }}>
                Reported attempt:{" "}
                {finalAttemptNumber ?? "Not available"} of {attempts.length}
              </Badge>
              {finalAttempt?.status && (
                <Badge style={verdictStyle(finalAttempt.status)}>
                  Attempt status: {formatLabel(finalAttempt.status)}
                </Badge>
              )}
            </div>
          </section>

          <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
                  Final evaluation
                </h2>
                <p className="mt-2 text-sm text-gray-500">
                  {finalAttempt
                    ? `Evaluation of ${finalAttemptLabel}, the attempt this query reports. The verdict and failure type are the backend evaluator's saved result and are not recomputed in the browser. Individual attempt evaluations are listed under Attempt history. N/A means the backend did not return that score.`
                    : "The backend did not identify a reported attempt for this query, so no final evaluation is shown."}
                </p>
              </div>
              {finalAttempt && (
                <Badge style={verdictStyle(finalVerdict)}>
                  {formatVerdict(finalVerdict)}
                </Badge>
              )}
            </div>

            {finalAttempt && !finalEvaluation && (
              <div className="mt-4 rounded-xl p-4" style={{ backgroundColor: "#F5F5F4" }}>
                <p className="text-sm text-gray-600">
                  {finalAttemptLabel} was not evaluated, so no final scores or
                  feedback are available.
                </p>
              </div>
            )}

            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
              {scores.map((score) => (
                <ScoreCard
                  key={score.key}
                  title={score.title}
                  value={score.value}
                  color={score.color}
                  description={score.description}
                  failureCause={score.failureCause}
                />
              ))}
            </div>

            {finalEvaluation && (
              <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
                <div className="rounded-xl border p-4" style={{ borderColor: BORDER }}>
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                    Failure type
                  </p>
                  <p className="mt-2 text-sm font-semibold text-gray-800">
                    {finalEvaluation.failure_type
                      ? formatLabel(finalEvaluation.failure_type)
                      : "None reported"}
                  </p>
                </div>

                <div className="rounded-xl border p-4" style={{ borderColor: BORDER }}>
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                    Evaluator feedback
                  </p>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-700">
                    {finalEvaluation.feedback ||
                      "No evaluator feedback was returned."}
                  </p>
                </div>
              </div>
            )}
          </section>

          <AttemptHistory
            attempts={attempts}
            finalAttemptNumber={finalAttemptNumber}
          />

          {firstAttempt && lastAttempt && (
            <>
              <AnswerComparison
                before={firstAttempt}
                after={lastAttempt}
                finalAttemptNumber={finalAttemptNumber}
              />

              <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
                <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
                  Score comparison
                </h2>
                <p className="mt-2 text-sm text-gray-500">
                  Scores of every attempt, with the change from the previous
                  attempt in percentage points (pp).
                </p>
                <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
                  {SCORE_METRICS.map((metric) => (
                    <ScoreComparison
                      key={metric.key}
                      title={metric.title}
                      metric={metric.key}
                      attempts={attempts}
                      finalAttemptNumber={finalAttemptNumber}
                    />
                  ))}
                </div>
              </section>
            </>
          )}

          <CorrectionReason attempts={attempts} />

          <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
            <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
              Claim analysis
            </h2>
            <p className="mt-2 text-sm text-gray-500">
              Examine the claims of {finalAttemptLabel} and their evaluation
              verdicts. Claims of other attempts are under Attempt history.
            </p>

            <ClaimList
              key={`${query.query_id}-${finalAttemptNumber}`}
              claims={finalEvaluation?.claims}
              evidence={finalAttempt?.retrieval ?? []}
            />
          </section>

          <section className="border bg-white p-5 shadow-sm" style={cardStyle}>
            <h2 className="text-xl font-bold" style={{ color: PURPLE }}>
              Retrieved evidence
            </h2>
            <p className="mt-2 text-sm text-gray-500">
              Passages retrieved for {finalAttemptLabel} and supplied to the
              answer-generation process. Passages of other attempts are under
              Attempt history.
            </p>

            <EvidenceList
              evidence={finalAttempt?.retrieval}
              citations={finalAttempt?.citations}
            />
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

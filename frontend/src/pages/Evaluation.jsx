
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getQuery, USE_MOCK } from "../../api/client";
import { thresholdCheck, thresholdPercent } from "../evaluationThreshold.js";
import { comparisonScores, SINGLE_MODE_MESSAGE } from "../comparisonScores.js";

const C = {
  purple: "#554188",
  purpleLight: "#F0EBFA",
  lavender: "#E5DBE6",
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

function formatLabel(value) {
  if (value == null || value === "") return "Not available";
  return String(value).replaceAll("_", " ");
}

function normalizedScore(value) {
  if (
    value == null ||
    value === "" ||
    !Number.isFinite(Number(value))
  ) {
    return null;
  }

  const number = Number(value);
  return number <= 1 ? number * 100 : number;
}

function formatScore(value) {
  const score = normalizedScore(value);
  return score === null ? "N/A" : `${score.toFixed(1)}%`;
}

function badgeStyle(value) {
  const status = String(value ?? "").toUpperCase();

  if (
    ["PASSED", "PASS", "SUPPORTED", "CORRECT", "ANSWERED"].includes(status)
  ) {
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
    ].includes(status)
  ) {
    return { color: C.red, background: C.redLight };
  }

  return { color: C.muted, background: "#F2F0F5" };
}

function SectionHeading({ eyebrow, title, description, icon }) {
  return (
    <div className="flex flex-wrap items-start gap-3">
      {icon && (
        <div
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl text-lg"
          style={{ background: C.purpleLight, color: C.purple }}
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

function ScoreCard({ title, value, description, color, tint, icon }) {
  const score = normalizedScore(value);
  const progress = score === null ? 0 : Math.max(0, Math.min(100, score));

  return (
    <article
      className="min-w-0 rounded-2xl border p-4 sm:p-5"
      style={{ background: tint, borderColor: color + "40" }}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-semibold" style={{ color: C.ink }}>
          {title}
        </p>
        <span
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-lg"
          style={{ background: "#FFFFFFB8", color }}
        >
          {icon}
        </span>
      </div>

      <p
        className="mt-4 text-3xl font-bold tracking-tight sm:text-4xl"
        style={{ color }}
      >
        {formatScore(value)}
      </p>

      <div
        className="mt-4 h-2 overflow-hidden rounded-full"
        style={{ background: "#FFFFFFC9" }}
        role="progressbar"
        aria-label={title}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress}
      >
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${progress}%`, background: color }}
        />
      </div>

      <p className="mt-3 text-xs leading-5" style={{ color: C.muted }}>
        {description}
      </p>
    </article>
  );
}

function getAttemptScore(attempt, key) {
  return normalizedScore(attempt?.evaluation?.[key]);
}

function ScoreComparison({ title, metric, before, after }) {
  const oldScore = getAttemptScore(before, metric);
  const newScore = getAttemptScore(after, metric);
  const difference =
    oldScore === null || newScore === null ? null : newScore - oldScore;

  return (
    <article
      className="rounded-2xl border p-4"
      style={{ borderColor: C.border, background: C.white }}
    >
      <h3 className="text-sm font-bold" style={{ color: C.ink }}>
        {title}
      </h3>

      <div className="mt-3 grid grid-cols-2 gap-3">
        <div className="rounded-xl p-3" style={{ background: C.redLight }}>
          <p className="text-xs" style={{ color: C.red }}>Before</p>
          <p className="mt-1 text-xl font-bold" style={{ color: C.red }}>
            {oldScore === null ? "N/A" : `${oldScore.toFixed(1)}%`}
          </p>
        </div>
        <div className="rounded-xl p-3" style={{ background: C.greenLight }}>
          <p className="text-xs" style={{ color: C.green }}>After</p>
          <p className="mt-1 text-xl font-bold" style={{ color: C.green }}>
            {newScore === null ? "N/A" : `${newScore.toFixed(1)}%`}
          </p>
        </div>
      </div>

      {difference !== null && (
        <p
          className="mt-3 text-xs font-bold"
          style={{
            color:
              difference > 0.05
                ? C.green
                : difference < -0.05
                  ? C.red
                  : C.muted,
          }}
        >
          {difference > 0.05 ? "↑ " : difference < -0.05 ? "↓ " : ""}
          {difference > 0 ? "+" : ""}
          {difference.toFixed(1)} percentage points
        </p>
      )}
    </article>
  );
}

function AttemptHistory({ attempts, finalAttempt }) {
  return (
    <section className="p-5 sm:p-6" style={panel}>
      <SectionHeading
        eyebrow="Trace the process"
        title="Attempts & answers"
        description="Follow each generated answer, its evaluation scores, and its correction status."
        icon="↻"
      />

      {attempts.length === 0 ? (
        <p
          className="mt-5 rounded-xl p-4 text-sm"
          style={{ background: C.canvas, color: C.muted }}
        >
          No individual attempts were returned by the backend.
        </p>
      ) : (
        <div className="relative mt-6 space-y-4">
          {attempts.map((item, index) => {
            const evaluation = item?.evaluation ?? {};
            const attemptNumber = item?.attempt_number ?? index + 1;
            const isFinal =
              finalAttempt != null &&
              Number(attemptNumber) === Number(finalAttempt.attempt_number);

            const status =
              evaluation.passed === true
                ? "PASSED"
                : evaluation.passed === false
                  ? "FAILED"
                  : item.status ?? "NOT EVALUATED";

            const metrics = [
              ["Faithfulness", evaluation.faithfulness],
              ["Answer relevance", evaluation.answer_relevance],
              ["Context relevance", evaluation.context_relevance],
            ];

            return (
              <article
                key={item.id ?? attemptNumber}
                className="overflow-hidden rounded-2xl border"
                style={{
                  borderColor: isFinal ? C.purple : C.border,
                  background: C.white,
                }}
              >
                <div
                  className="flex flex-wrap items-center justify-between gap-3 p-4"
                  style={{
                    background: isFinal ? C.purpleLight : C.canvas,
                  }}
                >
                  <div>
                    <p className="text-sm font-bold" style={{ color: C.ink }}>
                      Attempt {attemptNumber}
                      {isFinal ? " · Final attempt" : ""}
                    </p>
                    {item.model && (
                      <p className="mt-1 text-xs" style={{ color: C.muted }}>
                        Model: {item.model}
                      </p>
                    )}
                  </div>
                  <span
                    className="rounded-full px-3 py-1.5 text-xs font-bold"
                    style={badgeStyle(status)}
                  >
                    {formatLabel(status).toUpperCase()}
                  </span>
                </div>

                <div className="p-4 sm:p-5">
                  <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
                    {metrics.map(([label, value], metricIndex) => (
                      <div
                        key={label}
                        className="rounded-xl p-3"
                        style={{
                          background: [
                            C.pinkLight,
                            C.greenLight,
                            C.blueLight,
                          ][metricIndex],
                        }}
                      >
                        <p className="text-xs" style={{ color: C.muted }}>
                          {label}
                        </p>
                        <p
                          className="mt-1 text-lg font-bold"
                          style={{ color: C.ink }}
                        >
                          {formatScore(value)}
                        </p>
                      </div>
                    ))}
                  </div>

                  <h4 className="text-sm font-bold" style={{ color: C.ink }}>
                    Generated answer
                  </h4>
                  <p
                    className="mt-2 whitespace-pre-wrap text-sm leading-7"
                    style={{ color: C.muted }}
                  >
                    {item.answer || "No answer was returned for this attempt."}
                  </p>

                  {evaluation.feedback && (
                    <div
                      className="mt-4 rounded-xl p-4"
                      style={{ background: C.canvas }}
                    >
                      <p className="text-xs font-bold" style={{ color: C.purple }}>
                        Evaluator feedback
                      </p>
                      <p
                        className="mt-2 whitespace-pre-wrap text-sm leading-6"
                        style={{ color: C.muted }}
                      >
                        {evaluation.feedback}
                      </p>
                    </div>
                  )}

                  {item.retrieval_query && (
                    <details className="mt-4">
                      <summary
                        className="cursor-pointer text-sm font-semibold"
                        style={{ color: C.purple }}
                      >
                        View retrieval query
                      </summary>
                      <p
                        className="mt-3 whitespace-pre-wrap rounded-xl p-3 text-sm leading-6"
                        style={{ background: C.canvas, color: C.muted }}
                      >
                        {item.retrieval_query}
                      </p>
                    </details>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

function AnswerComparison({ before, after, reportedAttemptNumber }) {
  const reported = (attempt) =>
    Number(attempt?.attempt_number) === Number(reportedAttemptNumber) ? " · Reported" : "";
  const beforeText = before?.answer ?? "";
  const afterText = after?.answer ?? "";

  const splitSentences = (text) =>
    text.split(/(?<=[.!?])\s+/).map((s) => s.trim()).filter(Boolean);

  const oldSentences = splitSentences(beforeText);
  const newSentences = splitSentences(afterText);
  const removed = oldSentences.filter((s) => !newSentences.includes(s));
  const added = newSentences.filter((s) => !oldSentences.includes(s));

  return (
    <section className="p-5 sm:p-6" style={panel}>
      <SectionHeading
        eyebrow="Correction analysis"
        title="Before & after"
        description="Compare the first answer with the correction attempt. The reported answer is marked. Sentence differences use exact text matching."
        icon="⇄"
      />

      <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <article
          className="min-w-0 rounded-2xl border p-4 sm:p-5"
          style={{ borderColor: "#F2CDD5", background: "#FFF8F9" }}
        >
          <span
            className="inline-block rounded-full px-3 py-1 text-xs font-bold"
            style={{ background: C.redLight, color: C.red }}
          >
            ORIGINAL
          </span>
          <h3 className="mt-3 font-bold" style={{ color: C.ink }}>
            Attempt {before?.attempt_number}{reported(before)}
          </h3>
          <p className="mt-3 whitespace-pre-wrap text-sm leading-7" style={{ color: C.muted }}>
            {beforeText || "No original answer was returned."}
          </p>
        </article>

        <article
          className="min-w-0 rounded-2xl border p-4 sm:p-5"
          style={{ borderColor: "#C8E8D5", background: "#F6FCF8" }}
        >
          <span
            className="inline-block rounded-full px-3 py-1 text-xs font-bold"
            style={{ background: C.greenLight, color: C.green }}
          >
            CORRECTION
          </span>
          <h3 className="mt-3 font-bold" style={{ color: C.ink }}>
            Attempt {after?.attempt_number}{reported(after)}
          </h3>
          <p className="mt-3 whitespace-pre-wrap text-sm leading-7" style={{ color: C.muted }}>
            {afterText || "This attempt returned no answer."}
          </p>
        </article>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-2">
        <DifferenceList
          title="Removed or changed sentences"
          items={removed}
          empty="No removed sentences detected."
          tint={C.redLight}
          color={C.red}
        />
        <DifferenceList
          title="Added or changed sentences"
          items={added}
          empty="No added sentences detected."
          tint={C.greenLight}
          color={C.green}
        />
      </div>
    </section>
  );
}

function DifferenceList({ title, items, empty, tint, color }) {
  return (
    <div className="rounded-2xl border p-4" style={{ borderColor: C.border }}>
      <h3 className="text-sm font-bold" style={{ color }}>
        {title}
      </h3>
      {items.length ? (
        <ul className="mt-3 space-y-2">
          {items.map((sentence, index) => (
            <li
              key={`${index}-${sentence}`}
              className="rounded-xl p-3 text-sm leading-6"
              style={{ background: tint, color }}
            >
              {sentence}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm" style={{ color: C.muted }}>{empty}</p>
      )}
    </div>
  );
}

function CorrectionReason({ attempts, finalAttempt, selectionReason }) {
  const first = attempts[0];
  const correction = attempts.length > 1 ? attempts[attempts.length - 1] : null;
  const firstEvaluation = first?.evaluation;

  const fields = [
    ["Attempt 1 failure type", formatLabel(firstEvaluation?.failure_type)],
    [
      "Attempt 1 evaluator feedback",
      firstEvaluation?.feedback || "No evaluator feedback was returned.",
    ],
    ["Original retrieval query", first?.retrieval_query || "Not available"],
    [
      "Correction",
      correction
        ? `Attempt ${correction.attempt_number}: ${formatLabel(correction.strategy)} · ${formatLabel(correction.status)} · retrieval query: ${correction.retrieval_query || "Not available"}`
        : "No correction attempt was recorded.",
    ],
    [
      "Final selection",
      selectionReason ||
        (finalAttempt
          ? `Attempt ${finalAttempt.attempt_number} is reported.`
          : "No final attempt was reported."),
    ],
  ];

  return (
    <section className="p-5 sm:p-6" style={panel}>
      <SectionHeading
        eyebrow="Troubleshooting"
        title="Correction diagnostics"
        description="Inspect what triggered a correction, what the correction attempt did, and why the reported attempt was selected."
        icon="⌕"
      />

      <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-2">
        {fields.map(([label, value], index) => (
          <div
            key={label}
            className="min-w-0 rounded-2xl p-4"
            style={{ background: index % 2 ? C.canvas : C.purpleLight }}
          >
            <p className="text-xs font-bold uppercase tracking-wide" style={{ color: C.purple }}>
              {label}
            </p>
            <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6" style={{ color: C.ink }}>
              {value}
            </p>
          </div>
        ))}
      </div>

      {attempts.length === 1 && (
        <p
          className="mt-4 rounded-xl p-4 text-sm"
          style={{ background: C.amberLight, color: C.amber }}
        >
          Only one attempt is available. No separate correction attempt was returned.
        </p>
      )}
    </section>
  );
}

function BasicVsReliComparison({ query }) {
  const { available, metrics } = comparisonScores(query);

  return (
    <section className="p-5 sm:p-6" style={panel}>
      <SectionHeading
        eyebrow="System benchmarking"
        title="Basic RAG vs Attest"
        description="Compare actual scores returned for both systems. Correction attempts are not Basic RAG results."
        icon="⇆"
      />

      {available ? (
        <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-3">
          {metrics.map(({ title, key, basic: basicValue, reli: reliValue }) => {
            const basic = normalizedScore(basicValue);
            const reli = normalizedScore(reliValue);
            const difference =
              basic === null || reli === null ? null : reli - basic;

            return (
              <article
                key={key}
                className="rounded-2xl border p-4"
                style={{ borderColor: C.border }}
              >
                <h3 className="text-sm font-bold" style={{ color: C.ink }}>
                  {title}
                </h3>

                <div className="mt-3 grid grid-cols-2 gap-2">
                  <div className="rounded-xl p-3" style={{ background: C.blueLight }}>
                    <p className="text-xs" style={{ color: C.blue }}>Basic RAG</p>
                    <p className="mt-1 text-lg font-bold" style={{ color: C.ink }}>
                      {basic === null ? "N/A" : `${basic.toFixed(1)}%`}
                    </p>
                  </div>
                  <div className="rounded-xl p-3" style={{ background: C.purpleLight }}>
                    <p className="text-xs" style={{ color: C.purple }}>Attest</p>
                    <p className="mt-1 text-lg font-bold" style={{ color: C.purple }}>
                      {reli === null ? "N/A" : `${reli.toFixed(1)}%`}
                    </p>
                  </div>
                </div>

                <p className="mt-3 text-xs" style={{ color: difference === null ? C.muted : difference > 0 ? C.green : difference < 0 ? C.red : C.muted }}>
                  {difference === null
                    ? "Comparison scores were not returned by the backend."
                    : `Difference: ${difference > 0 ? "+" : ""}${difference.toFixed(1)} percentage points`}
                </p>
              </article>
            );
          })}
        </div>
      ) : (
        <div
          className="mt-5 rounded-2xl p-4 sm:p-5"
          style={{ background: C.canvas }}
        >
          <p className="text-sm leading-6" style={{ color: C.muted }}>
            {SINGLE_MODE_MESSAGE}
          </p>
          <Link
            to="/comparison"
            className="mt-4 inline-flex rounded-xl px-4 py-2.5 text-sm font-bold text-white transition hover:opacity-90"
            style={{ background: C.purple }}
          >
            Open Comparison Lab →
          </Link>
        </div>
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
        setError("No saved query is available. Open Ask, submit a question, and try again.");
        setLoading(false);
        return;
      }

      if (USE_MOCK) {
        setError("Evaluation details require real backend data. Turn mock mode off.");
        setLoading(false);
        return;
      }

      try {
        const response = await getQuery(queryId);
        if (cancelled) return;

        setQuery(response);

        const actualId = response?.query_id ?? queryId;
        try {
          sessionStorage.setItem("relirag_last_query_id", String(actualId));
        } catch {
          // The route query ID remains available without session storage.
        }
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
  const initialAttempt = attempts[0] ?? null;
  const correctionAttempt = attempts.length > 1 ? attempts[attempts.length - 1] : null;
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
    query?.question ?? query?.original_question ?? "Question not available";

  const finalAnswer =
    query?.final_answer ?? finalAttempt?.answer ?? query?.answer ?? "";

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
      metric: "faithfulness",
      title: "Faithfulness",
      value: evaluation?.faithfulness,
      color: C.pink,
      tint: C.pinkLight,
      icon: "✳",
      description: "Does the answer stay supported by retrieved evidence?",
    },
    {
      metric: "answer_relevance",
      title: "Answer relevance",
      value: evaluation?.answer_relevance,
      color: C.green,
      tint: C.greenLight,
      icon: "◎",
      description: "Does the answer address the user's question?",
    },
    {
      metric: "context_relevance",
      title: "Context relevance",
      value: evaluation?.context_relevance,
      color: C.blue,
      tint: C.blueLight,
      icon: "⌕",
      description: "Is the retrieved evidence relevant to the question?",
    },
  ];

  const threshold = thresholdCheck(evaluation);
  const thresholdResults = scores.map((score) => ({
    ...score,
    passed: threshold.scores[score.metric],
  }));
  const thresholdBadge = {
    passed: { label: "ALL SCORES PASS", style: badgeStyle("PASSED") },
    below_threshold: { label: "BELOW THRESHOLD", style: badgeStyle("FAILED") },
    evaluator_error: { label: "EVALUATOR ERROR", style: { color: C.amber, background: C.amberLight } },
    incomplete: { label: "INCOMPLETE", style: badgeStyle("UNKNOWN") },
    not_evaluated: { label: "NOT EVALUATED", style: badgeStyle("UNKNOWN") },
  }[threshold.status];

  const finalVerdict =
    evaluation?.passed === true
      ? "PASSED"
      : evaluation?.passed === false
        ? "FAILED"
        : finalAttempt?.status ?? query?.status ?? "NOT EVALUATED";

  return (
    <div className="evaluation-dashboard space-y-6">
      <header
        className="relative overflow-hidden p-6 sm:p-8"
        style={{
          ...panel,
          background: "linear-gradient(125deg, #F0EBFA 0%, #FDF7FA 58%, #EDF3FC 100%)",
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
              className="rounded-full px-3 py-1.5 text-xs font-bold tracking-wide"
              style={{ background: "#FFFFFFC9", color: C.purple }}
            >
              ATTEST
            </span>
            <span
              className="rounded-full px-3 py-1.5 text-xs font-semibold"
              style={{ background: "#FFFFFFA8", color: C.muted }}
            >
              Evaluation workspace
            </span>
          </div>

          <h1
            className="mt-4 text-3xl font-bold tracking-tight sm:text-4xl"
            style={{ color: C.purple }}
          >
            Evaluation details
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-7 sm:text-base" style={{ color: C.muted }}>
            Explore answer quality, follow correction attempts, and inspect the evidence behind each result.
          </p>

          {!loading && !error && query && (
            <div className="mt-5 flex flex-wrap gap-2">
              <span
                className="max-w-full break-all rounded-full px-3 py-2 text-xs font-semibold"
                style={{ background: "#FFFFFFC9", color: C.purple }}
              >
                Query ID: {query?.query_id ?? queryId}
              </span>
              <span
                className="rounded-full px-3 py-2 text-xs font-bold"
                style={badgeStyle(finalVerdict)}
              >
                {formatLabel(finalVerdict).toUpperCase()}
              </span>
            </div>
          )}
        </div>
      </header>

      {loading && (
        <section className="p-6" style={panel}>
          <div className="flex items-center gap-3">
            <div
              className="h-5 w-5 animate-spin rounded-full border-2 border-t-transparent"
              style={{ borderColor: C.purple, borderTopColor: "transparent" }}
            />
            <p className="text-sm" style={{ color: C.muted }}>
              Loading evaluation details from the backend...
            </p>
          </div>
        </section>
      )}

      {!loading && error && (
        <section
          className="p-5 sm:p-6"
          style={{
            ...panel,
            borderColor: "#F2CDD5",
            background: "#FFF8F9",
          }}
        >
          <div className="flex items-start gap-3">
            <span className="text-xl" style={{ color: C.red }}>!</span>
            <div>
              <h2 className="font-bold" style={{ color: C.red }}>
                Could not load evaluation
              </h2>
              <p className="mt-2 text-sm leading-6" style={{ color: C.muted }}>
                {error}
              </p>
              <Link
                to="/ask"
                className="mt-4 inline-flex rounded-xl px-4 py-2.5 text-sm font-bold text-white"
                style={{ background: C.purple }}
              >
                Return to Ask
              </Link>
            </div>
          </div>
        </section>
      )}

      {!loading && !error && query && (
        <>
          <section className="p-5 sm:p-6" style={panel}>
            <SectionHeading
              eyebrow="Request overview"
              title="Your question"
              description="The query being evaluated by the RELI-RAG pipeline."
              icon="?"
            />
            <p className="mt-5 text-lg font-semibold leading-8" style={{ color: C.ink }}>
              {question}
            </p>

            <div className="mt-4 flex flex-wrap gap-2">
              <span
                className="rounded-full px-3 py-1.5 text-xs font-semibold"
                style={{ background: C.purpleLight, color: C.purple }}
              >
                {attempts.length} attempt{attempts.length === 1 ? "" : "s"}
              </span>
              <span
                className="rounded-full px-3 py-1.5 text-xs font-semibold"
                style={badgeStyle(query?.status)}
              >
                Query: {formatLabel(query?.status)}
              </span>
              {finalAttempt?.attempt_number != null && (
                <span
                  className="rounded-full px-3 py-1.5 text-xs font-semibold"
                  style={{ background: C.blueLight, color: C.blue }}
                >
                  Final attempt #{finalAttempt.attempt_number}
                </span>
              )}
            </div>
          </section>

          <AttemptHistory attempts={attempts} finalAttempt={finalAttempt} />

          <section className="p-5 sm:p-6" style={panel}>
            <SectionHeading
              eyebrow="Final result"
              title="Answer quality overview"
              description="The final answer and the three evaluation metrics returned by the backend."
              icon="✧"
            />

            <div
              className="mt-5 rounded-2xl border p-4 sm:p-5"
              style={{ borderColor: C.border, background: C.canvas }}
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h3 className="font-bold" style={{ color: C.ink }}>
                  Final answer
                </h3>
                <span
                  className="rounded-full px-3 py-1.5 text-xs font-bold"
                  style={badgeStyle(finalVerdict)}
                >
                  {formatLabel(finalVerdict).toUpperCase()}
                </span>
              </div>
              <p className="mt-3 whitespace-pre-wrap text-sm leading-7" style={{ color: C.muted }}>
                {finalAnswer || "No final answer was returned."}
              </p>
            </div>

            <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-3">
              {scores.map((score) => (
                <ScoreCard key={score.title} {...score} />
              ))}
            </div>

            {evaluation?.feedback && (
              <div
                className="mt-4 rounded-2xl p-4"
                style={{ background: C.purpleLight }}
              >
                <h3 className="text-sm font-bold" style={{ color: C.purple }}>
                  Evaluator feedback
                </h3>
                <p className="mt-2 whitespace-pre-wrap text-sm leading-6" style={{ color: C.ink }}>
                  {evaluation.feedback}
                </p>
              </div>
            )}
          </section>

          {initialAttempt && finalAttempt && (
            <>
              {correctionAttempt ? (
                <AnswerComparison
                  before={initialAttempt}
                  after={correctionAttempt}
                  reportedAttemptNumber={finalAttempt.attempt_number}
                />
              ) : (
                <section className="p-5 sm:p-6" style={panel}>
                  <SectionHeading
                    title="Before & after comparison"
                    description="A comparison becomes available when the query has at least two attempts."
                    icon="⇄"
                  />
                  <p className="mt-4 rounded-xl p-4 text-sm" style={{ background: C.canvas, color: C.muted }}>
                    Only one attempt was returned. There is no separate correction answer to compare.
                  </p>
                </section>
              )}

              {correctionAttempt && (
                <section className="p-5 sm:p-6" style={panel}>
                  <SectionHeading
                    eyebrow="Metric changes"
                    title="Score changes"
                    description={`Compare attempt ${initialAttempt.attempt_number} with correction attempt ${correctionAttempt.attempt_number}. The reported answer is attempt ${finalAttempt.attempt_number}. This is a correction comparison, not a Basic RAG benchmark.`}
                    icon="↗"
                  />
                  <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-3">
                    <ScoreComparison title="Faithfulness" metric="faithfulness" before={initialAttempt} after={correctionAttempt} />
                    <ScoreComparison title="Answer relevance" metric="answer_relevance" before={initialAttempt} after={correctionAttempt} />
                    <ScoreComparison title="Context relevance" metric="context_relevance" before={initialAttempt} after={correctionAttempt} />
                  </div>
                </section>
              )}
            </>
          )}

          <CorrectionReason
            attempts={attempts}
            finalAttempt={finalAttempt}
            selectionReason={query?.selection_reason}
          />

          <section className="p-5 sm:p-6" style={panel}>
            <SectionHeading
              eyebrow="Quality gate"
              title="Evaluator threshold check"
              description={`Each score must be at least ${thresholdPercent()}%, the same pass threshold the backend evaluator uses. A score exactly at the threshold passes. This check does not rerun the evaluator.`}
              icon="✓"
            />

            <div
              className="mt-5 flex flex-wrap items-center justify-between gap-4 rounded-2xl p-4"
              style={{ background: C.purpleLight }}
            >
              <div>
                <p className="text-sm" style={{ color: C.muted }}>Required minimum score</p>
                <p className="mt-1 text-3xl font-bold" style={{ color: C.purple }}>
                  {thresholdPercent()}%
                </p>
              </div>
              <span
                className="rounded-full px-3 py-2 text-xs font-bold"
                style={thresholdBadge.style}
              >
                {thresholdBadge.label}
              </span>
            </div>

            {threshold.status === "evaluator_error" && (
              <p className="mt-3 text-xs leading-5" style={{ color: C.muted }}>
                The evaluator could not complete, so this answer fails regardless of the threshold.
              </p>
            )}
            {threshold.matchesVerdict === false && (
              <p className="mt-3 text-xs leading-5" style={{ color: C.muted }}>
                The stored verdict ({evaluation.passed ? "passed" : "failed"}) differs from this
                check. It was recorded with the pass threshold in effect when this answer was
                evaluated.
              </p>
            )}

            <div className="mt-4 space-y-3">
              {thresholdResults.map((score) => (
                <div
                  key={score.title}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4"
                  style={{ borderColor: C.border }}
                >
                  <div>
                    <p className="text-sm font-semibold" style={{ color: C.ink }}>
                      {score.title}
                    </p>
                    <p className="mt-1 text-xs" style={{ color: C.muted }}>
                      Score: {formatScore(score.value)}
                    </p>
                  </div>
                  <span
                    className="rounded-full px-3 py-1.5 text-xs font-bold"
                    style={
                      score.passed === null
                        ? badgeStyle("UNKNOWN")
                        : badgeStyle(score.passed ? "PASSED" : "FAILED")
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
          </section>

          <section className="p-5 sm:p-6" style={panel}>
            <SectionHeading
              eyebrow="Evidence verification"
              title="Claim analysis"
              description="Expand a claim to inspect its verdict and any supporting evidence returned by the evaluator."
              icon="⌕"
            />

            {claims.length ? (
              <div className="mt-5 space-y-3">
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

                  const selected = selectedClaim === index;

                  return (
                    <article
                      key={claim?.id ?? index}
                      className="rounded-2xl border p-4"
                      style={{
                        borderColor: selected ? C.purple : C.border,
                        background: selected ? "#FAF8FE" : C.white,
                      }}
                    >
                      <button
                        type="button"
                        onClick={() => setSelectedClaim(selected ? null : index)}
                        aria-expanded={selected}
                        className="flex w-full flex-wrap items-start justify-between gap-3 text-left"
                      >
                        <span className="flex-1 text-sm leading-6" style={{ color: C.ink }}>
                          <span className="mr-2 font-bold" style={{ color: C.purple }}>
                            Claim {index + 1}
                          </span>
                          {text}
                        </span>
                        {verdict && (
                          <span className="rounded-full px-3 py-1.5 text-xs font-bold" style={badgeStyle(verdict)}>
                            {formatLabel(verdict).toUpperCase()}
                          </span>
                        )}
                      </button>

                      {selected && typeof claim === "object" && claim !== null && (
                        <div className="mt-4 space-y-3 border-t pt-4" style={{ borderColor: C.border }}>
                          {claim.evidence_chunk_id != null && (
                            <p className="text-sm" style={{ color: C.muted }}>
                              <strong style={{ color: C.purple }}>Evidence chunk ID: </strong>
                              {claim.evidence_chunk_id}
                            </p>
                          )}
                          {claim.evidence_quote && (
                            <p className="text-sm leading-6" style={{ color: C.muted }}>
                              <strong style={{ color: C.purple }}>Evidence quote: </strong>
                              {claim.evidence_quote}
                            </p>
                          )}
                          {claim.reason && (
                            <p className="text-sm leading-6" style={{ color: C.muted }}>
                              <strong style={{ color: C.purple }}>Reason: </strong>
                              {claim.reason}
                            </p>
                          )}
                          <details>
                            <summary className="cursor-pointer text-xs font-bold" style={{ color: C.purple }}>
                              View complete claim data
                            </summary>
                            <pre className="mt-3 overflow-auto rounded-xl p-3 text-xs leading-5" style={{ background: "#30283E", color: "#F8F5FC" }}>
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
              <p className="mt-5 rounded-xl p-4 text-sm" style={{ background: C.canvas, color: C.muted }}>
                No individual claim analysis was returned for this attempt.
              </p>
            )}
          </section>

          <section className="p-5 sm:p-6" style={panel}>
            <SectionHeading
              eyebrow="Source inspection"
              title="Retrieved evidence"
              description="Inspect the passages returned by retrieval for the final attempt."
              icon="▤"
            />

            {evidence.length ? (
              <div className="mt-5 space-y-3">
                {evidence.map((item, index) => (
                  <article
                    key={item?.chunk_id ?? item?.id ?? index}
                    className="rounded-2xl border p-4 sm:p-5"
                    style={{ borderColor: C.border }}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <h3 className="break-words text-sm font-bold" style={{ color: C.ink }}>
                          {item?.filename ?? item?.document_name ?? item?.source ?? `Evidence ${index + 1}`}
                        </h3>
                        {item?.page_number != null && (
                          <p className="mt-1 text-xs" style={{ color: C.muted }}>
                            Page {item.page_number}
                          </p>
                        )}
                      </div>

                      {item?.similarity != null && Number.isFinite(Number(item.similarity)) && (
                        <span className="rounded-full px-3 py-1.5 text-xs font-bold" style={{ background: C.blueLight, color: C.blue }}>
                          Similarity: {Number(item.similarity).toFixed(3)}
                        </span>
                      )}
                    </div>

                    <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-7" style={{ color: C.muted }}>
                      {item?.content ?? item?.text ?? item?.chunk_text ?? "No evidence text was returned."}
                    </p>

                    <div className="mt-3 flex flex-wrap gap-3 text-xs" style={{ color: C.muted }}>
                      <span>Rank: {item?.rank ?? index + 1}</span>
                      <span>Chunk ID: {item?.chunk_id ?? "N/A"}</span>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <p className="mt-5 rounded-xl p-4 text-sm" style={{ background: C.canvas, color: C.muted }}>
                No retrieved evidence was returned for this query.
              </p>
            )}

            {citations.length > 0 && (
              <div className="mt-5 border-t pt-5" style={{ borderColor: C.border }}>
                <h3 className="text-sm font-bold" style={{ color: C.purple }}>
                  Answer citations
                </h3>
                <ul className="mt-3 space-y-2">
                  {citations.map((citation, index) => (
                    <li
                      key={index}
                      className="break-words rounded-xl p-3 text-sm leading-6"
                      style={{ background: C.canvas, color: C.muted }}
                    >
                      {typeof citation === "string" || typeof citation === "number"
                        ? String(citation)
                        : citation?.text ?? citation?.filename ?? JSON.stringify(citation)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          <BasicVsReliComparison query={query} />

          <footer className="flex flex-wrap items-center gap-3 pb-4">
            <Link
              to="/ask"
              className="rounded-xl border px-4 py-2.5 text-sm font-bold transition hover:opacity-80"
              style={{ borderColor: C.border, background: C.white, color: C.purple }}
            >
              ← Back to Ask
            </Link>

            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded-xl px-4 py-2.5 text-sm font-bold text-white transition hover:opacity-90"
              style={{ background: C.purple }}
            >
              ↻ Refresh evaluation
            </button>

            <Link
              to="/analytics"
              className="rounded-xl border px-4 py-2.5 text-sm font-bold transition hover:opacity-80"
              style={{ borderColor: C.border, background: C.white, color: C.purple }}
            >
              View analytics →
            </Link>
          </footer>
        </>
      )}
    </div>
  );
}

export default Evaluation;

// Displays the evaluator result returned with a /query attempt. It only renders API data;
// it never triggers an evaluation itself.

const PALETTE = {
  purple: "var(--color-primary)",
  lavender: "var(--color-lavender)",
  smoke: "var(--color-background)",
};

const FAILURE_LABELS = {
  unsupported_claim: "Unsupported claim",
  missing_info: "Missing information",
  irrelevant_retrieval: "Irrelevant retrieval",
  evaluator_error: "Evaluator error",
};

const VERDICTS = {
  supported: {
    label: "Supported",
    badge: "bg-green-100 text-green-800",
    accent: "var(--status-passed)",
  },
  partially_supported: {
    label: "Partially supported",
    badge: "bg-amber-100 text-amber-800",
    accent: "var(--status-corrected)",
  },
  unsupported: {
    label: "Unsupported",
    badge: "bg-red-100 text-red-800",
    accent: "var(--status-failed)",
  },
};

const UNKNOWN_VERDICT = {
  label: "Unverified",
  badge: "bg-gray-100 text-gray-700",
  accent: "var(--status-insufficient)",
};

const SCORES = [
  { key: "faithfulness", label: "Faithfulness", color: "var(--color-blue)" },
  { key: "answer_relevance", label: "Answer relevance", color: "var(--color-pink)" },
  { key: "context_relevance", label: "Context relevance", color: "var(--color-blue-soft)" },
];

function isScore(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function OutcomeBadge({ evaluation, evaluatorError }) {
  let className = "bg-gray-100 text-gray-700";
  let text = "Not determined";

  if (evaluatorError) {
    text = "Evaluation failed";
  } else if (evaluation.passed === true) {
    className = "bg-green-100 text-green-800";
    text = "✓ Passed";
  } else if (evaluation.passed === false) {
    className = "bg-red-100 text-red-800";
    text = "✕ Failed";
  }

  return (
    <span className={`rounded-full px-3 py-1.5 text-xs font-bold ${className}`}>
      {text}
    </span>
  );
}

function ScoreCard({ label, value, color }) {
  const scored = isScore(value);
  const percent = scored ? Math.round(Math.min(Math.max(value, 0), 1) * 100) : 0;

  return (
    <div className="rounded-xl p-4" style={{ backgroundColor: PALETTE.smoke }}>
      <p className="text-xs text-gray-500">{label}</p>
      <p className="mt-1 text-2xl font-bold" style={{ color: PALETTE.purple }}>
        {scored ? `${percent}%` : "—"}
      </p>
      <div
        className="mt-3 h-2 overflow-hidden rounded-full"
        style={{ backgroundColor: PALETTE.lavender }}
      >
        <div
          className="h-full rounded-full"
          style={{ width: `${percent}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}

function ClaimEvidence({ claim, source, onLocateEvidence }) {
  const hasChunk = claim.evidence_chunk_id !== null && claim.evidence_chunk_id !== undefined;

  if (!claim.evidence_quote && !hasChunk) {
    return (
      <p className="mt-3 text-xs text-gray-500">
        No verified evidence in the retrieved passages.
      </p>
    );
  }

  return (
    <div
      className="mt-3 rounded-lg border-l-4 p-3"
      style={{ borderColor: "var(--color-blue)", backgroundColor: PALETTE.smoke }}
    >
      {claim.evidence_quote && (
        <blockquote className="text-sm italic leading-6 text-gray-700">
          “{claim.evidence_quote}”
        </blockquote>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
        {hasChunk && <span>Chunk #{claim.evidence_chunk_id}</span>}
        {source && (
          <span className="break-all">
            [{source.rank}] {source.title}, p. {source.page}
          </span>
        )}
        {source && (
          <button
            type="button"
            onClick={() => onLocateEvidence(source.id)}
            className="font-semibold underline underline-offset-2"
            style={{ color: PALETTE.purple }}
          >
            Locate evidence
          </button>
        )}
      </div>
    </div>
  );
}

export default function EvaluationPanel({ evaluation, evaluateMs, evidence, onLocateEvidence }) {
  if (!evaluation) {
    return (
      <section className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm sm:p-6">
        <h2 className="text-lg font-bold" style={{ color: PALETTE.purple }}>
          Answer evaluation
        </h2>
        <p className="mt-2 text-sm text-gray-500">
          This answer has not been evaluated, so no reliability scores are available.
        </p>
      </section>
    );
  }

  const evaluatorError = evaluation.failure_type === "evaluator_error";
  const claims = evaluation.claims ?? [];
  const verdictCounts = claims.reduce((counts, claim) => {
    counts[claim.verdict] = (counts[claim.verdict] ?? 0) + 1;
    return counts;
  }, {});

  return (
    <section className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold" style={{ color: PALETTE.purple }}>
            Answer evaluation
          </h2>
          <p className="mt-1 text-sm text-gray-500">
            Claim-level verification of the answer against the retrieved evidence
            {isScore(evaluateMs) ? ` · ${evaluateMs} ms` : ""}
          </p>
        </div>

        <OutcomeBadge evaluation={evaluation} evaluatorError={evaluatorError} />
      </div>

      {evaluation.failure_type && (
        <p className="mt-4 text-sm text-gray-700">
          <span className="font-semibold" style={{ color: PALETTE.purple }}>
            Failure type:
          </span>{" "}
          {FAILURE_LABELS[evaluation.failure_type] ?? evaluation.failure_type}{" "}
          <code className="rounded bg-[#F5F5F4] px-1 font-mono text-xs text-gray-600">
            {evaluation.failure_type}
          </code>
        </p>
      )}

      {evaluatorError ? (
        <p
          role="status"
          className="mt-4 rounded-xl border p-4 text-sm leading-6 text-gray-700"
          style={{ borderColor: PALETTE.lavender, backgroundColor: PALETTE.smoke }}
        >
          The evaluator could not complete, so no scores or claim verdicts are available.
          The generated answer above is unchanged.
        </p>
      ) : (
        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          {SCORES.map((score) => (
            <ScoreCard
              key={score.key}
              label={score.label}
              value={evaluation[score.key]}
              color={score.color}
            />
          ))}
        </div>
      )}

      {evaluation.feedback && (
        <div className="mt-5 rounded-xl p-4" style={{ backgroundColor: PALETTE.smoke }}>
          <p className="text-xs text-gray-500">Evaluator feedback</p>
          <p className="mt-1 text-sm leading-6 text-gray-700">{evaluation.feedback}</p>
        </div>
      )}

      {!evaluatorError && (
        <div className="mt-5 border-t border-[#E5DBE6] pt-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm font-semibold" style={{ color: PALETTE.purple }}>
              Claim verification
            </p>
            {claims.length > 0 && (
              <p className="text-xs text-gray-500">
                {Object.entries(VERDICTS)
                  .map(([key, verdict]) => `${verdictCounts[key] ?? 0} ${verdict.label.toLowerCase()}`)
                  .join(" · ")}
              </p>
            )}
          </div>

          {claims.length === 0 ? (
            <p className="mt-3 text-sm text-gray-500">No claims were extracted from the answer.</p>
          ) : (
            <ol className="mt-3 space-y-3">
              {claims.map((claim, index) => {
                const verdict = VERDICTS[claim.verdict] ?? UNKNOWN_VERDICT;
                const source = evidence.find((item) => item.id === claim.evidence_chunk_id);

                return (
                  <li
                    key={index}
                    className="rounded-xl border border-l-4 p-4"
                    style={{ borderColor: PALETTE.lavender, borderLeftColor: verdict.accent }}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <p className="flex-1 text-sm font-medium leading-6 text-gray-800">
                        <span className="mr-2 text-xs font-bold text-gray-400">{index + 1}.</span>
                        {claim.claim_text}
                      </p>
                      <span
                        className={`shrink-0 rounded-full px-3 py-1 text-xs font-semibold ${verdict.badge}`}
                      >
                        {verdict.label}
                      </span>
                    </div>

                    <ClaimEvidence
                      claim={claim}
                      source={source}
                      onLocateEvidence={onLocateEvidence}
                    />
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      )}
    </section>
  );
}

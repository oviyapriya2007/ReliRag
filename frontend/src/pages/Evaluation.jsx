import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getQuery, USE_MOCK } from "../../api/client";

const PURPLE = "#554188";
const BLUE = "#738fbd";
const BORDER = "#E5DBE6";

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
  return `${Math.round(score <= 1 ? score * 100 : score)}%`;
}

function formatVerdict(verdict) {
  return formatLabel(verdict || "Not evaluated").toUpperCase();
}

function verdictStyle(verdict) {
  const value = String(verdict ?? "").toUpperCase();

  if (value === "PASSED" || value === "PASS") {
    return {
      color: "#166534",
      backgroundColor: "#DCFCE7",
    };
  }

  if (value === "CORRECTED") {
    return {
      color: "#92400E",
      backgroundColor: "#FEF3C7",
    };
  }

  if (
    value === "FAILED_AFTER_CORRECTION" ||
    value === "FAILED" ||
    value === "FAIL"
  ) {
    return {
      color: "#991B1B",
      backgroundColor: "#FEE2E2",
    };
  }

  return {
    color: "#57534E",
    backgroundColor: "#F5F5F4",
  };
}

function ScoreCard({ title, value, description, color }) {
  return (
    <article
      className="rounded-xl border p-4"
      style={{
        borderColor: color,
        borderRadius: "12px",
        backgroundColor: "#FFFFFF",
      }}
    >
      <p
        className="text-sm font-semibold"
        style={{ color }}
      >
        {title}
      </p>

      <p
        className="mt-2 text-3xl font-bold"
        style={{ color }}
      >
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

function Evaluation() {
  const { id } = useParams();

  const [query, setQuery] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedClaim, setSelectedClaim] = useState(null);

  const queryId =
    id || sessionStorage.getItem("relirag_last_query_id");

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

        sessionStorage.setItem(
          "relirag_last_query_id",
          String(actualId)
        );
      } catch (err) {
        if (!cancelled) {
          setError(
            err?.message || "Failed to load evaluation details."
          );
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
  const attempt = attempts[attempts.length - 1];

  const question =
    query?.question ??
    query?.original_question ??
    "Question not available";

  const answer =
    query?.final_answer ??
    attempt?.answer ??
    query?.answer ??
    "";

  const evaluation =
    attempt?.evaluation ??
    query?.evaluation ??
    {};

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

  const citations =
    attempt?.citations ??
    query?.citations ??
    [];

  const scores = [
    {
      title: "Faithfulness",
      value: evaluation?.faithfulness,
      color: "#EF4444",
      description:
        "Measures whether the answer is supported by the retrieved evidence.",
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

  return (
    <div className="space-y-6">
      <header>
        <p
          className="text-sm font-medium"
          style={{ color: BLUE }}
        >
          RELI-RAG
        </p>

        <h1
          className="mt-1 text-3xl font-bold"
          style={{ color: PURPLE }}
        >
          Evaluation Details
        </h1>

        <p className="mt-2 text-sm text-gray-500">
          Review answer quality, individual claims, and the
          evidence retrieved by the RAG pipeline.
        </p>
      </header>

      {loading && (
        <section
          className="border bg-white p-5"
          style={cardStyle}
        >
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

          <p className="mt-2 text-sm text-red-700">
            {error}
          </p>

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
          {/* Question and answer */}
          <section
            className="border bg-white p-5 shadow-sm"
            style={cardStyle}
          >
            <p
              className="text-xs font-semibold uppercase tracking-wide"
              style={{ color: BLUE }}
            >
              Evaluated question
            </p>

            <h2
              className="mt-2 text-xl font-bold leading-7"
              style={{ color: PURPLE }}
            >
              {question}
            </h2>

            <div
              className="mt-5 border-t pt-4"
              style={{ borderColor: BORDER }}
            >
              <h3
                className="text-sm font-bold"
                style={{ color: PURPLE }}
              >
                Generated answer
              </h3>

              <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-gray-700">
                {answer || "No answer was returned."}
              </p>
            </div>

            <div className="mt-4">
              <span
                className="inline-block rounded-full px-3 py-1 text-xs font-semibold"
                style={{
                  color: PURPLE,
                  backgroundColor: "#E5DBE6",
                }}
              >
                Status: {formatLabel(query?.status)}
              </span>
            </div>
          </section>

          {/* Evaluation scores */}
          <section
            className="border bg-white p-5 shadow-sm"
            style={cardStyle}
          >
            <h2
              className="text-xl font-bold"
              style={{ color: PURPLE }}
            >
              Evaluation scores
            </h2>

            <p className="mt-2 text-sm text-gray-500">
              These scores measure different aspects of answer
              quality. N/A means the backend did not return that
              score.
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

          {/* Claim analysis */}
          <section
            className="border bg-white p-5 shadow-sm"
            style={cardStyle}
          >
            <h2
              className="text-xl font-bold"
              style={{ color: PURPLE }}
            >
              Claim analysis
            </h2>

            <p className="mt-2 text-sm text-gray-500">
              Examine individual answer claims and their evaluation
              verdicts.
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
                      ? claim.verdict ??
                        claim.status ??
                        claim.result
                      : null;

                  const isSelected = selectedClaim === index;

                  return (
                    <article
                      key={claim.id ?? index}
                      className="rounded-xl border p-4"
                      style={{
                        borderColor: isSelected ? PURPLE : BORDER,
                        backgroundColor: isSelected
                          ? "#F7F4FB"
                          : "#FFFFFF",
                      }}
                    >
                      <button
                        type="button"
                        onClick={() =>
                          setSelectedClaim(
                            isSelected ? null : index
                          )
                        }
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
                            {formatVerdict(verdict)}
                          </span>
                        )}
                      </button>

                      {isSelected &&
                        typeof claim === "object" && (
                          <div
                            className="mt-4 border-t pt-3"
                            style={{ borderColor: BORDER }}
                          >
                            {claim.reason && (
                              <p className="text-sm leading-6 text-gray-600">
                                <strong style={{ color: PURPLE }}>
                                  Reason:{" "}
                                </strong>
                                {claim.reason}
                              </p>
                            )}

                            {claim.evidence && (
                              <p className="mt-2 text-sm leading-6 text-gray-600">
                                <strong style={{ color: PURPLE }}>
                                  Evidence:{" "}
                                </strong>
                                {typeof claim.evidence === "string"
                                  ? claim.evidence
                                  : JSON.stringify(claim.evidence)}
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
              <div
                className="mt-4 rounded-xl p-4"
                style={{ backgroundColor: "#F5F5F4" }}
              >
                <p className="text-sm text-gray-600">
                  No individual claim analysis was returned for
                  this query.
                </p>
              </div>
            )}
          </section>

          {/* Retrieved evidence */}
          <section
            className="border bg-white p-5 shadow-sm"
            style={cardStyle}
          >
            <h2
              className="text-xl font-bold"
              style={{ color: PURPLE }}
            >
              Retrieved evidence
            </h2>

            <p className="mt-2 text-sm text-gray-500">
              Passages retrieved from your selected documents and
              supplied to the answer-generation process.
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
                          style={{
                            color: PURPLE,
                            backgroundColor: "#E5DBE6",
                          }}
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
                      <span>
                        Chunk ID: {item.chunk_id ?? "N/A"}
                      </span>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div
                className="mt-4 rounded-xl p-4"
                style={{ backgroundColor: "#F5F5F4" }}
              >
                <p className="text-sm text-gray-600">
                  No retrieved evidence was returned for this query.
                </p>
              </div>
            )}

            {Array.isArray(citations) && citations.length > 0 && (
              <div
                className="mt-5 border-t pt-4"
                style={{ borderColor: BORDER }}
              >
                <h3
                  className="text-sm font-bold"
                  style={{ color: PURPLE }}
                >
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
              style={{
                color: PURPLE,
                borderColor: BORDER,
              }}
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
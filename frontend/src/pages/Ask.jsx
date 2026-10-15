import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  USE_MOCK,
  getDocuments,
  getQuery,
  runQuery,
} from "../../api/client";

const PURPLE = "#554188";
const BLUE = "#738fbd";
const BORDER = "#E5DBE6";
const DARK_TEXT = "#292524";
const MUTED_TEXT = "#57534E";

function Ask() {
  const [question, setQuestion] = useState("");
  const [documents, setDocuments] = useState([]);
  const [selectedDocuments, setSelectedDocuments] = useState([]);
  const [result, setResult] = useState(null);
  const [queryId, setQueryId] = useState(
    () => sessionStorage.getItem("relirag_last_query_id")
  );

  const [loading, setLoading] = useState(false);
  const [loadingDocuments, setLoadingDocuments] = useState(true);
  const [restoring, setRestoring] = useState(false);
  const [error, setError] = useState("");
  const [showEvidence, setShowEvidence] = useState(true);
  const [showDebug, setShowDebug] = useState(false);

  // Load available documents.
  useEffect(() => {
    let cancelled = false;

    async function loadDocuments() {
      setLoadingDocuments(true);

      try {
        const data = await getDocuments();

        if (cancelled) return;

        const items = Array.isArray(data)
          ? data
          : data?.documents ?? [];

        setDocuments(items);
        setSelectedDocuments(items.map((document) => document.id));
      } catch (err) {
        if (!cancelled) {
          setError(err?.message || "Could not load documents.");
        }
      } finally {
        if (!cancelled) {
          setLoadingDocuments(false);
        }
      }
    }

    loadDocuments();

    return () => {
      cancelled = true;
    };
  }, []);

  // Restore the most recent query.
  useEffect(() => {
    let cancelled = false;

    async function restoreLastQuery() {
      const savedId = sessionStorage.getItem("relirag_last_query_id");

      if (!savedId || USE_MOCK) return;

      setRestoring(true);

      try {
        const savedResult = await getQuery(savedId);

        if (cancelled) return;

        const actualId = savedResult?.query_id ?? savedId;

        setQueryId(String(actualId));
        setResult(savedResult);

        if (savedResult?.question) {
          setQuestion(savedResult.question);
        }
      } catch (err) {
        if (!cancelled) {
          console.error("Could not restore previous query:", err);
        }
      } finally {
        if (!cancelled) {
          setRestoring(false);
        }
      }
    }

    restoreLastQuery();

    return () => {
      cancelled = true;
    };
  }, []);

  // Select or deselect an individual document.
  function toggleDocument(documentId) {
    setSelectedDocuments((current) =>
      current.includes(documentId)
        ? current.filter((id) => id !== documentId)
        : [...current, documentId]
    );
  }

  // Select or deselect all available documents.
  function toggleAllDocuments() {
    setSelectedDocuments((current) =>
      current.length === documents.length
        ? []
        : documents.map((document) => document.id)
    );
  }

  // Submit the question to the backend.
  async function handleSubmit(event) {
    event.preventDefault();

    const submittedQuestion = question.trim();

    if (!submittedQuestion) {
      setError("Please enter a question first.");
      return;
    }

    setLoading(true);
    setError("");
    setResult(null);

    try {
      const response = await runQuery({
        question: submittedQuestion,
        documentIds: selectedDocuments,
      });

      const savedId = response?.query_id;

      if (savedId !== null && savedId !== undefined) {
        sessionStorage.setItem(
          "relirag_last_query_id",
          String(savedId)
        );

        setQueryId(String(savedId));
      }

      setResult(response);
    } catch (err) {
      setError(err?.message || "Could not submit your question.");
    } finally {
      setLoading(false);
    }
  }

  // Extract the latest attempt and its results.
  const attempts = result?.attempts ?? [];
  const attempt = attempts[attempts.length - 1];

  const answer =
    result?.final_answer ??
    attempt?.answer ??
    result?.answer ??
    "";

  const status = String(
    result?.final_status ??
      result?.status ??
      attempt?.status ??
      "UNKNOWN"
  ).toUpperCase();

  const retrieval = attempt?.retrieval ?? result?.retrieval ?? [];
  const citations = attempt?.citations ?? result?.citations ?? [];
  const evaluation = attempt?.evaluation ?? result?.evaluation ?? null;
  const timings = attempt?.timings ?? result?.timings ?? {};

  const insufficientEvidence =
    status === "INSUFFICIENT_EVIDENCE" ||
    status === "INSUFFICIENT DOCUMENT EVIDENCE";

  // Display scores consistently when the backend returns 0–1 or 0–100.
  function formatScore(value) {
    if (
      value === null ||
      value === undefined ||
      value === "" ||
      !Number.isFinite(Number(value))
    ) {
      return "N/A";
    }

    const numericValue = Number(value);
    const percentage =
      numericValue >= 0 && numericValue <= 1
        ? numericValue * 100
        : numericValue;

    return `${Math.round(percentage)}%`;
  }

  return (
    <div className="space-y-6">
      {/* Page header */}
      <header>
        <p
          className="text-sm font-semibold"
          style={{ color: BLUE }}
        >
          RELI-RAG
        </p>

        <h1
          className="mt-1 text-3xl font-bold"
          style={{ color: PURPLE }}
        >
          Ask a Question
        </h1>

        <p
          className="mt-2 text-sm"
          style={{ color: DARK_TEXT }}
        >
          Ask questions about your uploaded documents and inspect
          the evidence behind each answer.
        </p>
      </header>

      {/* Question form */}
      <section
        className="border bg-white p-5 shadow-sm"
        style={{
          borderColor: BORDER,
          borderRadius: "16px",
        }}
      >
        <form onSubmit={handleSubmit} className="space-y-4">
          <label
            htmlFor="question"
            className="block text-sm font-semibold"
            style={{ color: PURPLE }}
          >
            Your question
          </label>

          <textarea
            id="question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Example: What does network segmentation do?"
            rows={4}
            className="w-full rounded-xl border p-3 text-sm outline-none focus:ring-2"
            style={{
              borderColor: BORDER,
              color: DARK_TEXT,
              backgroundColor: "#FFFFFF",
            }}
          />

          {/* Source document selector */}
          <div>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2
                className="text-sm font-bold"
                style={{ color: PURPLE }}
              >
                Select source documents
              </h2>

              {documents.length > 0 && (
                <button
                  type="button"
                  onClick={toggleAllDocuments}
                  className="text-sm font-semibold underline"
                  style={{ color: PURPLE }}
                >
                  {selectedDocuments.length === documents.length
                    ? "Deselect all"
                    : "Select all"}
                </button>
              )}
            </div>

            {loadingDocuments ? (
              <p className="text-sm" style={{ color: DARK_TEXT }}>
                Loading documents...
              </p>
            ) : documents.length > 0 ? (
              <div className="space-y-2">
                {documents.map((document) => (
                  <label
                    key={document.id}
                    className="flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition-colors hover:bg-gray-50"
                    style={{
                      borderColor: BORDER,
                      backgroundColor: "#FFFFFF",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={selectedDocuments.includes(document.id)}
                      onChange={() => toggleDocument(document.id)}
                      className="mt-1 accent-purple-800"
                    />

                    <span className="min-w-0">
                      <span
                        className="block break-words text-sm font-semibold"
                        style={{ color: DARK_TEXT }}
                      >
                        {document.filename ??
                          document.name ??
                          "Untitled document"}
                      </span>

                      <span
                        className="mt-1 block text-xs"
                        style={{ color: MUTED_TEXT }}
                      >
                        {document.total_pages != null
                          ? `${document.total_pages} pages`
                          : ""}
                        {document.total_chunks != null
                          ? ` · ${document.total_chunks} chunks`
                          : ""}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            ) : (
              <p className="text-sm" style={{ color: DARK_TEXT }}>
                No documents are available. Upload a document first.
              </p>
            )}
          </div>

          {/* Error message */}
          {error && (
            <div
              role="alert"
              className="rounded-xl border p-3 text-sm"
              style={{
                borderColor: "#FECACA",
                backgroundColor: "#FEF2F2",
                color: "#991B1B",
              }}
            >
              {error}
            </div>
          )}

          {/* Submit button */}
          <button
            type="submit"
            disabled={loading || !question.trim()}
            className="rounded-xl px-5 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
            style={{ backgroundColor: PURPLE }}
          >
            {loading ? "Processing your question..." : "Submit Question"}
          </button>

          {loading && (
            <p className="text-xs" style={{ color: DARK_TEXT }}>
              Retrieving evidence and evaluating the answer...
            </p>
          )}
        </form>
      </section>

      {restoring && !result && (
        <p className="text-sm" style={{ color: DARK_TEXT }}>
          Restoring your previous question and answer...
        </p>
      )}

      {result && (
        <div className="space-y-5">
          {/* Answer / Insufficient evidence */}
          {insufficientEvidence ? (
            <section
              role="status"
              aria-live="polite"
              className="rounded-2xl border p-5"
              style={{
                borderColor: "#D6D3D1",
                backgroundColor: "#F5F5F4",
                color: DARK_TEXT,
              }}
            >
              <div className="flex items-start gap-3">
                <span
                  aria-hidden="true"
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-lg font-bold"
                  style={{
                    backgroundColor: "#E7E5E4",
                    color: "#292524",
                  }}
                >
                  !
                </span>

                <div className="min-w-0">
                  <h2
                    className="text-base font-bold"
                    style={{
                      color: "#292524",
                      backgroundColor: "transparent",
                    }}
                  >
                    Insufficient evidence
                  </h2>

                  <p
                    className="mt-2 text-sm leading-6"
                    style={{
                      color: "#44403C",
                      backgroundColor: "transparent",
                    }}
                  >
                    The uploaded documents do not contain enough
                    information to answer this question reliably.
                    Try rephrasing your question or selecting
                    relevant documents.
                  </p>

                  <p
                    className="mt-3 text-xs font-semibold"
                    style={{ color: "#57534E" }}
                  >
                    Status: {status.replaceAll("_", " ")}
                  </p>
                </div>
              </div>
            </section>
          ) : (
            <section
              className="border bg-white p-5 shadow-sm"
              style={{
                borderColor: BORDER,
                borderRadius: "16px",
              }}
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2
                  className="text-lg font-bold"
                  style={{ color: PURPLE }}
                >
                  Answer
                </h2>

                <span
                  className="rounded-full px-3 py-1 text-xs font-semibold"
                  style={{
                    color: PURPLE,
                    backgroundColor: "#E5DBE6",
                  }}
                >
                  {status.replaceAll("_", " ")}
                </span>
              </div>

              <div
                className="mt-4 whitespace-pre-wrap text-sm leading-7"
                style={{ color: DARK_TEXT }}
              >
                {answer || "No answer was returned."}
              </div>

              {citations.length > 0 && (
                <div className="mt-4">
                  <h3
                    className="text-sm font-semibold"
                    style={{ color: PURPLE }}
                  >
                    Citations
                  </h3>

                  <ul
                    className="mt-2 list-inside list-disc space-y-1 text-sm"
                    style={{ color: DARK_TEXT }}
                  >
                    {citations.map((citation, index) => (
                      <li key={index}>
                        {typeof citation === "string"
                          ? citation
                          : citation.text ??
                            citation.filename ??
                            `Citation ${index + 1}`}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>
          )}

          {/* Evaluation details */}
          {queryId && (
            <section
              className="border bg-white p-5"
              style={{
                borderColor: BORDER,
                borderRadius: "16px",
              }}
            >
              <h2 className="font-bold" style={{ color: PURPLE }}>
                Evaluation details
              </h2>

              <p
                className="mt-1 text-sm"
                style={{ color: DARK_TEXT }}
              >
                Inspect faithfulness, answer relevance, context
                relevance, claim verdicts, and retrieved evidence.
              </p>

              <Link
                to={`/query/${encodeURIComponent(queryId)}`}
                className="mt-4 inline-block rounded-xl px-4 py-2 text-sm font-semibold text-white"
                style={{ backgroundColor: PURPLE }}
              >
                View Evaluation Details
              </Link>
            </section>
          )}

          {/* Evaluation summary */}
          {evaluation && (
            <section
              className="border bg-white p-5 shadow-sm"
              style={{
                borderColor: BORDER,
                borderRadius: "16px",
              }}
            >
              <h2
                className="text-xl font-bold"
                style={{ color: PURPLE }}
              >
                Evaluation summary
              </h2>

              <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
                {[
                  {
                    label: "Faithfulness",
                    value: evaluation.faithfulness,
                    color: "#EF4444",
                  },
                  {
                    label: "Answer relevance",
                    value: evaluation.answer_relevance,
                    color: "#22C55E",
                  },
                  {
                    label: "Context relevance",
                    value: evaluation.context_relevance,
                    color: "#3B82F6",
                  },
                ].map((item) => (
                  <article
                    key={item.label}
                    className="rounded-xl border p-4"
                    style={{
                      borderColor: item.color,
                      backgroundColor: "#FFFFFF",
                    }}
                  >
                    <p
                      className="text-sm font-semibold"
                      style={{ color: item.color }}
                    >
                      {item.label}
                    </p>

                    <p
                      className="mt-2 text-3xl font-bold"
                      style={{ color: item.color }}
                    >
                      {formatScore(item.value)}
                    </p>
                  </article>
                ))}
              </div>
            </section>
          )}

          {/* Evidence Explorer */}
          <section
            className="border bg-white p-5"
            style={{
              borderColor: BORDER,
              borderRadius: "16px",
            }}
          >
            <button
              type="button"
              onClick={() => setShowEvidence((current) => !current)}
              className="flex w-full items-center justify-between gap-3 text-left"
            >
              <span className="font-bold" style={{ color: PURPLE }}>
                Evidence Explorer ({retrieval.length})
              </span>

              <span className="text-sm font-semibold" style={{ color: PURPLE }}>
                {showEvidence ? "Hide" : "Show"}
              </span>
            </button>

            {showEvidence && (
              <div className="mt-4 space-y-3">
                {retrieval.length > 0 ? (
                  retrieval.map((item, index) => (
                    <article
                      key={item.chunk_id ?? index}
                      className="rounded-xl border p-4"
                      style={{ borderColor: BORDER }}
                    >
                      <div className="flex flex-wrap justify-between gap-2">
                        <p
                          className="text-sm font-semibold"
                          style={{ color: DARK_TEXT }}
                        >
                          {item.filename ??
                            item.document_name ??
                            "Retrieved passage"}
                        </p>

                        <span className="text-xs" style={{ color: MUTED_TEXT }}>
                          {item.page_number != null
                            ? `Page ${item.page_number}`
                            : ""}
                        </span>
                      </div>

                      <p
                        className="mt-2 whitespace-pre-wrap text-sm leading-6"
                        style={{ color: DARK_TEXT }}
                      >
                        {item.content ??
                          item.text ??
                          "No passage text returned."}
                      </p>

                      <div
                        className="mt-3 flex flex-wrap gap-3 text-xs"
                        style={{ color: MUTED_TEXT }}
                      >
                        <span>Rank: {item.rank ?? index + 1}</span>
                        <span>Chunk ID: {item.chunk_id ?? "N/A"}</span>
                        <span>
                          Similarity:{" "}
                          {typeof item.similarity === "number"
                            ? item.similarity.toFixed(3)
                            : "N/A"}
                        </span>
                      </div>
                    </article>
                  ))
                ) : (
                  <p className="text-sm" style={{ color: DARK_TEXT }}>
                    No retrieval passages were returned.
                  </p>
                )}
              </div>
            )}
          </section>

          {/* Retrieval Debug Panel */}
          <section
            className="border bg-white p-5"
            style={{
              borderColor: BORDER,
              borderRadius: "16px",
            }}
          >
            <button
              type="button"
              onClick={() => setShowDebug((current) => !current)}
              className="flex w-full items-center justify-between gap-3 text-left"
            >
              <span className="font-bold" style={{ color: PURPLE }}>
                Retrieval Debug Panel
              </span>

              <span className="text-sm font-semibold" style={{ color: PURPLE }}>
                {showDebug ? "Hide" : "Show"}
              </span>
            </button>

            {showDebug && (
              <div className="mt-4 space-y-3">
                <div
                  className="rounded-xl p-3 text-sm"
                  style={{
                    backgroundColor: "#F5F5F4",
                    color: DARK_TEXT,
                  }}
                >
                  <p>
                    <strong>Query ID:</strong> {queryId ?? "Not returned"}
                  </p>

                  <p className="mt-1">
                    <strong>Status:</strong> {status}
                  </p>

                  <p className="mt-1">
                    <strong>Retrieved passages:</strong> {retrieval.length}
                  </p>

                  <p className="mt-1">
                    <strong>Evaluation time:</strong>{" "}
                    {timings.evaluate_ms != null
                      ? `${timings.evaluate_ms} ms`
                      : "Not available"}
                  </p>
                </div>

                <details>
                  <summary
                    className="cursor-pointer text-sm font-semibold"
                    style={{ color: PURPLE }}
                  >
                    View raw backend response
                  </summary>

                  <pre className="mt-3 max-h-96 overflow-auto rounded-xl bg-gray-900 p-4 text-xs text-gray-100">
                    {JSON.stringify(result, null, 2)}
                  </pre>
                </details>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

export default Ask;
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

const HISTORY_KEY = "relirag_query_history";
const LAST_QUERY_KEY = "relirag_last_query_id";
const MAX_HISTORY = 10;

const panelStyle = {
  borderColor: BORDER,
  borderRadius: "12px",
};

function readHistory() {
  try {
    const saved = localStorage.getItem(HISTORY_KEY);
    return saved ? JSON.parse(saved) : [];
  } catch {
    return [];
  }
}

function saveHistory(history) {
  try {
    localStorage.setItem(
      HISTORY_KEY,
      JSON.stringify(history.slice(0, MAX_HISTORY)),
    );
  } catch {
    // The query can still be used if browser storage is unavailable.
  }
}

function getStatus(data) {
  const attempt = data?.attempts?.at(-1);

  return (
    data?.final_status ??
    data?.status ??
    attempt?.status ??
    "UNKNOWN"
  ).toString().toUpperCase();
}

function formatScore(value) {
  if (value === null || value === undefined || value === "") {
    return "N/A";
  }

  const number = Number(value);

  if (!Number.isFinite(number)) return "N/A";

  return `${Math.round(
    number <= 1 ? number * 100 : number,
  )}%`;
}

function StatusBadge({ status }) {
  const normalized = (status || "UNKNOWN").toUpperCase();
  const insufficient = normalized.includes("INSUFFICIENT");
  const failed =
    normalized.includes("FAILED") ||
    normalized.includes("ERROR");

  const color = insufficient
    ? "#92400E"
    : failed
      ? "#991B1B"
      : normalized === "UNKNOWN"
        ? MUTED_TEXT
        : "#166534";

  const background = insufficient
    ? "#FEF3C7"
    : failed
      ? "#FEE2E2"
      : normalized === "UNKNOWN"
        ? "#F5F5F4"
        : "#DCFCE7";

  return (
    <span
      className="inline-block rounded-full px-2 py-1 text-xs font-semibold"
      style={{ color, backgroundColor: background }}
    >
      {normalized.replaceAll("_", " ")}
    </span>
  );
}

function HistorySidebar({ history, onClear }) {
  return (
    <aside
      className="h-fit border bg-white p-4 shadow-sm xl:sticky xl:top-6"
      style={panelStyle}
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-bold" style={{ color: PURPLE }}>
          Recent Query History
        </h2>

        {history.length > 0 && (
          <button
            type="button"
            onClick={onClear}
            className="text-xs font-medium text-red-600 hover:underline"
          >
            Clear
          </button>
        )}
      </div>

      <p className="mt-1 text-xs" style={{ color: MUTED_TEXT }}>
        Your latest {MAX_HISTORY} queries
      </p>

      {history.length === 0 ? (
        <div
          className="mt-5 rounded-lg border border-dashed p-4 text-center text-sm"
          style={{ borderColor: BORDER, color: MUTED_TEXT }}
        >
          <p className="text-2xl">◷</p>
          <p className="mt-2 font-medium">No recent queries</p>
          <p className="mt-1 text-xs">
            Ask a question to build your history.
          </p>
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          {history.map((item) => (
            <Link
              key={String(item.id)}
              to={`/query/${encodeURIComponent(item.id)}`}
              className="block rounded-lg border p-3 transition hover:bg-gray-50"
              style={{ borderColor: BORDER }}
            >
              <p
                className="line-clamp-3 text-sm font-medium"
                style={{ color: DARK_TEXT }}
              >
                {item.question}
              </p>

              <div className="mt-2">
                <StatusBadge status={item.status} />
              </div>

              <p
                className="mt-2 text-xs"
                style={{ color: MUTED_TEXT }}
              >
                {item.timestamp
                  ? new Date(item.timestamp).toLocaleString()
                  : "Recent query"}
              </p>

              <p className="mt-1 text-xs" style={{ color: BLUE }}>
                View query →
              </p>
            </Link>
          ))}
        </div>
      )}

      <p
        className="mt-4 border-t pt-3 text-xs"
        style={{ borderColor: BORDER, color: MUTED_TEXT }}
      >
        History is stored in this browser. Detailed results require
        the backend query to remain available.
      </p>
    </aside>
  );
}

function DocumentSelector({
  documents,
  selectedDocuments,
  onToggle,
  onToggleAll,
  loading,
}) {
  const allSelected =
    documents.length > 0 &&
    documents.every((doc) =>
      selectedDocuments.includes(String(doc.id)),
    );

  return (
    <section className="rounded-xl border bg-white p-5" style={panelStyle}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold" style={{ color: PURPLE }}>
            Knowledge Base
          </h2>
          <p className="mt-1 text-sm" style={{ color: MUTED_TEXT }}>
            Choose which documents to search.
          </p>
        </div>

        <button
          type="button"
          onClick={onToggleAll}
          disabled={loading || documents.length === 0}
          className="text-sm font-semibold disabled:opacity-50"
          style={{ color: BLUE }}
        >
          {allSelected ? "Deselect all" : "Select all"}
        </button>
      </div>

      {loading ? (
        <p className="mt-4 text-sm" style={{ color: MUTED_TEXT }}>
          Loading documents…
        </p>
      ) : documents.length === 0 ? (
        <p className="mt-4 text-sm" style={{ color: MUTED_TEXT }}>
          No documents available. Upload documents before querying.
        </p>
      ) : (
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {documents.map((doc) => {
            const id = String(doc.id);
            const checked = selectedDocuments.includes(id);

            return (
              <label
                key={id}
                className="flex cursor-pointer items-start gap-3 rounded-lg border p-3"
                style={{
                  borderColor: checked ? BLUE : BORDER,
                  backgroundColor: checked ? "#F4F7FC" : "white",
                }}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => onToggle(id)}
                  className="mt-1"
                />

                <span className="min-w-0">
                  <span className="block break-words text-sm font-medium">
                    {doc.name || doc.filename || `Document ${id}`}
                  </span>
                  <span
                    className="mt-1 block text-xs"
                    style={{ color: MUTED_TEXT }}
                  >
                    {doc.pages ?? "—"} pages · {doc.chunks ?? "—"} chunks
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      )}
    </section>
  );
}

function EvaluationSummary({ evaluation, attempt }) {
  const metrics = [
    {
      label: "Faithfulness",
      value:
        evaluation?.faithfulness ??
        evaluation?.faithfulness_score,
    },
    {
      label: "Answer relevance",
      value:
        evaluation?.answer_relevance ??
        evaluation?.answer_relevance_score,
    },
    {
      label: "Context relevance",
      value:
        evaluation?.context_relevance ??
        evaluation?.context_relevance_score,
    },
  ];

  return (
    <section className="rounded-xl border bg-white p-5" style={panelStyle}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold" style={{ color: PURPLE }}>
          Evaluation Summary
        </h2>
        <span className="text-xs" style={{ color: MUTED_TEXT }}>
          {attempt?.attempt_number
            ? `Attempt ${attempt.attempt_number}`
            : "Latest attempt"}
        </span>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        {metrics.map((metric) => (
          <div
            key={metric.label}
            className="rounded-lg p-4"
            style={{ backgroundColor: "#F5F5F4" }}
          >
            <p className="text-xs" style={{ color: MUTED_TEXT }}>
              {metric.label}
            </p>
            <p
              className="mt-2 text-2xl font-bold"
              style={{ color: PURPLE }}
            >
              {formatScore(metric.value)}
            </p>
          </div>
        ))}
      </div>

      <p className="mt-3 text-xs" style={{ color: MUTED_TEXT }}>
        Scores are displayed from the evaluation data returned by the backend.
      </p>
    </section>
  );
}

function EvidenceExplorer({ citations, retrieval }) {
  const [expanded, setExpanded] = useState(true);
  const items = retrieval || [];

  return (
    <section className="rounded-xl border bg-white p-5" style={panelStyle}>
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between gap-3 text-left"
      >
        <span>
          <span className="block font-semibold" style={{ color: PURPLE }}>
            Evidence Explorer
          </span>
          <span className="mt-1 block text-sm" style={{ color: MUTED_TEXT }}>
            Retrieved passages and supporting citations
          </span>
        </span>
        <span style={{ color: PURPLE }}>
          {expanded ? "−" : "+"}
        </span>
      </button>

      {expanded && (
        <div className="mt-4 space-y-3">
          {items.length === 0 ? (
            <p className="text-sm" style={{ color: MUTED_TEXT }}>
              No retrieved evidence was returned.
            </p>
          ) : (
            items.map((item, index) => (
              <article
                key={`${item.chunk_id ?? item.id ?? index}-${index}`}
                className="rounded-lg border p-4"
                style={{ borderColor: BORDER }}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-semibold">
                    [{item.rank ?? index + 1}]{" "}
                    {item.filename || item.document_name || "Source document"}
                  </p>

                  {item.similarity != null && (
                    <span
                      className="text-xs font-semibold"
                      style={{ color: BLUE }}
                    >
                      Similarity: {formatScore(item.similarity)}
                    </span>
                  )}
                </div>

                <p className="mt-1 text-xs" style={{ color: MUTED_TEXT }}>
                  {item.page_number != null
                    ? `Page ${item.page_number}`
                    : "Page not provided"}
                  {item.chunk_id != null
                    ? ` · Chunk ${item.chunk_id}`
                    : ""}
                </p>

                <p className="mt-3 whitespace-pre-wrap text-sm leading-6">
                  {item.content || item.text || "No passage text available."}
                </p>
              </article>
            ))
          )}

          {citations?.length > 0 && (
            <div
              className="rounded-lg p-3"
              style={{ backgroundColor: "#F5F5F4" }}
            >
              <p className="text-sm font-semibold">Answer citations</p>
              <p className="mt-1 text-sm" style={{ color: MUTED_TEXT }}>
                {citations
                  .map((citation) =>
                    typeof citation === "object"
                      ? citation.filename ||
                        citation.id ||
                        JSON.stringify(citation)
                      : citation,
                  )
                  .join(", ")}
              </p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function RetrievalDebugPanel({ retrieval, timings, attempts }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <section className="rounded-xl border bg-white p-5" style={panelStyle}>
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between gap-3 text-left"
      >
        <span>
          <span className="block font-semibold" style={{ color: PURPLE }}>
            Retrieval Debug Panel
          </span>
          <span className="mt-1 block text-sm" style={{ color: MUTED_TEXT }}>
            Inspect retrieval details, timings, and attempts
          </span>
        </span>
        <span style={{ color: PURPLE }}>
          {expanded ? "−" : "+"}
        </span>
      </button>

      {expanded && (
        <div className="mt-4 space-y-4">
          <div>
            <h3 className="text-sm font-semibold">Retrieved chunks</h3>
            <pre
              className="mt-2 overflow-x-auto rounded-lg p-3 text-xs"
              style={{ backgroundColor: "#F5F5F4" }}
            >
              {JSON.stringify(retrieval || [], null, 2)}
            </pre>
          </div>

          <div>
            <h3 className="text-sm font-semibold">Timings</h3>
            <pre
              className="mt-2 overflow-x-auto rounded-lg p-3 text-xs"
              style={{ backgroundColor: "#F5F5F4" }}
            >
              {JSON.stringify(timings || {}, null, 2)}
            </pre>
          </div>

          <div>
            <h3 className="text-sm font-semibold">Query attempts</h3>
            <pre
              className="mt-2 overflow-x-auto rounded-lg p-3 text-xs"
              style={{ backgroundColor: "#F5F5F4" }}
            >
              {JSON.stringify(attempts || [], null, 2)}
            </pre>
          </div>
        </div>
      )}
    </section>
  );
}

export default function Ask() {
  const [question, setQuestion] = useState("");
  const [documents, setDocuments] = useState([]);
  const [selectedDocuments, setSelectedDocuments] = useState([]);
  const [result, setResult] = useState(null);
  const [queryId, setQueryId] = useState(
    sessionStorage.getItem(LAST_QUERY_KEY),
  );
  const [queryHistory, setQueryHistory] = useState(readHistory);
  const [loading, setLoading] = useState(false);
  const [loadingDocuments, setLoadingDocuments] = useState(true);
  const [restoring, setRestoring] = useState(false);
  const [error, setError] = useState("");
  const [showEvidence, setShowEvidence] = useState(true);
  const [showDebug, setShowDebug] = useState(false);

  useEffect(() => {
    let active = true;

    async function loadDocuments() {
      try {
        const data = await getDocuments();

        if (!active) return;

        const list = Array.isArray(data) ? data : [];
        setDocuments(list);
        setSelectedDocuments(list.map((doc) => String(doc.id)));
      } catch (err) {
        if (active) {
          setError(err.message || "Failed to load documents.");
        }
      } finally {
        if (active) setLoadingDocuments(false);
      }
    }

    loadDocuments();

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;

    async function restoreLastQuery() {
      if (USE_MOCK || !queryId) return;

      setRestoring(true);

      try {
        const data = await getQuery(queryId);

        if (!active) return;

        setResult(data);
        if (data.question) setQuestion(data.question);
      } catch {
        // The last query may no longer exist on the backend.
      } finally {
        if (active) setRestoring(false);
      }
    }

    restoreLastQuery();

    return () => {
      active = false;
    };
  }, [queryId]);

  function recordHistory(id, submittedQuestion, data) {
    if (id == null) return;

    const entry = {
      id: String(id),
      question: submittedQuestion,
      status: getStatus(data),
      timestamp: new Date().toISOString(),
    };

    setQueryHistory((previous) => {
      const updated = [
        entry,
        ...previous.filter((item) => String(item.id) !== String(id)),
      ].slice(0, MAX_HISTORY);

      saveHistory(updated);
      return updated;
    });
  }

  function toggleDocument(id) {
    setSelectedDocuments((previous) =>
      previous.includes(id)
        ? previous.filter((item) => item !== id)
        : [...previous, id],
    );
  }

  function toggleAllDocuments() {
    const allSelected =
      documents.length > 0 &&
      documents.every((doc) =>
        selectedDocuments.includes(String(doc.id)),
      );

    setSelectedDocuments(
      allSelected ? [] : documents.map((doc) => String(doc.id)),
    );
  }

  async function handleSubmit(event) {
    event.preventDefault();

    const submittedQuestion = question.trim();

    if (!submittedQuestion) {
      setError("Please enter a question.");
      return;
    }

    if (selectedDocuments.length === 0) {
      setError("Select at least one document to search.");
      return;
    }

    setLoading(true);
    setError("");
    setResult(null);
    setShowEvidence(true);
    setShowDebug(false);

    try {
      // Read Top-k from Evaluation settings.
      let topK = 5;

      try {
        const savedSettings = JSON.parse(
          localStorage.getItem("relirag_evaluation_settings") || "{}"
        );

        const configuredTopK = Number(savedSettings.topK);

        if (
          Number.isInteger(configuredTopK) &&
          configuredTopK >= 1 &&
          configuredTopK <= 10
        ) {
          topK = configuredTopK;
        }
      } catch {
        // Keep the default Top-k value if settings are unavailable.
      }

      // Send Top-k along with the question.
      const data = await runQuery({
        question: submittedQuestion,
        documentIds: selectedDocuments,
        k: topK,
      });

      setResult(data);

      const id = data.query_id ?? data.id ?? null;

      if (id != null) {
        setQueryId(String(id));
        sessionStorage.setItem(LAST_QUERY_KEY, String(id));
        recordHistory(id, submittedQuestion, data);
      } else {
        setQueryHistory((previous) => {
          const updated = [
            {
              id: `local-${Date.now()}`,
              question: submittedQuestion,
              status: getStatus(data),
              timestamp: new Date().toISOString(),
            },
            ...previous,
          ].slice(0, MAX_HISTORY);

          saveHistory(updated);
          return updated;
        });
      }
    } catch (err) {
      setError(err.message || "Something went wrong while querying.");
    } finally {
      setLoading(false);
    }
  }

  function clearHistory() {
    setQueryHistory([]);
    saveHistory([]);
  }

  const attempts = result?.attempts || [];
  const latestAttempt = attempts.at(-1) || {};
  const answer =
    result?.final_answer ??
    result?.answer ??
    latestAttempt?.answer ??
    "";

  const status = getStatus(result || {});
  const retrieval =
    latestAttempt?.retrieval ??
    result?.retrieval ??
    [];

  const citations =
    latestAttempt?.citations ??
    result?.citations ??
    [];

  const evaluation =
    latestAttempt?.evaluation ??
    result?.evaluation ??
    latestAttempt?.scores ??
    {};

  const timings =
    latestAttempt?.timings ??
    result?.timings ??
    latestAttempt?.attempt_timings ??
    {};

  const insufficientEvidence =
    status.includes("INSUFFICIENT_EVIDENCE") ||
    status.includes("INSUFFICIENT") ||
    result?.insufficient_evidence === true;

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
      <div className="mb-6">
        <p className="text-sm font-semibold" style={{ color: BLUE }}>
          RELI-RAG · RETRIEVAL AUGMENTED GENERATION
        </p>
        <h1 className="mt-2 text-2xl font-bold" style={{ color: PURPLE }}>
          Ask a Question
        </h1>
        <p className="mt-2 text-sm" style={{ color: MUTED_TEXT }}>
          Ask questions grounded in your documents and inspect the evidence
          behind each answer.
        </p>
      </div>

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_300px]">
        <main className="min-w-0 space-y-5">
          <form
            onSubmit={handleSubmit}
            className="rounded-xl border bg-white p-5"
            style={panelStyle}
          >
            <label
              htmlFor="question"
              className="block font-semibold"
              style={{ color: PURPLE }}
            >
              Your question
            </label>

            <textarea
              id="question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask something about your uploaded documents..."
              rows={4}
              className="mt-3 w-full resize-y rounded-lg border p-3 text-sm outline-none focus:ring-2"
              style={{ borderColor: BORDER, color: DARK_TEXT }}
              disabled={loading}
            />

            <p className="mt-2 text-xs" style={{ color: MUTED_TEXT }}>
              Choose the relevant documents below before submitting.
            </p>

            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button
                type="submit"
                disabled={loading || loadingDocuments}
                className="rounded-lg px-5 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
                style={{ backgroundColor: PURPLE }}
              >
                {loading ? "Searching documents…" : "Ask RELI-RAG"}
              </button>

              <button
                type="button"
                onClick={() => {
                  setQuestion("");
                  setResult(null);
                  setError("");
                }}
                disabled={loading}
                className="rounded-lg border px-4 py-3 text-sm font-medium disabled:opacity-50"
                style={{ borderColor: BORDER, color: DARK_TEXT }}
              >
                Clear question
              </button>
            </div>
          </form>

          <DocumentSelector
            documents={documents}
            selectedDocuments={selectedDocuments}
            onToggle={toggleDocument}
            onToggleAll={toggleAllDocuments}
            loading={loadingDocuments}
          />

          {error && (
            <div
              role="alert"
              className="rounded-xl border p-4 text-sm"
              style={{
                borderColor: "#FCA5A5",
                backgroundColor: "#FEF2F2",
                color: "#991B1B",
              }}
            >
              <p className="font-semibold">Something needs attention</p>
              <p className="mt-1">{error}</p>
            </div>
          )}

          {restoring && (
            <p className="text-sm" style={{ color: MUTED_TEXT }}>
              Restoring your previous query…
            </p>
          )}

          {result && (
            <>
              <section
                className="rounded-xl border bg-white p-5"
                style={panelStyle}
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h2 className="font-semibold" style={{ color: PURPLE }}>
                    Query Result
                  </h2>
                  <StatusBadge status={status} />
                </div>

                {insufficientEvidence ? (
                  <div
                    className="mt-4 rounded-lg border p-4"
                    style={{
                      borderColor: "#F59E0B",
                      backgroundColor: "#FFFBEB",
                      color: "#92400E",
                    }}
                  >
                    <p className="font-bold">Insufficient Evidence</p>
                    <p className="mt-2 text-sm leading-6">
                      The retrieved documents do not provide enough
                      reliable evidence to answer this question confidently.
                      Try selecting other documents or asking a more specific
                      question.
                    </p>
                    {answer && (
                      <p className="mt-3 whitespace-pre-wrap text-sm leading-6">
                        {answer}
                      </p>
                    )}
                  </div>
                ) : (
                  <div className="mt-4 whitespace-pre-wrap text-sm leading-7">
                    {answer || "No answer was returned by the backend."}
                  </div>
                )}

                {queryId && (
                  <p className="mt-4 text-xs" style={{ color: MUTED_TEXT }}>
                    Query ID: {queryId}
                  </p>
                )}

                {queryId && !String(queryId).startsWith("local-") && (
                  <Link
                    to={`/query/${encodeURIComponent(queryId)}`}
                    className="mt-3 inline-block text-sm font-semibold hover:underline"
                    style={{ color: BLUE }}
                  >
                    View evaluation details →
                  </Link>
                )}
              </section>

              <EvaluationSummary
                evaluation={evaluation}
                attempt={latestAttempt}
              />

              <section
                className="rounded-xl border bg-white p-5"
                style={panelStyle}
              >
                <button
                  type="button"
                  onClick={() => setShowEvidence((value) => !value)}
                  className="flex w-full items-center justify-between text-left"
                >
                  <span className="font-semibold" style={{ color: PURPLE }}>
                    Evidence Explorer
                  </span>
                  <span style={{ color: PURPLE }}>
                    {showEvidence ? "Hide" : "Show"}
                  </span>
                </button>

                {showEvidence && (
                  <div className="mt-4">
                    <EvidenceExplorer
                      citations={citations}
                      retrieval={retrieval}
                    />
                  </div>
                )}
              </section>

              <section
                className="rounded-xl border bg-white p-5"
                style={panelStyle}
              >
                <button
                  type="button"
                  onClick={() => setShowDebug((value) => !value)}
                  className="flex w-full items-center justify-between text-left"
                >
                  <span className="font-semibold" style={{ color: PURPLE }}>
                    Retrieval Debug Panel
                  </span>
                  <span style={{ color: PURPLE }}>
                    {showDebug ? "Hide" : "Show"}
                  </span>
                </button>

                {showDebug && (
                  <div className="mt-4">
                    <RetrievalDebugPanel
                      retrieval={retrieval}
                      timings={timings}
                      attempts={attempts}
                    />
                  </div>
                )}
              </section>
            </>
          )}
        </main>

        <HistorySidebar
          history={queryHistory}
          onClear={clearHistory}
        />
      </div>
    </div>
  );
}

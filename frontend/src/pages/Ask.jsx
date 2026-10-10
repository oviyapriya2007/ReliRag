
import { useEffect, useMemo, useRef, useState } from "react";
import { USE_MOCK, getDocuments, runQuery } from "../../api/client";
import AnswerText from "../components/AnswerText";

const COLORS = {
  purple: "#554188",
  blue: "#738fbd",
  lightBlue: "#a8c3d4",
  pink: "#db88a4",
  lavender: "#E5DBE6",
  smoke: "#F5F5F4",
  taupe: "#BBADAD",
  indigo: "#7080DA",
};

const INSUFFICIENT_MESSAGE =
  "The uploaded documents do not contain enough information to answer this question reliably.";

// POST /query is a single request, so the "Generating" stage is shown after a short delay.
const GENERATING_STAGE_DELAY_MS = 800;

function toEvidence(chunk) {
  return {
    id: chunk.chunk_id,
    documentId: chunk.document_id,
    title: chunk.filename,
    page: chunk.page_number,
    rank: chunk.rank,
    score: chunk.similarity ?? 0,
    text: chunk.content,
  };
}

export default function Ask() {
  const [question, setQuestion] = useState("");
  const [documents, setDocuments] = useState([]);
  const [selectedDocuments, setSelectedDocuments] = useState([]);
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingStage, setLoadingStage] = useState("");
  const [showEvidence, setShowEvidence] = useState(true);
  const [showDebug, setShowDebug] = useState(false);
  const [activeEvidenceId, setActiveEvidenceId] = useState(null);
  const [answer, setAnswer] = useState("");
  const [status, setStatus] = useState("");
  const [evidence, setEvidence] = useState([]);
  const [citations, setCitations] = useState([]);
  const [latency, setLatency] = useState(null);
  const [error, setError] = useState("");

  const evidenceRefs = useRef({});

  const insufficientEvidence = status === "INSUFFICIENT_EVIDENCE";

  const citedEvidence = useMemo(
    () =>
      citations
        .map((number) => evidence.find((item) => item.rank === number))
        .filter(Boolean),
    [citations, evidence]
  );

  useEffect(() => {
    getDocuments()
      .then((loaded) => {
        setDocuments(loaded);
        setSelectedDocuments(loaded.map((document) => document.id));
      })
      .catch((loadError) => {
        console.error("Failed to load documents:", loadError);
        setError(`Failed to load documents: ${loadError.message}`);
      });
  }, []);

  const toggleDocument = (documentId) => {
    setSelectedDocuments((current) =>
      current.includes(documentId)
        ? current.filter((id) => id !== documentId)
        : [...current, documentId]
    );
  };

  const scrollToEvidence = (evidenceId) => {
    setActiveEvidenceId(evidenceId);
    setShowEvidence(true);

    window.setTimeout(() => {
      evidenceRefs.current[evidenceId]?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }, 100);
  };

  const handleSubmit = async (event) => {
    event.preventDefault();

    if (!question.trim() || selectedDocuments.length === 0 || loading) {
      return;
    }

    setSubmitted(false);
    setAnswer("");
    setStatus("");
    setEvidence([]);
    setCitations([]);
    setLatency(null);
    setError("");
    setActiveEvidenceId(null);
    setLoading(true);
    setLoadingStage("Retrieving relevant document passages...");

    const startTime = Date.now();
    const stageTimer = window.setTimeout(
      () => setLoadingStage("Generating an answer from the retrieved evidence..."),
      GENERATING_STAGE_DELAY_MS
    );

    try {
      const result = await runQuery({
        question: question.trim(),
        documentIds: selectedDocuments,
      });
      const attempt = result.attempts?.[result.attempts.length - 1];

      setStatus(result.status);
      setAnswer(result.final_answer ?? "");
      setEvidence((attempt?.retrieval ?? []).map(toEvidence));
      setCitations(attempt?.citations ?? []);
      setLatency(Date.now() - startTime);
      setSubmitted(true);
    } catch (queryError) {
      console.error("Query failed:", queryError);
      setError(queryError.message);
    } finally {
      window.clearTimeout(stageTimer);
      setLoading(false);
      setLoadingStage("");
    }
  };

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 p-4 sm:p-6 lg:p-8">
      {/* B1: Ask screen */}
      <header>
        <p
          className="text-sm font-semibold"
          style={{ color: COLORS.blue }}
        >
          DOCUMENT INTELLIGENCE
        </p>

        <h1
          className="mt-2 text-3xl font-bold tracking-tight"
          style={{ color: COLORS.purple }}
        >
          Ask RELI-RAG
        </h1>

        <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-600">
          Ask a question about your documents and explore the evidence
          behind the generated answer.
        </p>
      </header>

      <section className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm sm:p-6">
        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label
              htmlFor="reli-rag-question"
              className="mb-2 block text-sm font-semibold"
              style={{ color: COLORS.purple }}
            >
              Your question
            </label>

            <textarea
              id="reli-rag-question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Example: What is network security?"
              rows={3}
              required
              className="w-full resize-y rounded-xl border border-[#BBADAD] bg-white p-4 text-sm text-gray-800 outline-none transition focus:border-[#554188] focus:ring-2 focus:ring-[#E5DBE6]"
            />
          </div>

          <div>
            <h2
              className="mb-3 text-sm font-semibold"
              style={{ color: COLORS.purple }}
            >
              Search within documents
            </h2>

            <div className="grid gap-3 sm:grid-cols-2">
              {documents.map((document) => (
                <label
                  key={document.id}
                  className="flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition"
                  style={{
                    borderColor: selectedDocuments.includes(document.id)
                      ? COLORS.blue
                      : COLORS.lavender,
                    backgroundColor: selectedDocuments.includes(document.id)
                      ? COLORS.smoke
                      : "#FFFFFF",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={selectedDocuments.includes(document.id)}
                    onChange={() => toggleDocument(document.id)}
                    className="mt-1 accent-[#554188]"
                  />

                  <span className="min-w-0 break-all text-sm font-medium text-gray-700">
                    {document.name}
                  </span>
                </label>
              ))}
            </div>

            <p className="mt-2 text-xs text-gray-500">
              {documents.length > 0
                ? "Select one or more documents to search."
                : "No documents uploaded yet. Upload a PDF on the Documents page first."}
            </p>
          </div>

          <button
            type="submit"
            disabled={
              loading ||
              !question.trim() ||
              selectedDocuments.length === 0
            }
            className="rounded-xl px-5 py-3 text-sm font-semibold text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            style={{ backgroundColor: COLORS.purple }}
          >
            {loading ? "Working..." : "Ask question"}
          </button>
        </form>

        {loading && (
          <div
            role="status"
            className="mt-5 rounded-xl border p-4"
            style={{
              borderColor: COLORS.lavender,
              backgroundColor: COLORS.smoke,
            }}
          >
            <div className="flex items-center gap-3">
              <span
                className="h-3 w-3 animate-pulse rounded-full"
                style={{ backgroundColor: COLORS.pink }}
              />

              <p
                className="text-sm font-medium"
                style={{ color: COLORS.purple }}
              >
                {loadingStage}
              </p>
            </div>
          </div>
        )}

        {error && (
          <p
            role="alert"
            className="mt-5 rounded-xl border border-[#E7B8C2] bg-red-50 p-4 text-sm text-[#B4233D]"
          >
            {error}
          </p>
        )}
      </section>

      {submitted && (
        <div className="space-y-6">
          {/* B5: Insufficient-Evidence Card */}
          {insufficientEvidence && (
            <section
              role="alert"
              className="rounded-2xl border p-5 shadow-sm sm:p-6"
              style={{
                borderColor: COLORS.taupe,
                backgroundColor: COLORS.smoke,
              }}
            >
              <div className="flex items-start gap-4">
                <div
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-xl font-bold"
                  style={{
                    backgroundColor: COLORS.lavender,
                    color: COLORS.purple,
                  }}
                  aria-hidden="true"
                >
                  !
                </div>

                <div>
                  <h2
                    className="text-lg font-bold"
                    style={{ color: COLORS.purple }}
                  >
                    Insufficient Evidence
                  </h2>

                  <p className="mt-2 text-sm leading-6 text-gray-700">
                    {INSUFFICIENT_MESSAGE}
                  </p>

                  <p className="mt-3 text-xs leading-5 text-gray-500">
                    Try selecting relevant documents or asking a question
                    that can be answered using the available document content.
                  </p>
                </div>
              </div>
            </section>
          )}

          {/* B2, B3 and B4: Show only when evidence is sufficient */}
          {!insufficientEvidence && (
            <>
              {/* B2: Generated answer */}
              <section className="rounded-2xl border border-[#E5DBE6] bg-white p-5 shadow-sm sm:p-6">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2
                      className="text-lg font-bold"
                      style={{ color: COLORS.purple }}
                    >
                      Generated answer
                    </h2>

                    <p className="mt-1 text-sm text-gray-500">
                      Answer generated from the retrieved evidence
                    </p>
                  </div>

                  {USE_MOCK && (
                    <span
                      className="rounded-full px-3 py-1.5 text-xs font-bold"
                      style={{
                        backgroundColor: COLORS.lavender,
                        color: COLORS.purple,
                      }}
                    >
                      DEMO · MOCK DATA
                    </span>
                  )}
                </div>

                <AnswerText
                  text={answer}
                  className="mt-5 text-sm leading-7 text-gray-700"
                />

                <div className="mt-5 border-t border-[#E5DBE6] pt-4">
                  <p
                    className="mb-3 text-sm font-semibold"
                    style={{ color: COLORS.purple }}
                  >
                    Supporting citations
                  </p>

                  {citedEvidence.length === 0 && (
                    <p className="text-sm text-gray-500">
                      The answer did not cite any retrieved passage.
                    </p>
                  )}

                  <div className="flex flex-wrap gap-2">
                    {citedEvidence.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => scrollToEvidence(item.id)}
                        className="rounded-lg border px-3 py-2 text-xs font-semibold transition hover:opacity-80"
                        style={{
                          borderColor: COLORS.lightBlue,
                          backgroundColor: COLORS.smoke,
                          color: COLORS.purple,
                        }}
                      >
                        [{item.rank}] {item.title}, p. {item.page}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="mt-5 grid gap-3 sm:grid-cols-2">
                  <div
                    className="rounded-xl p-4"
                    style={{ backgroundColor: COLORS.smoke }}
                  >
                    <p className="text-xs text-gray-500">Answer status</p>
                    <p
                      className="mt-1 text-sm font-bold"
                      style={{ color: COLORS.purple }}
                    >
                      {status}
                    </p>
                  </div>

                  <div
                    className="rounded-xl p-4"
                    style={{ backgroundColor: COLORS.smoke }}
                  >
                    <p className="text-xs text-gray-500">
                      Total latency
                    </p>
                    <p
                      className="mt-1 text-sm font-bold"
                      style={{ color: COLORS.purple }}
                    >
                      {latency !== null ? `${latency} ms` : "—"}
                    </p>
                  </div>
                </div>
              </section>

              {/* B3: Evidence Explorer */}
              <section className="overflow-hidden rounded-2xl border border-[#E5DBE6] bg-white shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-3 p-5">
                  <div>
                    <h2
                      className="text-lg font-bold"
                      style={{ color: COLORS.purple }}
                    >
                      Retrieved evidence
                    </h2>

                    <p className="mt-1 text-sm text-gray-500">
                      Explore the retrieved passages behind this answer.
                    </p>
                  </div>

                  <button
                    type="button"
                    onClick={() => setShowEvidence((current) => !current)}
                    aria-expanded={showEvidence}
                    className="rounded-lg border px-3 py-2 text-sm font-semibold transition hover:opacity-80"
                    style={{
                      borderColor: COLORS.lavender,
                      backgroundColor: COLORS.smoke,
                      color: COLORS.purple,
                    }}
                  >
                    {showEvidence ? "Hide Evidence ▲" : "View Evidence ▼"}
                  </button>
                </div>

                {showEvidence && (
                  <div className="space-y-4 border-t border-[#E5DBE6] p-5">
                    {evidence.length > 0 ? (
                      evidence.map((item) => (
                        <article
                          key={item.id}
                          ref={(element) => {
                            evidenceRefs.current[item.id] = element;
                          }}
                          className="scroll-mt-6 rounded-xl border p-4 transition"
                          style={{
                            borderColor:
                              activeEvidenceId === item.id
                                ? COLORS.purple
                                : COLORS.lavender,
                            backgroundColor:
                              activeEvidenceId === item.id
                                ? "#F0EBF7"
                                : "#FFFFFF",
                            boxShadow:
                              activeEvidenceId === item.id
                                ? `0 0 0 2px ${COLORS.lavender}`
                                : "none",
                          }}
                        >
                          <div className="flex flex-wrap items-start justify-between gap-3">
                            <div className="min-w-0">
                              <h3
                                className="break-all text-sm font-bold"
                                style={{ color: COLORS.purple }}
                              >
                                {item.title}
                              </h3>

                              <p className="mt-1 text-xs text-gray-500">
                                Page {item.page}
                              </p>
                            </div>

                            <span
                              className="rounded-full px-3 py-1 text-xs font-bold"
                              style={{
                                backgroundColor: COLORS.lavender,
                                color: COLORS.purple,
                              }}
                            >
                              Citation {item.rank}
                            </span>
                          </div>

                          <p className="mt-4 text-sm leading-7 text-gray-700">
                            {item.text}
                          </p>

                          <button
                            type="button"
                            onClick={() => setActiveEvidenceId(item.id)}
                            className="mt-3 text-xs font-semibold underline underline-offset-2"
                            style={{ color: COLORS.purple }}
                          >
                            Highlight this passage
                          </button>
                        </article>
                      ))
                    ) : (
                      <p className="text-sm text-gray-500">
                        No passages were retrieved for the selected
                        documents.
                      </p>
                    )}
                  </div>
                )}
              </section>

              {/* B4: Retrieval Debug Panel */}
              <section className="overflow-hidden rounded-2xl border border-[#E5DBE6] bg-white shadow-sm">
                <button
                  type="button"
                  onClick={() => setShowDebug((current) => !current)}
                  aria-expanded={showDebug}
                  className="flex w-full items-center justify-between gap-3 p-5 text-left transition hover:bg-[#E5DBE6]/30"
                >
                  <div>
                    <h2
                      className="text-lg font-bold"
                      style={{ color: COLORS.purple }}
                    >
                      Retrieval Debug Panel
                    </h2>

                    <p className="mt-1 text-sm text-gray-500">
                      Inspect retrieved chunks, ranking, and similarity scores.
                    </p>
                  </div>

                  <span
                    className="shrink-0 rounded-lg px-3 py-2 text-sm font-semibold"
                    style={{
                      backgroundColor: COLORS.lavender,
                      color: COLORS.purple,
                    }}
                  >
                    {showDebug ? "Hide ▲" : "Show ▼"}
                  </span>
                </button>

                {showDebug && (
                  <div className="space-y-4 border-t border-[#E5DBE6] p-5">
                    <p
                      className="rounded-lg p-3 text-xs leading-5 text-gray-600"
                      style={{ backgroundColor: COLORS.smoke }}
                    >
                      {USE_MOCK
                        ? "Demo data: ranks and similarity scores are illustrative, not actual pgvector retrieval results."
                        : "Cosine similarity from pgvector (1 − distance) between the question and each chunk."}
                    </p>

                    {evidence.length > 0 ? (
                      evidence
                        .slice()
                        .sort((a, b) => a.rank - b.rank)
                        .map((item) => (
                          <article
                            key={item.id}
                            className="rounded-xl border p-4"
                            style={{
                              borderColor: COLORS.lavender,
                              backgroundColor: COLORS.smoke,
                            }}
                          >
                            <div className="flex flex-wrap items-center justify-between gap-3">
                              <span
                                className="rounded-full px-3 py-1 text-xs font-bold"
                                style={{
                                  backgroundColor: COLORS.lavender,
                                  color: COLORS.purple,
                                }}
                              >
                                Rank #{item.rank}
                              </span>

                              <span
                                className="text-sm font-bold"
                                style={{ color: COLORS.purple }}
                              >
                                {(item.score * 100).toFixed(0)}% similarity
                              </span>
                            </div>

                            <div
                              className="mt-3 h-2 overflow-hidden rounded-full"
                              style={{ backgroundColor: COLORS.lavender }}
                            >
                              <div
                                className="h-full rounded-full transition-all"
                                style={{
                                  width: `${Math.max(0, item.score) * 100}%`,
                                  backgroundColor: COLORS.blue,
                                }}
                              />
                            </div>

                            <h3
                              className="mt-3 break-all text-sm font-semibold"
                              style={{ color: COLORS.purple }}
                            >
                              {item.title}
                            </h3>

                            <p className="mt-1 text-xs text-gray-500">
                              Page {item.page}
                            </p>

                            <p className="mt-3 text-sm leading-6 text-gray-700">
                              {item.text}
                            </p>

                            <button
                              type="button"
                              onClick={() => scrollToEvidence(item.id)}
                              className="mt-3 text-xs font-semibold underline underline-offset-2"
                              style={{ color: COLORS.purple }}
                            >
                              Locate evidence
                            </button>
                          </article>
                        ))
                    ) : (
                      <p className="text-sm text-gray-500">
                        No chunks were retrieved for the selected
                        documents.
                      </p>
                    )}
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      )}
    </main>
  );
}

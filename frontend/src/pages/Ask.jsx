
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
const SETTINGS_KEY = "relirag_evaluation_settings";
const MAX_HISTORY = 10;

const panelStyle = {
  borderColor: BORDER,
  borderRadius: "12px",
};

const QUERY_MODES = [
  {
    value: "basic",
    label: "Basic",
    description: "Single attempt",
  },
  {
    value: "reli",
    label: "RELI",
    description: "Evaluation + up to one correction retry",
  },
];

const DEFAULT_MODE = "reli";

const DEFAULT_SETTINGS = {
  topK: 5,
  evaluatorThreshold: 0.7,
  similarityGate: 0.5,
};

const PIPELINE_STAGES = [
  {
    name: "Retrieve",
    detail: "Finding relevant document passages",
  },
  {
    name: "Generate",
    detail: "Generating an evidence-based answer",
  },
  {
    name: "Evaluate",
    detail: "Checking answer quality and faithfulness",
  },
  {
    name: "Correct",
    detail: "Attempting to improve a failed answer",
  },
  {
    name: "Re-evaluate",
    detail: "Checking the updated answer",
  },
];

function readSettings() {
  try {
    return {
      ...DEFAULT_SETTINGS,
      ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}"),
    };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

// Collapsible evaluation settings panel
function EvaluationSettingsPanel() {
  const [settings, setSettings] = useState(readSettings);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    } catch {
      // Settings are optional if browser storage is unavailable.
    }
  }, [settings]);

  function updateSetting(name, value) {
    setSettings((previous) => ({
      ...previous,
      [name]: value,
    }));
  }

  return (
    <section className="overflow-hidden rounded-xl border bg-white" style={panelStyle}>
      <button
        type="button"
        onClick={() => setExpanded((previous) => !previous)}
        aria-expanded={expanded}
        className="flex w-full items-center justify-between gap-4 p-5 text-left transition hover:bg-gray-50"
      >
        <span className="min-w-0">
          <span
            className="block font-semibold"
            style={{ color: PURPLE }}
          >
            Evaluation settings
          </span>
          <span
            className="mt-1 block text-sm"
            style={{ color: MUTED_TEXT }}
          >
            Configure retrieval preferences
          </span>
        </span>

        <span
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-lg transition-transform duration-300"
          style={{
            backgroundColor: "#F0ECF7",
            color: PURPLE,
            transform: expanded ? "rotate(180deg)" : "rotate(0deg)",
          }}
          aria-hidden="true"
        >
          ▾
        </span>
      </button>

      {expanded && (
        <div
          className="border-t p-5"
          style={{ borderColor: BORDER }}
        >
          <p className="text-sm leading-6" style={{ color: MUTED_TEXT }}>
            These preferences are saved in this browser. Top-k is sent with
            new queries. The similarity gate is a frontend preference and
            does not change backend processing. Pass/fail verdicts come from
            the backend.
          </p>

          <div className="mt-5 grid gap-5 sm:grid-cols-2">
            <div>
              <div className="flex items-center justify-between gap-3">
                <label htmlFor="ask-top-k" className="text-sm font-medium">
                  Top-k retrieval
                </label>
                <span
                  className="text-sm font-semibold"
                  style={{ color: PURPLE }}
                >
                  {settings.topK}
                </span>
              </div>

              <input
                id="ask-top-k"
                type="range"
                min="1"
                max="10"
                step="1"
                value={settings.topK}
                onChange={(event) =>
                  updateSetting("topK", Number(event.target.value))
                }
                className="mt-3 w-full"
              />

              <p className="mt-2 text-xs" style={{ color: MUTED_TEXT }}>
                Number of passages requested during retrieval.
              </p>
            </div>

            <div>
              <div className="flex items-center justify-between gap-3">
                <label
                  htmlFor="ask-similarity-gate"
                  className="text-sm font-medium"
                >
                  Similarity gate
                </label>
                <span
                  className="text-sm font-semibold"
                  style={{ color: PURPLE }}
                >
                  {Number(settings.similarityGate).toFixed(2)}
                </span>
              </div>

              <input
                id="ask-similarity-gate"
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={settings.similarityGate}
                onChange={(event) =>
                  updateSetting("similarityGate", Number(event.target.value))
                }
                className="mt-3 w-full"
              />

              <p className="mt-2 text-xs" style={{ color: MUTED_TEXT }}>
                Preferred minimum similarity when inspecting evidence.
              </p>
            </div>
          </div>

          <div
            className="mt-5 border-t pt-4"
            style={{ borderColor: BORDER }}
          >
            <button
              type="button"
              onClick={() => setSettings({ ...DEFAULT_SETTINGS })}
              className="rounded-lg border px-4 py-2 text-sm font-medium transition hover:bg-gray-50"
              style={{ borderColor: BORDER, color: DARK_TEXT }}
            >
              Reset settings
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

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
      JSON.stringify(history.slice(0, MAX_HISTORY))
    );
  } catch {
    // Query history is optional.
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

  return `${Math.round(number <= 1 ? number * 100 : number)}%`;
}

function StatusBadge({ status }) {
  const normalized = (status || "UNKNOWN").toUpperCase();
  const insufficient = normalized.includes("INSUFFICIENT");
  const failed =
    normalized.includes("FAILED") || normalized.includes("ERROR");

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

              <p className="mt-2 text-xs" style={{ color: MUTED_TEXT }}>
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
        History is stored in this browser. Detailed results require the
        backend query to remain available.
      </p>
    </aside>
  );
}

function ModeSelector({ mode, onChange, disabled }) {
  return (
    <fieldset className="mt-4" disabled={disabled}>
      <legend className="text-sm font-semibold" style={{ color: PURPLE }}>
        Mode
      </legend>

      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        {QUERY_MODES.map((option) => {
          const checked = mode === option.value;

          return (
            <label
              key={option.value}
              className="flex cursor-pointer items-start gap-3 rounded-lg border p-3"
              style={{
                borderColor: checked ? BLUE : BORDER,
                backgroundColor: checked ? "#F4F7FC" : "white",
                opacity: disabled ? 0.6 : 1,
              }}
            >
              <input
                type="radio"
                name="query-mode"
                value={option.value}
                checked={checked}
                onChange={() => onChange(option.value)}
                className="mt-1"
              />

              <span className="min-w-0">
                <span
                  className="block text-sm font-medium"
                  style={{ color: DARK_TEXT }}
                >
                  {option.label}
                </span>
                <span
                  className="mt-1 block text-xs"
                  style={{ color: MUTED_TEXT }}
                >
                  {option.description}
                </span>
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
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
    documents.every((doc) => selectedDocuments.includes(String(doc.id)));

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

const PIPELINE_STAGE_MS = 2200;

function prefersReducedMotion() {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function useReducedMotion() {
  const [reducedMotion, setReducedMotion] = useState(prefersReducedMotion);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return undefined;

    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReducedMotion(media.matches);
    media.addEventListener?.("change", sync);
    return () => media.removeEventListener?.("change", sync);
  }, []);

  return reducedMotion;
}

// Mounted only while a query is in flight so stage state remounts cleanly.
function IllustrativePipelineProgress({ reducedMotion }) {
  const stageCount = PIPELINE_STAGES.length;
  const [activeStage, setActiveStage] = useState(() =>
    reducedMotion ? stageCount - 1 : 0,
  );

  useEffect(() => {
    if (reducedMotion) return undefined;

    const interval = window.setInterval(() => {
      setActiveStage((current) => Math.min(current + 1, stageCount - 1));
    }, PIPELINE_STAGE_MS);

    return () => window.clearInterval(interval);
  }, [reducedMotion, stageCount]);

  const focusStage = reducedMotion ? stageCount - 1 : activeStage;
  const illustrativeProgress = ((focusStage + 1) / stageCount) * 100;

  return (
    <>
      <div className="pipeline-progress mt-4">
        <div className="flex items-center justify-between gap-3 text-xs">
          <span style={{ color: MUTED_TEXT }}>
            {reducedMotion
              ? "Reduced motion: static wait indicator"
              : `Stage ${focusStage + 1} of ${stageCount} (time-based)`}
          </span>
          <span className="font-semibold" style={{ color: PURPLE }}>
            {Math.round(illustrativeProgress)}%
          </span>
        </div>
        <div
          className="pipeline-progress-track mt-2"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(illustrativeProgress)}
          aria-label="Illustrative pipeline progress"
        >
          <div
            className="pipeline-progress-fill"
            style={{ width: `${illustrativeProgress}%` }}
          />
        </div>
      </div>

      <PipelineStageGrid
        loading
        reducedMotion={reducedMotion}
        activeStage={focusStage}
        getStageState={(index) => {
          if (index < focusStage) return "elapsed";
          if (index === focusStage) return "active";
          return "pending";
        }}
        getStageMessage={(_index, state) => {
          if (state === "active") {
            return reducedMotion
              ? "Waiting for backend response…"
              : "Illustrative focus…";
          }
          if (state === "elapsed") return "Elapsed (illustrative)";
          return "Waiting";
        }}
      />

      <p className="mt-4 text-xs" style={{ color: MUTED_TEXT }}>
        Stage highlighting is a time-based visual aid while waiting for the
        backend. It does not report live stage completion. Actual evaluation
        and correction results appear when the response arrives.
      </p>
    </>
  );
}

function PipelineStageGrid({
  loading,
  reducedMotion,
  activeStage,
  getStageState,
  getStageMessage,
}) {
  const stageCount = PIPELINE_STAGES.length;

  return (
    <div className="pipeline-stage-grid mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      {PIPELINE_STAGES.map((stage, index) => {
        const state = getStageState(index);
        const active = state === "active";
        const complete = state === "complete";
        const elapsed = state === "elapsed";
        const failed = state === "failed";
        const skipped = state === "skipped";

        const borderColor = active
          ? BLUE
          : complete
            ? "#86EFAC"
            : failed
              ? "#FCA5A5"
              : elapsed
                ? "#C4B5D6"
                : BORDER;

        const backgroundColor = active
          ? "#F0F5FF"
          : complete
            ? "#F0FDF4"
            : failed
              ? "#FEF2F2"
              : elapsed
                ? "#F7F4FB"
                : "#FAFAF9";

        return (
          <div
            key={stage.name}
            className={`pipeline-stage relative ${
              active ? "pipeline-stage--active" : ""
            } ${elapsed ? "pipeline-stage--elapsed" : ""}`}
          >
            {index < stageCount - 1 && (
              <span
                className={`pipeline-flow-connector hidden lg:block ${
                  loading && index < activeStage
                    ? "pipeline-flow-connector--on"
                    : ""
                }`}
                aria-hidden="true"
              />
            )}

            <div
              className="pipeline-stage-card h-full rounded-xl border p-3"
              style={{
                borderColor,
                backgroundColor,
                boxShadow: active ? `0 0 0 2px ${BLUE}22` : "none",
              }}
            >
              <div className="flex items-center justify-between gap-2">
                <span
                  className="flex h-8 w-8 items-center justify-center rounded-full text-sm font-bold"
                  style={{
                    color: failed
                      ? "#991B1B"
                      : complete
                        ? "#166534"
                        : PURPLE,
                    backgroundColor: failed
                      ? "#FEE2E2"
                      : complete
                        ? "#DCFCE7"
                        : active
                          ? "#DCE8F8"
                          : "#E5DBE6",
                  }}
                >
                  {complete
                    ? "✓"
                    : failed
                      ? "!"
                      : active
                        ? "…"
                        : skipped
                          ? "—"
                          : index + 1}
                </span>

                {active && !reducedMotion && (
                  <span
                    className="pipeline-spinner h-4 w-4 rounded-full border-2"
                    style={{
                      borderColor: BLUE,
                      borderTopColor: "transparent",
                    }}
                    aria-label="Illustrative stage focus"
                  />
                )}
              </div>

              <h3
                className="mt-3 text-sm font-semibold"
                style={{ color: PURPLE }}
              >
                {stage.name}
              </h3>

              <p
                className="mt-1 min-h-10 text-xs leading-5"
                style={{ color: MUTED_TEXT }}
              >
                {stage.detail}
              </p>

              <p
                className="mt-2 text-xs font-semibold"
                style={{
                  color: failed
                    ? "#991B1B"
                    : complete
                      ? "#166534"
                      : active
                        ? PURPLE
                        : MUTED_TEXT,
                }}
              >
                {getStageMessage(index, state)}
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Animated workflow. While loading, stage highlighting is time-based and
// illustrative only. After the response arrives, states come from the payload.
function CorrectionPipeline({ loading, result, error, mode }) {
  const reducedMotion = useReducedMotion();

  if (!loading && !result && !error) return null;

  const attempts = result?.attempts || [];
  const finalAttempt =
    attempts.find(
      (attempt) =>
        result?.final_attempt_number != null &&
        Number(attempt.attempt_number) ===
          Number(result.final_attempt_number),
    ) || attempts[attempts.length - 1];

  const evaluation = finalAttempt?.evaluation;
  const evaluated = Boolean(evaluation);
  const correctionAttempted = attempts.length > 1;

  function getResultStageState(index) {
    if (error) return index === 0 ? "failed" : "pending";
    if (!result) return "pending";

    if (index === 0) return "complete";

    if (index === 1) {
      return result.final_answer || result.answer || finalAttempt?.answer
        ? "complete"
        : "pending";
    }

    if (index === 2) {
      if (!evaluated) return "unknown";
      return evaluation?.passed === false ? "failed" : "complete";
    }

    if (index === 3) {
      if (mode === "basic" || result.mode === "basic") return "skipped";
      return correctionAttempted ? "complete" : "skipped";
    }

    if (index === 4) {
      if (mode === "basic" || result.mode === "basic") return "skipped";
      if (!correctionAttempted) return "skipped";
      if (!evaluated) return "unknown";
      return evaluation?.passed === false ? "failed" : "complete";
    }

    return "pending";
  }

  function getResultStageMessage(index, state) {
    if (state === "failed") return "Check result";
    if (state === "skipped") return "Not required / not reported";
    if (state === "unknown") return "Evaluation data unavailable";
    if (state === "complete") {
      if (index === 2) {
        return evaluation?.passed === true
          ? "Evaluation passed"
          : "Evaluation completed";
      }
      if (index === 3) return "Retry found in result";
      if (index === 4) return "Final evaluation received";
      return "Completed";
    }
    return "Waiting";
  }

  return (
    <section
      className="pipeline-panel rounded-xl border bg-white p-5"
      style={panelStyle}
      aria-live="polite"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold" style={{ color: PURPLE }}>
            Correction Pipeline
          </h2>
          <p className="mt-1 text-sm" style={{ color: MUTED_TEXT }}>
            Follow the answer generation and evaluation workflow.
          </p>
        </div>

        <span
          className="rounded-full px-3 py-1 text-xs font-semibold"
          style={{
            color: loading ? PURPLE : error ? "#991B1B" : "#166534",
            backgroundColor: loading
              ? "#EAF0FA"
              : error
                ? "#FEE2E2"
                : "#DCFCE7",
          }}
        >
          {loading
            ? "Waiting for backend…"
            : error
              ? "Request error"
              : "Result received"}
        </span>
      </div>

      {loading ? (
        <IllustrativePipelineProgress reducedMotion={reducedMotion} />
      ) : (
        <>
          <PipelineStageGrid
            loading={false}
            reducedMotion={reducedMotion}
            activeStage={PIPELINE_STAGES.length}
            getStageState={getResultStageState}
            getStageMessage={getResultStageMessage}
          />

          {error && (
            <p className="mt-4 text-sm" style={{ color: "#991B1B" }}>
              The request did not complete successfully. Check the error message
              below.
            </p>
          )}
        </>
      )}
    </section>
  );
}

// Must match the failure types in backend/app/services/evaluator.py.
const FAILURE_LABELS = {
  unsupported_claim: "Unsupported claim",
  missing_info: "Missing information",
  irrelevant_retrieval: "Irrelevant retrieval",
  evaluator_error: "Evaluator error",
};

function getVerdict(evaluation) {
  if (!evaluation) {
    return {
      label: "NOT EVALUATED",
      color: MUTED_TEXT,
      background: "#F5F5F4",
    };
  }

  if (evaluation.failure_type === "evaluator_error") {
    return {
      label: "EVALUATOR ERROR",
      color: "#92400E",
      background: "#FEF3C7",
    };
  }

  if (evaluation.passed === true) {
    return { label: "PASSED", color: "#166534", background: "#DCFCE7" };
  }

  if (evaluation.passed === false) {
    return { label: "FAILED", color: "#991B1B", background: "#FEE2E2" };
  }

  return {
    label: "NOT DETERMINED",
    color: MUTED_TEXT,
    background: "#F5F5F4",
  };
}

function EvaluationSummary({ evaluation, attempt, attemptCount }) {
  const verdict = getVerdict(evaluation);

  const metrics = [
    {
      label: "Faithfulness",
      value: evaluation?.faithfulness ?? evaluation?.faithfulness_score,
    },
    {
      label: "Answer relevance",
      value:
        evaluation?.answer_relevance ?? evaluation?.answer_relevance_score,
    },
    {
      label: "Context relevance",
      value:
        evaluation?.context_relevance ?? evaluation?.context_relevance_score,
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
            ? `Reported attempt ${attempt.attempt_number} of ${attemptCount}`
            : "Reported attempt not available"}
        </span>
      </div>

      <div
        className="mt-4 flex flex-wrap items-center gap-2 rounded-lg border p-3"
        style={{ borderColor: BORDER }}
      >
        <span className="text-sm font-semibold" style={{ color: DARK_TEXT }}>
          Evaluation verdict:
        </span>
        <span
          className="inline-block rounded-full px-2 py-1 text-xs font-semibold"
          style={{
            color: verdict.color,
            backgroundColor: verdict.background,
          }}
        >
          {verdict.label}
        </span>

        {evaluation?.failure_type && (
          <span className="text-sm" style={{ color: MUTED_TEXT }}>
            Failure type:{" "}
            {FAILURE_LABELS[evaluation.failure_type] ??
              evaluation.failure_type.replaceAll("_", " ")}
          </span>
        )}
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
            <p className="mt-2 text-2xl font-bold" style={{ color: PURPLE }}>
              {formatScore(metric.value)}
            </p>
          </div>
        ))}
      </div>

      <p className="mt-3 text-xs" style={{ color: MUTED_TEXT }}>
        Scores and verdicts are the backend evaluator&apos;s saved results.
        They are not recomputed in the browser.
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
        <span style={{ color: PURPLE }}>{expanded ? "−" : "+"}</span>
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
                    <span className="text-xs font-semibold" style={{ color: BLUE }}>
                      Similarity: {formatScore(item.similarity)}
                    </span>
                  )}
                </div>

                <p className="mt-1 text-xs" style={{ color: MUTED_TEXT }}>
                  {item.page_number != null
                    ? `Page ${item.page_number}`
                    : "Page not provided"}
                  {item.chunk_id != null ? ` · Chunk ${item.chunk_id}` : ""}
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
                      : citation
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
        <span style={{ color: PURPLE }}>{expanded ? "−" : "+"}</span>
      </button>

      {expanded && (
        <div className="mt-4 space-y-4">
          {[
            ["Retrieved chunks", retrieval || []],
            ["Timings", timings || {}],
            ["Query attempts", attempts || []],
          ].map(([title, value]) => (
            <div key={title}>
              <h3 className="text-sm font-semibold">{title}</h3>
              <pre
                className="mt-2 overflow-x-auto rounded-lg p-3 text-xs"
                style={{ backgroundColor: "#F5F5F4" }}
              >
                {JSON.stringify(value, null, 2)}
              </pre>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default function Ask() {
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState(DEFAULT_MODE);
  const [documents, setDocuments] = useState([]);
  const [selectedDocuments, setSelectedDocuments] = useState([]);
  const [result, setResult] = useState(null);
  const [queryId, setQueryId] = useState(
    sessionStorage.getItem(LAST_QUERY_KEY)
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
        if (active) setError(err.message || "Failed to load documents.");
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
        : [...previous, id]
    );
  }

  function toggleAllDocuments() {
    const allSelected =
      documents.length > 0 &&
      documents.every((doc) => selectedDocuments.includes(String(doc.id)));

    setSelectedDocuments(
      allSelected ? [] : documents.map((doc) => String(doc.id))
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
      let topK = 5;

      try {
        const savedSettings = JSON.parse(
          localStorage.getItem(SETTINGS_KEY) || "{}"
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
        // Keep the default Top-k value.
      }

      const data = await runQuery({
        question: submittedQuestion,
        documentIds: selectedDocuments,
        mode,
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

  const reportedAttempt =
    attempts.find(
      (attempt) =>
        result?.final_attempt_number != null &&
        Number(attempt.attempt_number) ===
          Number(result.final_attempt_number)
    ) || attempts[attempts.length - 1] || {};

  const answer =
    result?.final_answer ??
    result?.answer ??
    reportedAttempt?.answer ??
    "";

  const status = getStatus(result || {});

  const resultModeLabel =
    QUERY_MODES.find((option) => option.value === result?.mode)?.label ?? null;

  const retrieval = reportedAttempt?.retrieval ?? result?.retrieval ?? [];
  const citations = reportedAttempt?.citations ?? result?.citations ?? [];
  const evaluation = reportedAttempt?.evaluation ?? null;

  const timings =
    reportedAttempt?.timings ??
    result?.timings ??
    reportedAttempt?.attempt_timings ??
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
          <EvaluationSettingsPanel />

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

            <ModeSelector
              mode={mode}
              onChange={setMode}
              disabled={loading}
            />

            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button
                type="submit"
                disabled={loading || loadingDocuments}
                className="rounded-lg px-5 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
                style={{ backgroundColor: PURPLE }}
              >
                {loading ? "Processing pipeline…" : "Ask RELI-RAG"}
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

          {/* Correction pipeline appears directly below the question form. */}
          <CorrectionPipeline
            loading={loading}
            result={result}
            error={error}
            mode={mode}
          />

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

                  <div className="flex flex-wrap items-center gap-2">
                    {resultModeLabel && (
                      <span
                        className="inline-block rounded-full px-2 py-1 text-xs font-semibold"
                        style={{ color: PURPLE, backgroundColor: BORDER }}
                      >
                        {resultModeLabel} mode
                      </span>
                    )}
                    <span className="text-xs" style={{ color: MUTED_TEXT }}>
                      Answer status
                    </span>
                    <StatusBadge status={status} />
                  </div>
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
                      The retrieved documents do not provide enough reliable
                      evidence to answer this question confidently. Try
                      selecting other documents or asking a more specific
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
                attempt={reportedAttempt}
                attemptCount={attempts.length}
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

        <HistorySidebar history={queryHistory} onClear={clearHistory} />
      </div>
    </div>
  );
}

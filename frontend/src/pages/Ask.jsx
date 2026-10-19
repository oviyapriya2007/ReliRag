
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  USE_MOCK,
  getDocuments,
  getQuery,
  runQuery,
} from "../../api/client";
import {
  buildCorrectionDemoPayload,
  isCorrectionDemoQuestion,
} from "../demo/correctionDemo";

const PURPLE = "#55416F";
const BLUE = "#738FBD";
const SOFT_BLUE = "#EEF3FA";
const LAVENDER = "#F3EDF5";
const PALE_PINK = "#FBEFF4";
const SOFT_MINT = "#EAF6EF";
const BORDER = "#E5DBE6";
const DARK_TEXT = "#29243A";
const MUTED_TEXT = "#817789";
const ROSE = "#DB88A4";

const HISTORY_KEY = "relirag_query_history";
const LAST_QUERY_KEY = "relirag_last_query_id";
const SETTINGS_KEY = "relirag_evaluation_settings";
const MAX_HISTORY = 10;

const panelStyle = {
  borderColor: BORDER,
  borderRadius: "14px",
};

const QUERY_MODES = [
  { value: "basic", label: "Basic", description: "Single attempt" },
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
  { name: "Retrieve", detail: "Finding relevant document passages" },
  { name: "Generate", detail: "Generating an evidence-based answer" },
  { name: "Evaluate", detail: "Checking answer quality and faithfulness" },
  { name: "Correct", detail: "Attempting to improve a failed answer" },
  { name: "Re-evaluate", detail: "Checking the updated answer" },
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
    setSettings((previous) => ({ ...previous, [name]: value }));
  }

  return (
    <section
      className="overflow-hidden rounded-xl border bg-white shadow-sm"
      style={panelStyle}
    >
      <button
        type="button"
        onClick={() => setExpanded((previous) => !previous)}
        aria-expanded={expanded}
        className="flex w-full items-center justify-between gap-4 p-5 text-left transition hover:bg-[#F8F5FA]"
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
            backgroundColor: LAVENDER,
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
          className="border-t bg-[#FCFAFD] p-5"
          style={{ borderColor: BORDER }}
        >
          <p
            className="text-sm leading-6"
            style={{ color: MUTED_TEXT }}
          >
            These preferences are saved in this browser. Top-k is sent with
            new queries. The similarity gate is a frontend preference and
            does not change backend processing. Pass/fail verdicts come from
            the backend.
          </p>

          <div className="mt-5 grid gap-5 sm:grid-cols-2">
            <div
              className="rounded-xl border bg-white p-4"
              style={{ borderColor: BORDER }}
            >
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
                className="mt-3 w-full accent-[#738FBD]"
              />

              <p
                className="mt-2 text-xs"
                style={{ color: MUTED_TEXT }}
              >
                Number of passages requested during retrieval.
              </p>
            </div>

            <div
              className="rounded-xl border bg-white p-4"
              style={{ borderColor: BORDER }}
            >
              <div className="flex items-center justify-between gap-3">
                <label
                  htmlFor="ask-similarity-gate"
                  className="text-sm font-medium"
                >
                  Similarity gate
                </label>
                <span
                  className="text-sm font-semibold"
                  style={{ color: ROSE }}
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
                  updateSetting(
                    "similarityGate",
                    Number(event.target.value)
                  )
                }
                className="mt-3 w-full accent-[#DB88A4]"
              />

              <p
                className="mt-2 text-xs"
                style={{ color: MUTED_TEXT }}
              >
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
              className="rounded-lg border bg-white px-4 py-2 text-sm font-medium transition hover:bg-[#F3EDF5]"
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
    const parsed = saved ? JSON.parse(saved) : [];
    return Array.isArray(parsed) ? parsed.slice(0, MAX_HISTORY) : [];
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
  const attempts = data?.attempts;
  const attempt = Array.isArray(attempts)
    ? attempts[attempts.length - 1]
    : null;

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
    ? "#FFF2D6"
    : failed
      ? "#FCE8EC"
      : normalized === "UNKNOWN"
        ? "#F3EDF5"
        : "#E4F4EA";

  return (
    <span
      className="inline-block rounded-full px-2.5 py-1 text-xs font-semibold"
      style={{ color, backgroundColor: background }}
    >
      {normalized.replaceAll("_", " ")}
    </span>
  );
}

function HistorySidebar({ history, onClear }) {
  return (
    <aside
      className="h-fit border bg-[#FCFAFD] p-4 shadow-sm xl:sticky xl:top-6"
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
            className="text-xs font-medium text-rose-600 hover:underline"
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
          className="mt-5 rounded-xl border border-dashed bg-white p-4 text-center text-sm"
          style={{ borderColor: BORDER, color: MUTED_TEXT }}
        >
          <p className="text-2xl" style={{ color: BLUE }}>
            ◷
          </p>
          <p className="mt-2 font-medium">No recent queries</p>
          <p className="mt-1 text-xs">
            Ask a question to build your history.
          </p>
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          {history.map((item, index) => (
            <Link
              key={String(item.id)}
              to={`/query/${encodeURIComponent(item.id)}`}
              className="block rounded-xl border bg-white p-3 transition hover:bg-[#EEF3FA]"
              style={{
                borderColor: BORDER,
                borderLeftWidth: "3px",
                borderLeftColor: index % 2 === 0 ? BLUE : ROSE,
              }}
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

              <p className="mt-1 text-xs font-medium" style={{ color: BLUE }}>
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
      <legend
        className="text-sm font-semibold"
        style={{ color: PURPLE }}
      >
        Mode
      </legend>

      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        {QUERY_MODES.map((option) => {
          const checked = mode === option.value;
          const accent = option.value === "reli" ? ROSE : BLUE;

          return (
            <label
              key={option.value}
              className="flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition"
              style={{
                borderColor: checked ? accent : BORDER,
                backgroundColor: checked
                  ? option.value === "reli"
                    ? PALE_PINK
                    : SOFT_BLUE
                  : "white",
                boxShadow: checked ? `0 0 0 1px ${accent}22` : "none",
                opacity: disabled ? 0.6 : 1,
              }}
            >
              <input
                type="radio"
                name="query-mode"
                value={option.value}
                checked={checked}
                onChange={() => onChange(option.value)}
                className="mt-1 accent-[#738FBD]"
              />

              <span className="min-w-0">
                <span
                  className="block text-sm font-semibold"
                  style={{ color: PURPLE }}
                >
                  {option.label}

                  {option.value === "reli" && (
                    <span
                      className="ml-2 rounded-full px-2 py-0.5 text-[10px]"
                      style={{
                        backgroundColor: "#F3DCE6",
                        color: "#884C67",
                      }}
                    >
                      EVALUATED
                    </span>
                  )}
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
    documents.every((doc) =>
      selectedDocuments.includes(String(doc.id))
    );

  return (
    <section
      className="rounded-xl border bg-white p-5 shadow-sm"
      style={panelStyle}
    >
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
          className="rounded-lg px-3 py-2 text-sm font-semibold transition hover:bg-[#EEF3FA] disabled:opacity-50"
          style={{ color: BLUE }}
        >
          {allSelected ? "Deselect all" : "Select all"}
        </button>
      </div>

      {loading ? (
        <p
          className="mt-4 rounded-lg p-3 text-sm"
          style={{ backgroundColor: SOFT_BLUE, color: MUTED_TEXT }}
          role="status"
        >
          Loading documents…
        </p>
      ) : documents.length === 0 ? (
        <p
          className="mt-4 rounded-lg p-3 text-sm"
          style={{ backgroundColor: PALE_PINK, color: MUTED_TEXT }}
        >
          No documents available. Upload documents before querying.
        </p>
      ) : (
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {documents.map((doc, index) => {
            const id = String(doc.id);
            const checked = selectedDocuments.includes(id);
            const accent = index % 2 === 0 ? BLUE : ROSE;

            return (
              <label
                key={id}
                className="flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition hover:shadow-sm"
                style={{
                  borderColor: checked ? accent : BORDER,
                  borderLeftWidth: checked ? "3px" : "1px",
                  backgroundColor: checked
                    ? index % 2 === 0
                      ? SOFT_BLUE
                      : PALE_PINK
                    : "#FCFAFD",
                }}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => onToggle(id)}
                  className="mt-1 accent-[#738FBD]"
                />

                <span className="min-w-0">
                  <span
                    className="block break-words text-sm font-medium"
                    style={{ color: DARK_TEXT }}
                  >
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

/* =========================================
   Correction Pipeline
   ========================================= */

const PIPELINE_STAGE_MS = 2200;

function prefersReducedMotion() {
  if (typeof window === "undefined" || !window.matchMedia) {
    return false;
  }

  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function useReducedMotion() {
  const [reducedMotion, setReducedMotion] = useState(prefersReducedMotion);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) {
      return undefined;
    }

    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReducedMotion(media.matches);

    media.addEventListener?.("change", sync);

    return () => media.removeEventListener?.("change", sync);
  }, []);

  return reducedMotion;
}

function IllustrativePipelineProgress({ reducedMotion }) {
  const stageCount = PIPELINE_STAGES.length;
  const [activeStage, setActiveStage] = useState(0);

  useEffect(() => {
    if (reducedMotion) {
      setActiveStage(stageCount - 1);
      return undefined;
    }

    setActiveStage(0);

    const interval = window.setInterval(() => {
      setActiveStage((current) =>
        current >= stageCount - 1 ? 0 : current + 1
      );
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
              : `Stage ${focusStage + 1} of ${stageCount} (illustrative)`}
          </span>

          <span className="font-semibold" style={{ color: PURPLE }}>
            {Math.round(illustrativeProgress)}%
          </span>
        </div>

        <div
          className="pipeline-progress-track mt-2 overflow-hidden rounded-full"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(illustrativeProgress)}
          aria-label="Illustrative pipeline progress"
        >
          <div
            className="pipeline-progress-fill rounded-full"
            style={{
              width: `${illustrativeProgress}%`,
              backgroundColor: BLUE,
            }}
          />
        </div>
      </div>

      <PipelineStageGrid
        loading
        reducedMotion={reducedMotion}
        activeStage={focusStage}
        getStageState={(index) =>
          index < focusStage
            ? "elapsed"
            : index === focusStage
              ? "active"
              : "pending"
        }
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

      <p
        className="mt-4 text-xs leading-5"
        style={{ color: MUTED_TEXT }}
      >
        This animation is a visual aid while waiting for the backend. It
        does not report live stage completion. Actual evaluation and
        correction results appear when the response arrives.
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
            ? "#A5D8B5"
            : failed
              ? "#E8A6B3"
              : elapsed
                ? "#C8B6D9"
                : BORDER;

        const backgroundColor = active
          ? SOFT_BLUE
          : complete
            ? SOFT_MINT
            : failed
              ? "#FCECF0"
              : elapsed
                ? LAVENDER
                : "#FCFAFD";

        return (
          <div
            key={stage.name}
            className={`pipeline-stage ${
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
                      ? "#F7DCE3"
                      : complete
                        ? "#D6EEDC"
                        : active
                          ? "#D5E3F4"
                          : elapsed
                            ? "#E6D9F0"
                            : "#F0E8F2",
                  }}
                  aria-hidden="true"
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

                {active && loading && !reducedMotion && (
                  <span
                    className="pipeline-spinner inline-block h-4 w-4 rounded-full border-2"
                    style={{
                      borderColor: BLUE,
                      borderTopColor: "transparent",
                    }}
                    role="img"
                    aria-label="Illustrative stage animation"
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

function CorrectionPipeline({ loading, result, error, mode }) {
  const reducedMotion = useReducedMotion();

  if (!loading && !result && !error) return null;

  const attempts = Array.isArray(result?.attempts) ? result.attempts : [];

  const finalAttempt =
    attempts.find(
      (attempt) =>
        result?.final_attempt_number != null &&
        Number(attempt.attempt_number) ===
          Number(result.final_attempt_number)
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
      if (
        mode === "basic" ||
        result.mode === "basic" ||
        !correctionAttempted
      ) {
        return "skipped";
      }

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

    return "Not confirmed";
  }

  return (
    <section
      className="pipeline-panel rounded-xl border bg-white p-5 shadow-sm"
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
              ? SOFT_BLUE
              : error
                ? "#FCE8EC"
                : SOFT_MINT,
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
        <PipelineStageGrid
          loading={false}
          reducedMotion={reducedMotion}
          activeStage={PIPELINE_STAGES.length}
          getStageState={getResultStageState}
          getStageMessage={getResultStageMessage}
        />
      )}

      {error && (
        <p className="mt-4 text-sm" style={{ color: "#991B1B" }}>
          The request did not complete successfully. Check the error
          message below.
        </p>
      )}
    </section>
  );
}

/* =========================================
   Evaluation Results
   ========================================= */

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
      background: LAVENDER,
    };
  }

  if (evaluation.failure_type === "evaluator_error") {
    return {
      label: "EVALUATOR ERROR",
      color: "#92400E",
      background: "#FFF2D6",
    };
  }

  if (evaluation.passed === true) {
    return {
      label: "PASSED",
      color: "#166534",
      background: "#E4F4EA",
    };
  }

  if (evaluation.passed === false) {
    return {
      label: "FAILED",
      color: "#991B1B",
      background: "#FCE8EC",
    };
  }

  return {
    label: "NOT DETERMINED",
    color: MUTED_TEXT,
    background: LAVENDER,
  };
}

function EvaluationSummary({ evaluation, attempt, attemptCount }) {
  const verdict = getVerdict(evaluation);

  const metrics = [
    {
      label: "Faithfulness",
      value:
        evaluation?.faithfulness ?? evaluation?.faithfulness_score,
      background: SOFT_BLUE,
      accent: BLUE,
    },
    {
      label: "Answer relevance",
      value:
        evaluation?.answer_relevance ??
        evaluation?.answer_relevance_score,
      background: PALE_PINK,
      accent: ROSE,
    },
    {
      label: "Context relevance",
      value:
        evaluation?.context_relevance ??
        evaluation?.context_relevance_score,
      background: LAVENDER,
      accent: PURPLE,
    },
  ];

  return (
    <section
      className="rounded-xl border bg-white p-5 shadow-sm"
      style={panelStyle}
    >
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
        style={{ borderColor: BORDER, backgroundColor: "#FCFAFD" }}
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
            className="rounded-xl border p-4"
            style={{
              backgroundColor: metric.background,
              borderColor: `${metric.accent}55`,
              borderTopWidth: "3px",
              borderTopColor: metric.accent,
            }}
          >
            <p className="text-xs font-medium" style={{ color: MUTED_TEXT }}>
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
        {evaluation?.feedback?.startsWith("[DEMO")
          ? "Scripted / demo scores — not a real Claude evaluation."
          : "Scores and verdicts are the backend evaluator's saved results. They are not recomputed in the browser."}
      </p>
    </section>
  );
}

function ScriptedCorrectionTrail({ result }) {
  const attempt1 = result?.attempts?.[0];
  const attempt2 = result?.attempts?.[1];

  if (!attempt1 || !attempt2) return null;

  return (
    <section
      className="rounded-xl border bg-white p-5"
      style={panelStyle}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold" style={{ color: PURPLE }}>
          Correction trail
        </h2>

        <span
          className="rounded-full px-3 py-1 text-xs font-bold"
          style={{
            color: "#92400E",
            backgroundColor: "#FEF3C7",
          }}
        >
          DEMO / SIMULATED
        </span>
      </div>

      <p className="mt-2 text-sm" style={{ color: MUTED_TEXT }}>
        Scripted walkthrough for this question only. Not saved to the
        database and not produced by Claude.
      </p>

      <ol className="mt-4 space-y-3">
        <li
          className="rounded-lg border p-4"
          style={{ borderColor: "#FCA5A5" }}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-800">
              Attempt 1
            </p>

            <span
              className="rounded-full px-2 py-1 text-xs font-semibold"
              style={{
                color: "#991B1B",
                backgroundColor: "#FEE2E2",
              }}
            >
              FAILED · missing_info
            </span>
          </div>

          <pre className="mt-3 whitespace-pre-wrap text-sm leading-6 text-gray-700">
            {attempt1.answer}
          </pre>
        </li>

        <li
          className="rounded-lg border p-4"
          style={{ borderColor: BLUE }}
        >
          <p className="text-sm font-semibold text-gray-800">
            Correction query (rewrite)
          </p>

          <pre
            className="mt-3 whitespace-pre-wrap rounded-lg p-3 text-sm leading-6 text-gray-700"
            style={{ backgroundColor: "#F0F5FF" }}
          >
            {result.correction_query || "No correction query provided."}
          </pre>
        </li>

        <li
          className="rounded-lg border p-4"
          style={{ borderColor: "#86EFAC" }}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-800">
              Attempt 2
            </p>

            <span
              className="rounded-full px-2 py-1 text-xs font-semibold"
              style={{
                color: "#166534",
                backgroundColor: "#DCFCE7",
              }}
            >
              PASSED
            </span>
          </div>

          <pre className="mt-3 whitespace-pre-wrap text-sm leading-6 text-gray-700">
            {attempt2.answer}
          </pre>
        </li>
      </ol>

      <p className="mt-3 text-xs" style={{ color: MUTED_TEXT }}>
        Full labelled view also available on{" "}
        <Link
          to="/correction-demo"
          className="font-semibold underline"
        >
          Correction Demo
        </Link>.
      </p>
    </section>
  );
}

/* =========================================
   Evidence Explorer
   ========================================= */

function EvidenceExplorer({ citations, retrieval }) {
  const items = Array.isArray(retrieval) ? retrieval : [];
  const citationList = Array.isArray(citations) ? citations : [];

  return (
    <section
      className="rounded-xl border bg-white p-5 shadow-sm"
      style={panelStyle}
    >
      <h2 className="font-semibold" style={{ color: PURPLE }}>
        Retrieved Evidence
      </h2>
      <p className="mt-1 text-sm" style={{ color: MUTED_TEXT }}>
        Retrieved passages and supporting citations
      </p>

      <div className="mt-4 space-y-3">
        {items.length === 0 && citationList.length === 0 ? (
          <p
            className="rounded-lg p-3 text-sm"
            style={{ color: MUTED_TEXT, backgroundColor: "#FCFAFD" }}
          >
            No retrieved evidence or citations were returned.
          </p>
        ) : (
          <>
            {items.map((item, index) => (
              <article
                key={`${item.chunk_id ?? item.id ?? index}-${index}`}
                className="rounded-xl border p-4"
                style={{
                  borderColor: BORDER,
                  backgroundColor:
                    index % 2 === 0 ? "#FCFAFD" : "#F8F6FA",
                  borderLeft: `3px solid ${
                    index % 2 === 0 ? BLUE : ROSE
                  }`,
                }}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p
                    className="text-sm font-semibold"
                    style={{ color: DARK_TEXT }}
                  >
                    [{item.rank ?? index + 1}]{" "}
                    {item.filename ||
                      item.document_name ||
                      "Source document"}
                  </p>

                  {item.similarity != null && (
                    <span
                      className="rounded-full px-2 py-1 text-xs font-semibold"
                      style={{
                        color: PURPLE,
                        backgroundColor: SOFT_BLUE,
                      }}
                    >
                      Similarity: {formatScore(item.similarity)}
                    </span>
                  )}
                </div>

                <p
                  className="mt-1 text-xs"
                  style={{ color: MUTED_TEXT }}
                >
                  {item.page_number != null
                    ? `Page ${item.page_number}`
                    : "Page not provided"}
                  {item.chunk_id != null
                    ? ` · Chunk ${item.chunk_id}`
                    : ""}
                </p>

                <p
                  className="mt-3 whitespace-pre-wrap text-sm leading-6"
                  style={{ color: DARK_TEXT }}
                >
                  {item.content || item.text || "No passage text available."}
                </p>
              </article>
            ))}

            {citationList.length > 0 && (
              <div
                className="rounded-xl border p-3"
                style={{
                  backgroundColor: PALE_PINK,
                  borderColor: "#F0D7E1",
                }}
              >
                <p
                  className="text-sm font-semibold"
                  style={{ color: PURPLE }}
                >
                  Answer citations
                </p>

                <p className="mt-1 text-sm" style={{ color: MUTED_TEXT }}>
                  {citationList
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
          </>
        )}
      </div>
    </section>
  );
}

/* =========================================
   Retrieval Debug Panel
   ========================================= */

function RetrievalDebugPanel({ retrieval, timings, attempts }) {
  return (
    <section
      className="rounded-xl border bg-white p-5 shadow-sm"
      style={panelStyle}
    >
      <h2 className="font-semibold" style={{ color: PURPLE }}>
        Debug Information
      </h2>
      <p className="mt-1 text-sm" style={{ color: MUTED_TEXT }}>
        Inspect retrieved data, timings, and attempts.
      </p>

      <div className="mt-4 space-y-4">
        {[
          ["Retrieved chunks", retrieval || []],
          ["Timings", timings || {}],
          ["Query attempts", attempts || []],
        ].map(([title, value], index) => (
          <div key={title}>
            <h3 className="text-sm font-semibold" style={{ color: PURPLE }}>
              {title}
            </h3>

            <pre
              className="mt-2 overflow-x-auto rounded-lg border p-3 text-xs"
              style={{
                backgroundColor: index % 2 === 0 ? SOFT_BLUE : LAVENDER,
                borderColor: BORDER,
                color: DARK_TEXT,
              }}
            >
              {JSON.stringify(value, null, 2)}
            </pre>
          </div>
        ))}
      </div>
    </section>
  );
}

/* =========================================
   Ask Page
   ========================================= */

export default function Ask() {
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState(DEFAULT_MODE);
  const [documents, setDocuments] = useState([]);
  const [selectedDocuments, setSelectedDocuments] = useState([]);
  const [result, setResult] = useState(null);

  const [queryId, setQueryId] = useState(() => {
    try {
      return sessionStorage.getItem(LAST_QUERY_KEY);
    } catch {
      return null;
    }
  });

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

        if (data.question) {
          setQuestion(data.question);
        }
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
      documents.every((doc) =>
        selectedDocuments.includes(String(doc.id))
      );

    setSelectedDocuments(
      allSelected ? [] : documents.map((doc) => String(doc.id))
    );
  }

  async function handleSubmit(event) {
    event.preventDefault();

    if (loading) return;

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
    setQueryId(null);
    setShowEvidence(true);
    setShowDebug(false);

    try {
      // Exact-match demo override only. Other questions use live Attest.
      if (isCorrectionDemoQuestion(submittedQuestion)) {
        await new Promise((resolve) => window.setTimeout(resolve, 9000));

        const data = buildCorrectionDemoPayload();

        setResult(data);
        setQueryId(null);

        recordHistory(
          `demo-${Date.now()}`,
          submittedQuestion,
          data
        );

        return;
      }

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

        try {
          sessionStorage.setItem(LAST_QUERY_KEY, String(id));
        } catch {
          // Restoring the last query is optional.
        }

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

  const attempts = Array.isArray(result?.attempts)
    ? result.attempts
    : [];

  const reportedAttempt =
    attempts.find(
      (attempt) =>
        result?.final_attempt_number != null &&
        Number(attempt.attempt_number) ===
          Number(result.final_attempt_number)
    ) ||
    attempts[attempts.length - 1] ||
    {};

  const answer =
    result?.final_answer ??
    result?.answer ??
    reportedAttempt?.answer ??
    "";

  const status = getStatus(result || {});

  const resultModeLabel =
    QUERY_MODES.find((option) => option.value === result?.mode)?.label ??
    null;

  const retrieval =
    reportedAttempt?.retrieval ?? result?.retrieval ?? [];

  const citations =
    reportedAttempt?.citations ?? result?.citations ?? [];

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
      <div
        className="relative mb-6 overflow-hidden rounded-2xl border p-5 sm:p-7"
        style={{
          backgroundColor: LAVENDER,
          borderColor: BORDER,
        }}
      >
        <div
          className="absolute right-0 top-0 h-2 w-32 rounded-bl-full"
          style={{ backgroundColor: ROSE }}
          aria-hidden="true"
        />

        <p
          className="text-xs font-bold uppercase tracking-[0.16em]"
          style={{ color: BLUE }}
        >
          Attest · Retrieval Augmented Generation
        </p>

        <h1
          className="mt-2 text-2xl font-bold sm:text-3xl"
          style={{ color: PURPLE }}
        >
          Ask a Question
        </h1>

        <p
          className="mt-2 max-w-2xl text-sm leading-6"
          style={{ color: MUTED_TEXT }}
        >
          Ask questions grounded in your documents and inspect the evidence
          behind each answer.
        </p>

        <div className="mt-4 flex flex-wrap gap-2">
          <span
            className="rounded-full border bg-white px-3 py-1 text-xs font-medium"
            style={{ borderColor: BORDER, color: PURPLE }}
          >
            Document-grounded answers
          </span>

          <span
            className="rounded-full px-3 py-1 text-xs font-medium"
            style={{
              backgroundColor: "#F7DCE6",
              color: "#884C67",
            }}
          >
            Evaluation insights
          </span>

          <span
            className="rounded-full px-3 py-1 text-xs font-medium"
            style={{
              backgroundColor: "#DCE8F6",
              color: "#3F5F91",
            }}
          >
            Evidence explorer
          </span>
        </div>
      </div>

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_300px]">
        <main className="min-w-0 space-y-5">
          <EvaluationSettingsPanel />

          <form
            onSubmit={handleSubmit}
            className="rounded-xl border bg-white p-5 shadow-sm sm:p-6"
            style={panelStyle}
          >
            <div className="mb-4 flex items-start gap-3">
              <div
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-lg"
                style={{
                  backgroundColor: SOFT_BLUE,
                  color: PURPLE,
                }}
                aria-hidden="true"
              >
                ✦
              </div>

              <div>
                <label
                  htmlFor="question"
                  className="block font-semibold"
                  style={{ color: PURPLE }}
                >
                  Your question
                </label>

                <p
                  className="mt-1 text-xs"
                  style={{ color: MUTED_TEXT }}
                >
                  Ask something about the selected knowledge sources.
                </p>
              </div>
            </div>

            <textarea
              id="question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask something about your uploaded documents..."
              rows={4}
              className="mt-1 w-full resize-y rounded-xl border p-4 text-sm outline-none transition focus:ring-2"
              style={{
                borderColor: BORDER,
                color: DARK_TEXT,
                backgroundColor: "#FCFAFD",
                "--tw-ring-color": `${BLUE}66`,
              }}
              disabled={loading}
              aria-describedby="question-help"
            />

            <p
              id="question-help"
              className="mt-2 text-xs"
              style={{ color: MUTED_TEXT }}
            >
              Choose the relevant documents below before submitting.
            </p>

            <ModeSelector
              mode={mode}
              onChange={setMode}
              disabled={loading}
            />

            <div
              className="mt-5 flex flex-wrap items-center gap-3 border-t pt-5"
              style={{ borderColor: BORDER }}
            >
              <button
                type="submit"
                disabled={loading || loadingDocuments}
                className="rounded-xl px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-60"
                style={{ backgroundColor: PURPLE }}
              >
                {loading ? "Processing pipeline…" : "Ask Attest →"}
              </button>

              <button
                type="button"
                onClick={() => {
                  setQuestion("");
                  setResult(null);
                  setQueryId(null);
                  setError("");
                }}
                disabled={loading}
                className="rounded-xl border bg-white px-4 py-3 text-sm font-medium transition hover:bg-[#F3EDF5] disabled:opacity-50"
                style={{ borderColor: BORDER, color: DARK_TEXT }}
              >
                Clear question
              </button>

              <span className="text-xs" style={{ color: MUTED_TEXT }}>
                {selectedDocuments.length} document
                {selectedDocuments.length === 1 ? "" : "s"} selected
              </span>
            </div>
          </form>

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
                borderColor: "#E8A6B3",
                backgroundColor: "#FCECF0",
                color: "#991B1B",
              }}
            >
              <p className="font-semibold">Something needs attention</p>
              <p className="mt-1">{error}</p>
            </div>
          )}

          {restoring && (
            <p
              className="rounded-lg p-3 text-sm"
              style={{
                color: MUTED_TEXT,
                backgroundColor: SOFT_BLUE,
              }}
              role="status"
            >
              Restoring your previous query…
            </p>
          )}

          {result && (
            <>
              <section
                className="overflow-hidden rounded-xl border bg-white shadow-sm"
                style={panelStyle}
              >
                <div
                  className="flex flex-wrap items-center justify-between gap-3 border-b p-5"
                  style={{
                    borderColor: BORDER,
                    backgroundColor: "#F8F5FA",
                  }}
                >
                  <div>
                    <h2
                      className="font-semibold"
                      style={{ color: PURPLE }}
                    >
                      Query Result
                    </h2>

                    <p
                      className="mt-1 text-xs"
                      style={{ color: MUTED_TEXT }}
                    >
                      Your response and its evaluation status
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    {result.demo && (
                      <span
                        className="inline-block rounded-full px-2 py-1 text-xs font-bold"
                        style={{
                          color: "#92400E",
                          backgroundColor: "#FEF3C7",
                        }}
                      >
                        DEMO / SIMULATED
                      </span>
                    )}

                    {resultModeLabel && (
                      <span
                        className="inline-block rounded-full px-2.5 py-1 text-xs font-semibold"
                        style={{
                          color: PURPLE,
                          backgroundColor: "#E7DDED",
                        }}
                      >
                        {resultModeLabel} mode
                      </span>
                    )}

                    <StatusBadge status={status} />
                  </div>
                </div>

                <div className="p-5">
                  {result.demo && (
                    <p
                      className="mb-4 rounded-lg border px-3 py-2 text-xs leading-5"
                      style={{
                        borderColor: "#F0D7A0",
                        backgroundColor: "#FFFBEB",
                        color: "#92400E",
                      }}
                    >
                      Scripted correction demo for this exact question only.
                      No database write and no Claude call. Other questions
                      still use the live Attest pipeline.
                    </p>
                  )}

                  {insufficientEvidence ? (
                    <div
                      className="rounded-xl border p-4"
                      style={{
                        borderColor: "#E9C78A",
                        backgroundColor: "#FFF8E9",
                        color: "#92400E",
                      }}
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-lg" aria-hidden="true">
                          ⓘ
                        </span>
                        <p className="font-bold">Insufficient Evidence</p>
                      </div>

                      <p className="mt-2 text-sm leading-6">
                        The retrieved documents do not provide enough
                        reliable evidence to answer this question confidently.
                        Try selecting other documents or asking a more
                        specific question.
                      </p>

                      {answer && (
                        <p className="mt-3 whitespace-pre-wrap text-sm leading-6">
                          {answer}
                        </p>
                      )}
                    </div>
                  ) : (
                    <div
                      className="rounded-xl p-4 text-sm leading-7"
                      style={{
                        backgroundColor: "#FCFAFD",
                        borderLeft: `3px solid ${BLUE}`,
                        color: DARK_TEXT,
                      }}
                    >
                      <div
                        className="mb-2 text-xs font-bold uppercase tracking-wider"
                        style={{ color: BLUE }}
                      >
                        Answer
                      </div>

                      <div className="whitespace-pre-wrap">
                        {answer || "No answer was returned by the backend."}
                      </div>
                    </div>
                  )}

                  {queryId && (
                    <p
                      className="mt-4 text-xs"
                      style={{ color: MUTED_TEXT }}
                    >
                      Query ID: {queryId}
                    </p>
                  )}

                  {queryId && !String(queryId).startsWith("local-") && (
                    <Link
                      to={`/query/${encodeURIComponent(queryId)}`}
                      className="mt-3 inline-block rounded-lg px-3 py-2 text-sm font-semibold transition hover:bg-[#EEF3FA]"
                      style={{ color: BLUE }}
                    >
                      View evaluation details →
                    </Link>
                  )}
                </div>
              </section>

              <EvaluationSummary
                evaluation={evaluation}
                attempt={reportedAttempt}
                attemptCount={attempts.length}
              />

              {result.demo && (
                <ScriptedCorrectionTrail result={result} />
              )}

              <section
                className="rounded-xl border bg-white p-5 shadow-sm"
                style={panelStyle}
              >
                <button
                  type="button"
                  onClick={() =>
                    setShowEvidence((value) => !value)
                  }
                  className="flex w-full items-center justify-between text-left"
                  aria-expanded={showEvidence}
                >
                  <span>
                    <span
                      className="block font-semibold"
                      style={{ color: PURPLE }}
                    >
                      Evidence Explorer
                    </span>
                    <span
                      className="mt-1 block text-sm"
                      style={{ color: MUTED_TEXT }}
                    >
                      Retrieved passages and supporting citations
                    </span>
                  </span>

                  <span
                    className="rounded-full px-3 py-1 text-xs font-semibold"
                    style={{
                      backgroundColor: SOFT_BLUE,
                      color: PURPLE,
                    }}
                    aria-hidden="true"
                  >
                    {showEvidence ? "Hide −" : "Show +"}
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
                className="rounded-xl border bg-white p-5 shadow-sm"
                style={panelStyle}
              >
                <button
                  type="button"
                  onClick={() => setShowDebug((value) => !value)}
                  className="flex w-full items-center justify-between text-left"
                  aria-expanded={showDebug}
                >
                  <span>
                    <span
                      className="block font-semibold"
                      style={{ color: PURPLE }}
                    >
                      Retrieval Debug Panel
                    </span>
                    <span
                      className="mt-1 block text-sm"
                      style={{ color: MUTED_TEXT }}
                    >
                      Inspect retrieved data, timings, and attempts
                    </span>
                  </span>

                  <span
                    className="rounded-full px-3 py-1 text-xs font-semibold"
                    style={{
                      backgroundColor: LAVENDER,
                      color: PURPLE,
                    }}
                    aria-hidden="true"
                  >
                    {showDebug ? "Hide −" : "Show +"}
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

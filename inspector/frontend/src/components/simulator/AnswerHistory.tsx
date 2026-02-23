"use client";

import type { HistoryEntry } from "@/lib/types/simulator";

interface AnswerHistoryProps {
  history: HistoryEntry[];
  onGoBackTo: (index: number) => void;
}

const PHASE_LABELS: Record<number, string> = {
  0: "Demographics",
  1: "ER Critical",
  2: "Symptoms",
  3: "ER Checklist",
  4: "OLDCARTS",
  5: "OPD",
};

/**
 * Right sidebar: scrollable timeline of past answers with "Back to here" buttons.
 */
export default function AnswerHistory({
  history,
  onGoBackTo,
}: AnswerHistoryProps) {
  if (history.length === 0) {
    return (
      <div className="text-sm text-gray-400 text-center py-8">
        No history yet. Answer questions to build the timeline.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {history.map((entry, idx) => {
        const answerPreview = formatAnswerPreview(entry.answerValue);
        return (
          <div
            key={idx}
            className="border border-gray-200 rounded p-2.5 bg-white hover:bg-gray-50 transition-colors"
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium text-blue-500 bg-blue-50 px-1.5 py-0.5 rounded">
                {PHASE_LABELS[entry.phase] ?? `Phase ${entry.phase}`}
              </span>
              <button
                onClick={() => onGoBackTo(idx)}
                className="text-xs text-gray-400 hover:text-blue-500 transition-colors"
                title="Go back to this step"
              >
                ← Back
              </button>
            </div>
            <p className="text-xs text-gray-700 font-medium truncate">
              {entry.label}
            </p>
            {answerPreview && (
              <p className="text-xs text-gray-400 mt-0.5 truncate">
                {answerPreview}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Format an answer value for display in the history timeline */
function formatAnswerPreview(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean")
    return String(value);
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") {
    // For objects like demographics or flag maps, show key count
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length <= 3) {
      return entries
        .map(([k, v]) => `${k}: ${formatAnswerPreview(v)}`)
        .join(", ");
    }
    return `${entries.length} fields`;
  }
  return String(value);
}

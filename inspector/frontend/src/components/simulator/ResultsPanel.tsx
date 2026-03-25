"use client";

import { useState } from "react";
import type { TerminationResult, DiseaseEntry, SkippedTermination } from "@/lib/types/simulator";

interface ResultsPanelProps {
  result: TerminationResult;
  onRestart: () => void;
  /** Disease list for resolving IDs to names */
  diseases?: DiseaseEntry[];
  /** True when LLM prediction is still loading */
  predictionLoading?: boolean;
}

/** Map severity IDs to Tailwind color classes */
const SEVERITY_COLORS: Record<string, string> = {
  sev001: "bg-green-100 text-green-800 border-green-300",
  sev002: "bg-yellow-100 text-yellow-800 border-yellow-300",
  sev002_5: "bg-orange-100 text-orange-800 border-orange-300",
  sev003: "bg-red-100 text-red-800 border-red-300",
};

/**
 * Final result card: shows department badges, severity badge (color-coded),
 * differential diagnosis ranked list, reason, and a restart button.
 */
export default function ResultsPanel({
  result,
  onRestart,
  diseases = [],
  predictionLoading = false,
}: ResultsPanelProps) {
  const sevColor =
    result.severity
      ? SEVERITY_COLORS[result.severity.id] ?? "bg-gray-100 text-gray-800 border-gray-300"
      : "bg-gray-100 text-gray-800 border-gray-300";

  /** Resolve a disease ID to its display name */
  const resolveDiseaseId = (diseaseId: string): string => {
    const entry = diseases.find((d) => d.id === diseaseId);
    if (entry) return `${entry.disease_name} (${entry.name_th})`;
    return diseaseId;
  };

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-800">
        {result.type === "terminated" ? "Simulation Terminated" : "Simulation Complete"}
      </h3>

      <div className="border border-gray-200 rounded-lg p-4 space-y-4 bg-white">
        {/* Severity */}
        {result.severity && (
          <div>
            <span className="text-xs font-medium text-gray-500 block mb-1">
              Severity
            </span>
            <span
              className={`inline-block px-3 py-1 rounded-full text-sm font-semibold border ${sevColor}`}
            >
              {result.severity.name} ({result.severity.id})
            </span>
          </div>
        )}

        {/* Departments */}
        {result.departments.length > 0 && (
          <div>
            <span className="text-xs font-medium text-gray-500 block mb-1">
              Department(s)
            </span>
            <div className="flex flex-wrap gap-2">
              {result.departments.map((dept) => (
                <span
                  key={dept.id}
                  className="inline-block px-3 py-1 rounded-full text-sm font-medium bg-blue-100 text-blue-800 border border-blue-300"
                >
                  {dept.name} ({dept.id})
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Differential Diagnosis */}
        {predictionLoading && (
          <div>
            <span className="text-xs font-medium text-gray-500 block mb-1">
              Differential Diagnosis
            </span>
            <div className="flex items-center gap-2 py-2">
              <div className="w-4 h-4 border-2 border-purple-500 border-t-transparent rounded-full animate-spin" />
              <span className="text-sm text-gray-500">Running prediction...</span>
            </div>
          </div>
        )}
        {!predictionLoading && result.diagnoses && result.diagnoses.length > 0 && (
          <div>
            <span className="text-xs font-medium text-gray-500 block mb-1">
              Differential Diagnosis
            </span>
            <ol className="list-decimal list-inside space-y-1">
              {result.diagnoses.map((dx) => (
                <li key={dx.disease_id} className="text-sm text-gray-700">
                  {resolveDiseaseId(dx.disease_id)}
                </li>
              ))}
            </ol>
          </div>
        )}
        {!predictionLoading && result.predictionEmpty && !result.predictionError && (
          <div>
            <span className="text-xs font-medium text-gray-500 block mb-1">
              Differential Diagnosis
            </span>
            <div className="border border-amber-200 rounded-md p-2 bg-amber-50">
              <p className="text-xs text-amber-700">
                Prediction returned no results (possible transient API error). Try restarting the simulation.
              </p>
            </div>
          </div>
        )}
        {!predictionLoading && result.predictionUnavailable && (
          <div>
            <span className="text-xs font-medium text-gray-500 block mb-1">
              Differential Diagnosis
            </span>
            <p className="text-xs text-gray-400 italic">
              OPENAI_API_KEY not configured — DDx unavailable.
            </p>
          </div>
        )}
        {!predictionLoading && result.predictionError && (
          <div>
            <span className="text-xs font-medium text-gray-500 block mb-1">
              Differential Diagnosis
            </span>
            <div className="border border-red-200 rounded-md p-2 bg-red-50">
              <p className="text-sm text-red-700">
                Prediction failed: {result.predictionError}
              </p>
            </div>
          </div>
        )}
        {/* Defensive fallback: non-ER result with no prediction flags at all */}
        {!predictionLoading &&
          result.fromPhase !== undefined && result.fromPhase > 3 &&
          !result.predictionError &&
          !result.predictionUnavailable &&
          !result.predictionEmpty &&
          (!result.diagnoses || result.diagnoses.length === 0) && (
          <div>
            <span className="text-xs font-medium text-gray-500 block mb-1">
              Differential Diagnosis
            </span>
            <p className="text-xs text-gray-400 italic">
              Prediction status unknown — no prediction data received.
            </p>
          </div>
        )}

        {/* Reason */}
        {result.reason && (
          <div>
            <span className="text-xs font-medium text-gray-500 block mb-1">
              Reason
            </span>
            <p className="text-sm text-gray-700">{result.reason}</p>
          </div>
        )}
      </div>

      {/* Skipped Terminations (when disable_early_termination was active) */}
      {result.skippedTerminations && result.skippedTerminations.length > 0 && (
        <SkippedTerminationsSection skipped={result.skippedTerminations} />
      )}

      <button
        onClick={onRestart}
        className="bg-gray-600 text-white px-4 py-2 rounded hover:bg-gray-700 transition-colors text-sm font-medium"
      >
        Restart Simulation
      </button>
    </div>
  );
}

/**
 * Collapsible section showing termination events that were skipped
 * because disable_early_termination was enabled.
 */
function SkippedTerminationsSection({ skipped }: { skipped: SkippedTermination[] }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border border-amber-200 rounded-lg bg-amber-50">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-3 text-left"
      >
        <span className="text-sm font-medium text-amber-800">
          Skipped Terminations ({skipped.length})
        </span>
        <svg
          className={`w-4 h-4 text-amber-600 transition-transform ${expanded ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {expanded && (
        <div className="px-3 pb-3 space-y-2">
          {skipped.map((entry, i) => {
            const sevColor = entry.severity
              ? SEVERITY_COLORS[entry.severity.id] ?? "bg-gray-100 text-gray-800 border-gray-300"
              : "bg-gray-100 text-gray-800 border-gray-300";
            return (
              <div key={i} className="bg-white rounded border border-amber-100 p-2 space-y-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-gray-500">
                    Phase {entry.phase}: {entry.phaseName}
                  </span>
                  {entry.severity && (
                    <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${sevColor}`}>
                      {entry.severity.name}
                    </span>
                  )}
                </div>
                {entry.departments.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {entry.departments.map((dept) => (
                      <span
                        key={dept.id}
                        className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200"
                      >
                        {dept.name}
                      </span>
                    ))}
                  </div>
                )}
                {entry.reason && (
                  <p className="text-xs text-gray-600">{entry.reason}</p>
                )}
                {entry.sourceQid && (
                  <p className="text-xs text-gray-400">Triggered by: {entry.sourceQid}</p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

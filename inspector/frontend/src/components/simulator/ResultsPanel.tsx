"use client";

import type { TerminationResult } from "@/lib/types/simulator";

interface ResultsPanelProps {
  result: TerminationResult;
  onRestart: () => void;
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
 * termination reason, and a restart button.
 */
export default function ResultsPanel({ result, onRestart }: ResultsPanelProps) {
  const sevColor =
    result.severity
      ? SEVERITY_COLORS[result.severity.id] ?? "bg-gray-100 text-gray-800 border-gray-300"
      : "bg-gray-100 text-gray-800 border-gray-300";

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

      <button
        onClick={onRestart}
        className="bg-gray-600 text-white px-4 py-2 rounded hover:bg-gray-700 transition-colors text-sm font-medium"
      >
        Restart Simulation
      </button>
    </div>
  );
}

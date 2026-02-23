"use client";

const PHASES = [
  { id: 0, label: "Demographics" },
  { id: 1, label: "ER Critical" },
  { id: 2, label: "Symptoms" },
  { id: 3, label: "ER Checklist" },
  { id: 4, label: "OLDCARTS" },
  { id: 5, label: "OPD" },
];

interface PhaseIndicatorProps {
  currentPhase: number;
  terminated: boolean;
}

/**
 * Horizontal stepper showing phases 0-5 with the current one highlighted.
 */
export default function PhaseIndicator({
  currentPhase,
  terminated,
}: PhaseIndicatorProps) {
  return (
    <div className="flex items-center gap-1 overflow-x-auto">
      {PHASES.map((p, i) => {
        const isActive = p.id === currentPhase;
        const isDone = p.id < currentPhase || terminated;

        return (
          <div key={p.id} className="flex items-center">
            {i > 0 && (
              <div
                className={`w-4 h-0.5 mx-0.5 ${
                  isDone ? "bg-green-400" : "bg-gray-300"
                }`}
              />
            )}
            <div
              className={`flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium whitespace-nowrap transition-colors ${
                isActive && !terminated
                  ? "bg-blue-500 text-white"
                  : isDone
                  ? "bg-green-100 text-green-700"
                  : "bg-gray-100 text-gray-500"
              }`}
            >
              <span
                className={`w-4 h-4 rounded-full flex items-center justify-center text-[10px] font-bold ${
                  isActive && !terminated
                    ? "bg-white text-blue-500"
                    : isDone
                    ? "bg-green-400 text-white"
                    : "bg-gray-300 text-white"
                }`}
              >
                {isDone && !isActive ? "\u2713" : p.id}
              </span>
              <span className="hidden sm:inline">{p.label}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

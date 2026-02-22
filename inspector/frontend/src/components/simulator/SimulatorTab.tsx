"use client";

import { useState, useEffect, useCallback } from "react";
import type { SimulatorDataResponse } from "@/lib/types/simulator";
import { fetchSimulatorData } from "@/lib/api/simulator";
import { useSimulator } from "@/lib/simulator/useSimulator";
import { computeAge } from "@/lib/simulator/engine";
import PhaseIndicator from "./PhaseIndicator";
import DemographicForm from "./DemographicForm";
import ErCriticalForm from "./ErCriticalForm";
import SymptomSelector from "./SymptomSelector";
import ErChecklistForm from "./ErChecklistForm";
import SequentialQuestion from "./SequentialQuestion";
import ResultsPanel from "./ResultsPanel";
import AnswerHistory from "./AnswerHistory";
import MobileFrame from "./MobileFrame";

type ViewMode = "desktop" | "mobile";

/**
 * Root component for the Simulator tab.
 * Fetches rule data, initializes the simulation hook, and renders
 * a 2-column layout: main content (left) + answer history (right).
 */
export default function SimulatorTab() {
  const [ruleData, setRuleData] = useState<SimulatorDataResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    fetchSimulatorData()
      .then((data) => {
        if (mounted) {
          setRuleData(data);
          setError(null);
        }
      })
      .catch((err) => {
        if (mounted) setError(err.message ?? "Failed to load simulator data");
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-gray-500 text-sm">Loading simulator data...</div>
      </div>
    );
  }

  if (error || !ruleData) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-red-500 text-sm">
          Error: {error ?? "No data available"}
        </div>
      </div>
    );
  }

  return <SimulatorContent ruleData={ruleData} />;
}

function SimulatorContent({
  ruleData,
}: {
  ruleData: SimulatorDataResponse;
}) {
  const sim = useSimulator(ruleData);
  const { currentStep } = sim;
  const [viewMode, setViewMode] = useState<ViewMode>("desktop");

  // Available symptoms: intersection of nhso_symptoms and oldcarts/opd keys
  const availableSymptoms = [
    ...new Set([
      ...Object.keys(ruleData.oldcarts),
      ...Object.keys(ruleData.opd),
    ]),
  ].filter((s) =>
    ruleData.nhso_symptoms.some((ns) => ns.name === s || ns.id === s)
  );

  // Go back to a specific history index (pop all entries after it)
  const goBackTo = useCallback(
    (index: number) => {
      // Pop back (history.length - index) times
      const pops = sim.history.length - index;
      for (let i = 0; i < pops; i++) {
        sim.goBack();
      }
    },
    [sim]
  );

  const age = computeAge(sim.demographics.date_of_birth as string);

  /** The main simulation form content — shared between desktop and mobile views */
  const simulationContent = (
    <>
      {/* Phase 0: Demographics */}
      {currentStep.phase === 0 && !currentStep.terminated && (
        <DemographicForm
          fields={ruleData.demographic}
          onSubmit={sim.submitAnswer}
          textOverrides={sim.textOverrides}
          onOverrideText={sim.setQuestionText}
        />
      )}

      {/* Phase 1: ER Critical Screen */}
      {currentStep.phase === 1 && !currentStep.terminated && (
        <ErCriticalForm
          items={ruleData.er_critical}
          onSubmit={sim.submitAnswer}
          textOverrides={sim.textOverrides}
          onOverrideText={sim.setQuestionText}
        />
      )}

      {/* Phase 2: Symptom Selection */}
      {currentStep.phase === 2 && !currentStep.terminated && (
        <SymptomSelector
          symptoms={ruleData.nhso_symptoms}
          availableSymptoms={availableSymptoms}
          onSubmit={sim.submitAnswer}
        />
      )}

      {/* Phase 3: ER Checklist */}
      {currentStep.phase === 3 && !currentStep.terminated && (
        <ErChecklistForm
          symptoms={[sim.primarySymptom, ...sim.secondarySymptoms]}
          age={age}
          ruleData={ruleData}
          onSubmit={sim.submitAnswer}
          textOverrides={sim.textOverrides}
          onOverrideText={sim.setQuestionText}
        />
      )}

      {/* Phases 4/5: Sequential questions */}
      {(currentStep.phase === 4 || currentStep.phase === 5) &&
        !currentStep.terminated &&
        currentStep.currentQuestion && (
          <SequentialQuestion
            key={currentStep.currentQuestion.qid}
            question={currentStep.currentQuestion}
            onSubmit={sim.submitAnswer}
            textOverrides={sim.textOverrides}
            onOverrideText={sim.setQuestionText}
            onOverrideOptionLabel={sim.setOptionLabel}
            phaseName={currentStep.phaseName}
          />
        )}

      {/* Termination / Completion result */}
      {currentStep.terminated && currentStep.result && (
        <ResultsPanel
          result={currentStep.result}
          onRestart={sim.reset}
        />
      )}

      {/* Back button (shown during active simulation, not on phase 0) */}
      {!currentStep.terminated && sim.canGoBack && (
        <div className="mt-4">
          <button
            onClick={sim.goBack}
            className="text-sm text-gray-500 hover:text-blue-500 transition-colors"
          >
            ← ย้อนกลับ
          </button>
        </div>
      )}
    </>
  );

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Top bar: Reset + Phase Indicator + View toggle */}
      <div className="flex items-center gap-3 mb-3">
        <button
          onClick={sim.reset}
          className="text-xs font-medium text-gray-500 hover:text-red-500 border border-gray-300 hover:border-red-300 rounded px-2 py-1 transition-colors"
        >
          Reset
        </button>
        <PhaseIndicator
          currentPhase={currentStep.phase}
          terminated={currentStep.terminated}
        />

        {/* Desktop / Mobile view toggle */}
        <div className="ml-auto flex items-center bg-gray-100 rounded-lg p-0.5">
          <button
            onClick={() => setViewMode("desktop")}
            className={`flex items-center gap-1 px-3 py-1 rounded-md text-xs font-medium transition-colors ${
              viewMode === "desktop"
                ? "bg-white text-gray-800 shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {/* Desktop icon */}
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="1" y="2" width="14" height="10" rx="1" />
              <line x1="5" y1="14" x2="11" y2="14" />
              <line x1="8" y1="12" x2="8" y2="14" />
            </svg>
            Desktop
          </button>
          <button
            onClick={() => setViewMode("mobile")}
            className={`flex items-center gap-1 px-3 py-1 rounded-md text-xs font-medium transition-colors ${
              viewMode === "mobile"
                ? "bg-white text-gray-800 shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {/* Mobile icon */}
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="4" y="1" width="8" height="14" rx="1.5" />
              <line x1="7" y1="12.5" x2="9" y2="12.5" />
            </svg>
            Mobile
          </button>
        </div>
      </div>

      {/* Desktop view: 2-column layout */}
      {viewMode === "desktop" && (
        <div className="flex-1 flex gap-4 min-h-0">
          {/* Main content */}
          <div className="flex-1 overflow-y-auto pr-2">
            <div className="max-w-2xl">
              {simulationContent}
            </div>
          </div>

          {/* History sidebar */}
          <div className="w-64 flex-shrink-0 border-l border-gray-200 pl-4 overflow-y-auto">
            <h4 className="text-sm font-semibold text-gray-600 mb-2">
              Answer History
            </h4>
            <AnswerHistory history={sim.history} onGoBackTo={goBackTo} />
          </div>
        </div>
      )}

      {/* Mobile preview: phone frame + history sidebar */}
      {viewMode === "mobile" && (
        <div className="flex-1 flex gap-4 min-h-0">
          <div className="flex-1 overflow-y-auto">
            <p className="text-xs text-gray-400 text-center mb-2">
              iPhone 14 preview (393 x 852 pt) — check if text is overwhelming on mobile
            </p>
            <MobileFrame>
              {simulationContent}
            </MobileFrame>
          </div>

          {/* History sidebar (kept outside the phone frame for usability) */}
          <div className="w-64 flex-shrink-0 border-l border-gray-200 pl-4 overflow-y-auto">
            <h4 className="text-sm font-semibold text-gray-600 mb-2">
              Answer History
            </h4>
            <AnswerHistory history={sim.history} onGoBackTo={goBackTo} />
          </div>
        </div>
      )}
    </div>
  );
}

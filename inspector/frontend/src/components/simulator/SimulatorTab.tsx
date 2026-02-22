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

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Top bar: Reset + Phase Indicator */}
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
      </div>

      {/* 2-column layout: main content + history sidebar */}
      <div className="flex-1 flex gap-4 min-h-0">
        {/* Main content */}
        <div className="flex-1 overflow-y-auto pr-2">
          <div className="max-w-2xl">
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
                  ← Back
                </button>
              </div>
            )}
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
    </div>
  );
}

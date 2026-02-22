/**
 * useSimulator — React hook managing the client-side prescreening simulation.
 *
 * Orchestrates the 6-phase flow using the pure-function engine and evaluator.
 * Manages history for back-navigation and text overrides for inline editing.
 */

import { useState, useCallback, useMemo } from "react";
import type {
  RawQuestion,
  SimulatorDataResponse,
  TerminationResult,
  HistoryEntry,
  TextOverride,
} from "../types/simulator";
import {
  computeAge,
  getFirstQid,
  resolveNext,
  determineAction,
  processAction,
  getErChecklistItems,
  resolveErChecklistTermination,
  buildErCriticalTermination,
} from "./engine";

/** Phase names for display */
const PHASE_NAMES: Record<number, string> = {
  0: "Demographics",
  1: "ER Critical Screen",
  2: "Symptom Selection",
  3: "ER Checklist",
  4: "OLDCARTS",
  5: "OPD",
};

/** What the UI should currently render */
export interface CurrentStep {
  phase: number;
  phaseName: string;
  /** True if the simulation has ended */
  terminated: boolean;
  /** The termination result (only set when terminated) */
  result: TerminationResult | null;
  /** The current user-facing question (only for sequential phases 4/5) */
  currentQuestion: RawQuestion | null;
}

/** The full public API returned by useSimulator */
export interface SimulatorAPI {
  currentStep: CurrentStep;
  /** Submit an answer for the current phase/question */
  submitAnswer: (value: unknown) => void;
  /** Whether back-navigation is available */
  canGoBack: boolean;
  /** Go back to the previous step */
  goBack: () => void;
  /** Reset the simulation to phase 0 */
  reset: () => void;
  /** Override a question's display text */
  setQuestionText: (qid: string, text: string) => void;
  /** Override an option's display label */
  setOptionLabel: (qid: string, optionId: string, label: string) => void;
  /** Current text overrides */
  textOverrides: Record<string, TextOverride>;
  /** History entries for the sidebar */
  history: HistoryEntry[];
  /** Demographics (readable for display) */
  demographics: Record<string, unknown>;
  /** ER critical items for phase 1 form */
  erCriticalFlags: Record<string, boolean>;
  /** ER checklist items for phase 3 form */
  erChecklistFlags: Record<string, boolean>;
  /** Primary symptom */
  primarySymptom: string;
  /** Secondary symptoms */
  secondarySymptoms: string[];
  /** All answers (for history display) */
  allAnswers: Record<string, unknown>;
}

export function useSimulator(ruleData: SimulatorDataResponse): SimulatorAPI {
  // --- Core simulation state ---
  const [phase, setPhase] = useState(0);
  const [demographics, setDemographics] = useState<Record<string, unknown>>({});
  const [allAnswers, setAllAnswers] = useState<Record<string, unknown>>({});
  const [primarySymptom, setPrimarySymptom] = useState("");
  const [secondarySymptoms, setSecondarySymptoms] = useState<string[]>([]);
  const [erCriticalFlags, setErCriticalFlags] = useState<Record<string, boolean>>({});
  const [erChecklistFlags, setErChecklistFlags] = useState<Record<string, boolean>>({});
  const [pending, setPending] = useState<string[]>([]);
  const [terminated, setTerminated] = useState(false);
  const [result, setResult] = useState<TerminationResult | null>(null);
  const [currentQuestion, setCurrentQuestion] = useState<RawQuestion | null>(null);

  // --- History for back-navigation ---
  const [history, setHistory] = useState<HistoryEntry[]>([]);

  // --- Text overrides for inline editing ---
  const [textOverrides, setTextOverrides] = useState<Record<string, TextOverride>>({});

  // --- Snapshot helpers ---

  /** Create a snapshot of current state for history */
  const snapshot = useCallback(
    (label: string, answerValue: unknown): HistoryEntry => ({
      phase,
      demographics: { ...demographics },
      allAnswers: { ...allAnswers },
      primarySymptom,
      secondarySymptoms: [...secondarySymptoms],
      erCriticalFlags: { ...erCriticalFlags },
      erChecklistFlags: { ...erChecklistFlags },
      pending: [...pending],
      currentQuestion,
      label,
      answerValue,
    }),
    [
      phase,
      demographics,
      allAnswers,
      primarySymptom,
      secondarySymptoms,
      erCriticalFlags,
      erChecklistFlags,
      pending,
      currentQuestion,
    ]
  );

  /** Restore state from a history snapshot */
  const restore = useCallback((entry: HistoryEntry) => {
    setPhase(entry.phase);
    setDemographics(entry.demographics);
    setAllAnswers(entry.allAnswers);
    setPrimarySymptom(entry.primarySymptom);
    setSecondarySymptoms(entry.secondarySymptoms);
    setErCriticalFlags(entry.erCriticalFlags);
    setErChecklistFlags(entry.erChecklistFlags);
    setPending(entry.pending);
    setCurrentQuestion(entry.currentQuestion);
    setTerminated(false);
    setResult(null);
  }, []);

  // --- Advance to sequential phase ---

  /** Enter phase 4 or 5 by seeding the pending queue with the first qid */
  const enterSequentialPhase = useCallback(
    (
      nextPhase: 4 | 5,
      symptom: string,
      answers: Record<string, unknown>,
      demos: Record<string, unknown>
    ) => {
      const source = nextPhase === 4 ? "oldcarts" : "opd";
      const firstQid = getFirstQid(source as "oldcarts" | "opd", symptom, ruleData);

      if (!firstQid) {
        // No questions for this symptom in this source
        if (nextPhase === 4) {
          // Try OPD
          enterSequentialPhase(5, symptom, answers, demos);
          return;
        }
        // Phase 5 exhausted — complete without explicit termination
        setPhase(5);
        setTerminated(true);
        setResult({
          type: "completed",
          departments: [],
          severity: null,
          reason: "All phases completed without explicit termination",
        });
        return;
      }

      const resolved = resolveNext(
        source as "oldcarts" | "opd",
        symptom,
        [firstQid],
        answers,
        demos,
        ruleData,
        nextPhase
      );

      setPhase(nextPhase);

      if (resolved.kind === "question") {
        setCurrentQuestion(resolved.question);
        setPending(resolved.pending);
      } else if (resolved.kind === "terminate") {
        setTerminated(true);
        setResult(resolved.termination);
        setPending(resolved.pending);
      } else if (resolved.kind === "advance_to_opd") {
        // OLDCARTS auto-eval chain produced an OPD action
        enterSequentialPhase(5, symptom, answers, demos);
      } else {
        // exhausted — advance to next phase
        if (nextPhase === 4) {
          enterSequentialPhase(5, symptom, answers, demos);
        } else {
          setTerminated(true);
          setResult({
            type: "completed",
            departments: [],
            severity: null,
            reason: "All phases completed without explicit termination",
          });
        }
      }
    },
    [ruleData]
  );

  // --- Submit answer ---

  const submitAnswer = useCallback(
    (value: unknown) => {
      if (terminated) return;

      if (phase === 0) {
        // Demographics submission: value is the full demographics object
        const demos = value as Record<string, unknown>;
        const label = "Demographics submitted";
        setHistory((h) => [...h, snapshot(label, value)]);
        setDemographics(demos);
        setPhase(1);
        return;
      }

      if (phase === 1) {
        // ER Critical: value is Record<string, boolean>
        const flags = value as Record<string, boolean>;
        const label = "ER Critical Screen submitted";
        setHistory((h) => [...h, snapshot(label, value)]);
        setErCriticalFlags(flags);

        // Record in allAnswers
        const nextAnswers = { ...allAnswers, ...flags };
        setAllAnswers(nextAnswers);

        // Check for any positive
        const positiveQids = Object.entries(flags)
          .filter(([, v]) => v === true)
          .map(([k]) => k);

        if (positiveQids.length > 0) {
          setTerminated(true);
          setResult(buildErCriticalTermination(positiveQids, ruleData));
          return;
        }

        setPhase(2);
        return;
      }

      if (phase === 2) {
        // Symptom selection: value is { primary_symptom, secondary_symptoms? }
        const sel = value as {
          primary_symptom: string;
          secondary_symptoms?: string[];
        };
        const label = `Symptoms: ${sel.primary_symptom}`;
        setHistory((h) => [...h, snapshot(label, value)]);
        setPrimarySymptom(sel.primary_symptom);
        setSecondarySymptoms(sel.secondary_symptoms ?? []);
        setPhase(3);
        return;
      }

      if (phase === 3) {
        // ER Checklist: value is Record<string, boolean>
        const flags = value as Record<string, boolean>;
        const label = "ER Checklist submitted";
        setHistory((h) => [...h, snapshot(label, value)]);
        setErChecklistFlags(flags);

        const nextAnswers = { ...allAnswers, ...flags };
        setAllAnswers(nextAnswers);

        // Check for first positive item
        const symptoms = [primarySymptom, ...secondarySymptoms];
        const age = computeAge(demographics.date_of_birth as string);
        const termResult = resolveErChecklistTermination(
          flags,
          symptoms,
          age,
          ruleData
        );

        if (termResult) {
          setTerminated(true);
          setResult(termResult);
          return;
        }

        // All negative — advance to OLDCARTS
        enterSequentialPhase(4, primarySymptom, nextAnswers, demographics);
        return;
      }

      if (phase === 4 || phase === 5) {
        // Sequential answer: value is the answer for currentQuestion
        if (!currentQuestion) return;

        const label = currentQuestion.question;
        setHistory((h) => [...h, snapshot(label, value)]);

        const nextAnswers = { ...allAnswers, [currentQuestion.qid]: value };
        setAllAnswers(nextAnswers);

        // Determine action from the question definition
        const action = determineAction(currentQuestion, value);
        const source = phase === 4 ? "oldcarts" : "opd";

        if (!action) {
          // No action determined — try to continue with existing pending
          const resolved = resolveNext(
            source as "oldcarts" | "opd",
            primarySymptom,
            [...pending],
            nextAnswers,
            demographics,
            ruleData,
            phase
          );
          handleResolveResult(resolved, nextAnswers);
          return;
        }

        // Process the action
        const newPending = [...pending];
        const actionResult = processAction(
          action,
          newPending,
          nextAnswers,
          ruleData,
          phase
        );

        if (actionResult.type === "terminate") {
          setTerminated(true);
          setResult(actionResult.termination!);
          setPending(newPending);
          return;
        }

        if (actionResult.type === "advance_to_opd") {
          enterSequentialPhase(5, primarySymptom, nextAnswers, demographics);
          return;
        }

        // Goto — resolve next from the updated pending queue
        const resolved = resolveNext(
          source as "oldcarts" | "opd",
          primarySymptom,
          newPending,
          nextAnswers,
          demographics,
          ruleData,
          phase
        );
        handleResolveResult(resolved, nextAnswers);
        return;
      }
    },
    [
      phase,
      terminated,
      demographics,
      allAnswers,
      primarySymptom,
      secondarySymptoms,
      erCriticalFlags,
      erChecklistFlags,
      pending,
      currentQuestion,
      history,
      snapshot,
      ruleData,
      enterSequentialPhase,
    ]
  );

  /** Handle a ResolveResult and update state accordingly */
  const handleResolveResult = useCallback(
    (
      resolved: ReturnType<typeof resolveNext>,
      answers: Record<string, unknown>
    ) => {
      if (resolved.kind === "question") {
        setCurrentQuestion(resolved.question);
        setPending(resolved.pending);
      } else if (resolved.kind === "terminate") {
        setTerminated(true);
        setResult(resolved.termination);
        setPending(resolved.pending);
      } else if (resolved.kind === "advance_to_opd") {
        enterSequentialPhase(5, primarySymptom, answers, demographics);
      } else {
        // exhausted
        if (phase === 4) {
          enterSequentialPhase(5, primarySymptom, answers, demographics);
        } else {
          setTerminated(true);
          setResult({
            type: "completed",
            departments: [],
            severity: null,
            reason: "All phases completed without explicit termination",
          });
        }
      }
    },
    [phase, primarySymptom, demographics, enterSequentialPhase]
  );

  // --- Back navigation ---

  const canGoBack = history.length > 0;

  const goBack = useCallback(() => {
    if (history.length === 0) return;
    const prev = history[history.length - 1];
    setHistory((h) => h.slice(0, -1));
    restore(prev);
  }, [history, restore]);

  // --- Reset ---

  const reset = useCallback(() => {
    setPhase(0);
    setDemographics({});
    setAllAnswers({});
    setPrimarySymptom("");
    setSecondarySymptoms([]);
    setErCriticalFlags({});
    setErChecklistFlags({});
    setPending([]);
    setTerminated(false);
    setResult(null);
    setCurrentQuestion(null);
    setHistory([]);
    // Note: textOverrides are preserved across reset
  }, []);

  // --- Text override setters ---

  const setQuestionText = useCallback((qid: string, text: string) => {
    setTextOverrides((prev) => ({
      ...prev,
      [qid]: { ...prev[qid], questionText: text },
    }));
  }, []);

  const setOptionLabel = useCallback(
    (qid: string, optionId: string, label: string) => {
      setTextOverrides((prev) => ({
        ...prev,
        [qid]: {
          ...prev[qid],
          optionLabels: { ...(prev[qid]?.optionLabels ?? {}), [optionId]: label },
        },
      }));
    },
    []
  );

  // --- Current step (derived state) ---

  const currentStep: CurrentStep = useMemo(
    () => ({
      phase,
      phaseName: PHASE_NAMES[phase] ?? `Phase ${phase}`,
      terminated,
      result,
      currentQuestion,
    }),
    [phase, terminated, result, currentQuestion]
  );

  return {
    currentStep,
    submitAnswer,
    canGoBack,
    goBack,
    reset,
    setQuestionText,
    setOptionLabel,
    textOverrides,
    history,
    demographics,
    erCriticalFlags,
    erChecklistFlags,
    primarySymptom,
    secondarySymptoms,
    allAnswers,
  };
}

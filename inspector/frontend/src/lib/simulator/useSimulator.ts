/**
 * useSimulator — React hook managing the client-side prescreening simulation.
 *
 * Orchestrates the 6-phase flow using the pure-function engine and evaluator.
 * Manages history for back-navigation and text overrides for inline editing.
 */

import { useState, useCallback, useMemo, useRef } from "react";
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
import type { QAPairPayload } from "../api/llm";
import type { LLMAnswerPair } from "../../components/simulator/LLMQuestionsPanel";
import { generateQuestions, predict } from "../api/llm";

/** Phase names for display */
const PHASE_NAMES: Record<number, string> = {
  0: "Demographics",
  1: "ER Critical Screen",
  2: "Symptom Selection",
  3: "ER Checklist",
  4: "OLDCARTS",
  5: "OPD",
  6: "LLM Questions",
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
  /** LLM phase state (phase 6) */
  llmLoading: boolean;
  llmQuestions: string[] | null;
  llmError: string | null;
  /** True while the LLM prediction call is in-flight */
  predictionLoading: boolean;
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
  /** Proceed from LLM questions phase to results (with LLM answers for prediction) */
  proceedToResults: (llmAnswers: LLMAnswerPair[]) => void;
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

  // --- LLM phase state (phase 6) ---
  const [llmLoading, setLlmLoading] = useState(false);
  const [llmQuestions, setLlmQuestions] = useState<string[] | null>(null);
  const [llmError, setLlmError] = useState<string | null>(null);
  const [pendingResult, _setPendingResult] = useState<TerminationResult | null>(null);
  const [predictionLoading, setPredictionLoading] = useState(false);
  // Guard ref to ignore stale LLM API responses after reset/back-nav
  const llmRequestIdRef = useRef(0);
  // Mirror pendingResult in a ref so proceedToResults always reads the latest
  // value synchronously, bypassing any useCallback closure staleness.
  const pendingResultRef = useRef<TerminationResult | null>(null);
  const setPendingResult = useCallback((val: TerminationResult | null) => {
    pendingResultRef.current = val;
    _setPendingResult(val);
  }, []);

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
      pendingResult,
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
      pendingResult,
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
    setPendingResult(entry.pendingResult);
    setTerminated(false);
    setResult(null);
    // Invalidate any in-flight LLM request
    llmRequestIdRef.current++;
    setLlmLoading(false);
    setLlmQuestions(null);
    setLlmError(null);
    setPredictionLoading(false);
  }, []);

  // --- LLM phase helpers ---

  /** Build QAPairPayload[] from the current simulation state for the LLM endpoint */
  const buildQAPairs = useCallback(
    (
      demos: Record<string, unknown>,
      answers: Record<string, unknown>,
      symptom: string,
      critFlags: Record<string, boolean>,
      checkFlags: Record<string, boolean>
    ): QAPairPayload[] => {
      const pairs: QAPairPayload[] = [];

      // Phase 0: demographics as a single entry
      if (Object.keys(demos).length > 0) {
        pairs.push({
          question: "Patient demographics",
          answer: demos,
          source: "rule_based",
          qid: null,
          question_type: "demographics",
          phase: 0,
        });
      }

      // Phase 1: ER critical flags
      for (const item of ruleData.er_critical) {
        if (item.qid in critFlags) {
          pairs.push({
            question: item.text,
            answer: critFlags[item.qid],
            source: "rule_based",
            qid: item.qid,
            question_type: "er_critical",
            phase: 1,
          });
        }
      }

      // Phase 2: primary symptom
      if (symptom) {
        pairs.push({
          question: "Primary symptom",
          answer: symptom,
          source: "rule_based",
          qid: null,
          question_type: "symptom_selection",
          phase: 2,
        });
      }

      // Phase 3: ER checklist flags
      for (const [qid, val] of Object.entries(checkFlags)) {
        pairs.push({
          question: qid,
          answer: val,
          source: "rule_based",
          qid,
          question_type: "er_checklist",
          phase: 3,
        });
      }

      // Phases 4/5: sequential answers matched to question definitions
      for (const source of ["oldcarts", "opd"] as const) {
        const phaseNum = source === "oldcarts" ? 4 : 5;
        const questions = ruleData[source]?.[symptom] ?? [];
        for (const q of questions) {
          if (q.qid in answers) {
            pairs.push({
              question: q.question,
              answer: answers[q.qid],
              source: "rule_based",
              qid: q.qid,
              question_type: q.question_type,
              phase: phaseNum,
            });
          }
        }
      }

      return pairs;
    },
    [ruleData]
  );

  /**
   * Route a termination result: ER terminations (phases 1/3) go straight
   * to results; normal completions enter the LLM phase first.
   */
  const triggerTermination = useCallback(
    (termResult: TerminationResult, answersOverride?: Record<string, unknown>) => {
      // ER terminations skip the LLM phase
      if (termResult.fromPhase !== undefined && termResult.fromPhase <= 3) {
        setTerminated(true);
        setResult(termResult);
        return;
      }

      // Non-ER: enter LLM phase
      setPendingResult(termResult);
      setPhase(6);
      setLlmLoading(true);
      setLlmQuestions(null);
      setLlmError(null);

      const requestId = ++llmRequestIdRef.current;

      // Use answersOverride when provided to avoid stale closure values
      // (e.g. when called from submitAnswer right after setAllAnswers)
      const qaPairs = buildQAPairs(
        demographics,
        answersOverride ?? allAnswers,
        primarySymptom,
        erCriticalFlags,
        erChecklistFlags
      );

      generateQuestions(qaPairs)
        .then((resp) => {
          // Ignore stale responses (user reset or navigated back)
          if (llmRequestIdRef.current !== requestId) return;

          if (!resp.available) {
            // OPENAI_API_KEY not set — skip to results
            setLlmLoading(false);
            setTerminated(true);
            setResult(termResult);
            setPendingResult(null);
            return;
          }

          setLlmLoading(false);
          if (resp.error) {
            setLlmError(resp.error);
          }
          setLlmQuestions(resp.questions);
        })
        .catch((err) => {
          if (llmRequestIdRef.current !== requestId) return;
          setLlmLoading(false);
          setLlmError(err.message ?? "Failed to generate questions");
          setLlmQuestions([]);
        });
    },
    [demographics, allAnswers, primarySymptom, erCriticalFlags, erChecklistFlags, buildQAPairs]
  );

  /** Proceed from LLM questions phase to final results.
   *  Calls the predict endpoint to get DDx before showing results.
   *
   *  Reads pendingResult from a ref (not the useState closure) to guarantee
   *  we always see the latest value regardless of React render timing. */
  const proceedToResults = useCallback((llmAnswers: LLMAnswerPair[]) => {
    // Read from ref — always current, immune to closure staleness
    const pr = pendingResultRef.current;
    if (!pr) {
      console.warn("[Simulator] proceedToResults: pendingResult is null — skipping predict");
      return;
    }

    console.log("[Simulator] proceedToResults: pendingResult =", pr);
    setPredictionLoading(true);
    const requestId = llmRequestIdRef.current;

    // Build rule-based QA pairs then append LLM-generated answers
    const qaPairs = buildQAPairs(
      demographics,
      allAnswers,
      primarySymptom,
      erCriticalFlags,
      erChecklistFlags
    );
    for (const pair of llmAnswers) {
      qaPairs.push({
        question: pair.question,
        answer: pair.answer,
        source: "llm_generated",
        qid: null,
        question_type: null,
        phase: null,
      });
    }

    // Determine context for prediction: rule-based severity/ER from pending result
    const rbSeverity = pr.severity?.id ?? null;
    const erOverride =
      rbSeverity === "sev003" &&
      pr.departments.some((d) => d.id === "dept002");

    console.log("[Simulator] Calling predict with", qaPairs.length, "QA pairs");

    predict(qaPairs, rbSeverity, erOverride)
      .then((resp) => {
        if (llmRequestIdRef.current !== requestId) return;
        console.log("[Simulator] Prediction response:", resp);
        setPredictionLoading(false);

        let finalResult: TerminationResult = { ...pr };
        if (resp.available && resp.prediction) {
          finalResult = {
            ...finalResult,
            diagnoses: resp.prediction.diagnoses,
            // Override departments/severity from LLM prediction
            ...(resp.prediction.departments.length > 0
              ? {
                  departments: resp.prediction.departments.map((id: string) => {
                    const dept = ruleData.departments.find((d) => d.id === id);
                    return { id, name: dept?.name ?? id };
                  }),
                }
              : {}),
            ...(resp.prediction.severity
              ? {
                  severity: (() => {
                    const sev = ruleData.severity_levels.find(
                      (s) => s.id === resp.prediction!.severity
                    );
                    return {
                      id: resp.prediction!.severity,
                      name: sev?.name ?? resp.prediction!.severity,
                    };
                  })(),
                }
              : {}),
          };
          // Detect empty prediction — API returned success but no useful data
          // (e.g. transient OpenAI error caught by the prediction module)
          if (resp.prediction.diagnoses.length === 0 && !resp.prediction.severity) {
            finalResult.predictionEmpty = true;
          }
        } else if (!resp.available) {
          finalResult = { ...finalResult, predictionUnavailable: true };
        } else if (resp.error) {
          // Server returned available:true but prediction failed (e.g. API error)
          finalResult = { ...finalResult, predictionError: resp.error };
        } else {
          // Fallback: server returned available:true but prediction is null with no error
          finalResult = { ...finalResult, predictionError: "Prediction returned no data" };
        }

        setTerminated(true);
        setResult(finalResult);
        setPendingResult(null);
      })
      .catch((err) => {
        if (llmRequestIdRef.current !== requestId) return;
        console.error("[Simulator] Prediction failed:", err);
        setPredictionLoading(false);
        setTerminated(true);
        setResult({
          ...pr,
          predictionError: err?.message ?? "Prediction request failed",
        });
        setPendingResult(null);
      });
  }, [
    demographics,
    allAnswers,
    primarySymptom,
    erCriticalFlags,
    erChecklistFlags,
    buildQAPairs,
    ruleData,
    setPendingResult,
  ]);

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
        triggerTermination({
          type: "completed",
          departments: [],
          severity: null,
          reason: "All phases completed without explicit termination",
          fromPhase: 5,
        }, answers);
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
        triggerTermination(resolved.termination, answers);
        setPending(resolved.pending);
      } else if (resolved.kind === "advance_to_opd") {
        // OLDCARTS auto-eval chain produced an OPD action
        enterSequentialPhase(5, symptom, answers, demos);
      } else {
        // exhausted — advance to next phase
        if (nextPhase === 4) {
          enterSequentialPhase(5, symptom, answers, demos);
        } else {
          triggerTermination({
            type: "completed",
            departments: [],
            severity: null,
            reason: "All phases completed without explicit termination",
            fromPhase: 5,
          }, answers);
        }
      }
    },
    [ruleData, triggerTermination]
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
          triggerTermination(buildErCriticalTermination(positiveQids, ruleData));
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
          triggerTermination(termResult);
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
          triggerTermination(actionResult.termination!, nextAnswers);
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
      triggerTermination,
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
        triggerTermination(resolved.termination, answers);
        setPending(resolved.pending);
      } else if (resolved.kind === "advance_to_opd") {
        enterSequentialPhase(5, primarySymptom, answers, demographics);
      } else {
        // exhausted
        if (phase === 4) {
          enterSequentialPhase(5, primarySymptom, answers, demographics);
        } else {
          triggerTermination({
            type: "completed",
            departments: [],
            severity: null,
            reason: "All phases completed without explicit termination",
            fromPhase: 5,
          }, answers);
        }
      }
    },
    [phase, primarySymptom, demographics, enterSequentialPhase, triggerTermination]
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
    // Invalidate any in-flight LLM request and clear LLM state
    llmRequestIdRef.current++;
    setLlmLoading(false);
    setLlmQuestions(null);
    setLlmError(null);
    setPendingResult(null);
    setPredictionLoading(false);
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
      llmLoading,
      llmQuestions,
      llmError,
      predictionLoading,
    }),
    [phase, terminated, result, currentQuestion, llmLoading, llmQuestions, llmError, predictionLoading]
  );

  return {
    currentStep,
    submitAnswer,
    canGoBack,
    goBack,
    reset,
    proceedToResults,
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

/**
 * Client-side port of PrescreenEngine._resolve_next logic.
 *
 * Pure functions that determine the next user-facing question or
 * termination given the current state of the simulation. No React
 * state — all state is passed in and returned.
 */

import type {
  RawAction,
  RawErChecklistItem,
  RawErCriticalItem,
  RawQuestion,
  SimulatorDataResponse,
  TerminationResult,
} from "../types/simulator";
import { compare, evalAgeFilter, evalConditional, evalGenderFilter } from "./evaluator";

/** Question types that the engine auto-evaluates (never shown to user) */
const AUTO_EVAL_TYPES = new Set(["gender_filter", "age_filter", "conditional"]);

/** Default ER severity and department for phase 1 critical items */
const DEFAULT_ER_SEVERITY = "sev003";
const DEFAULT_ER_DEPARTMENT = "dept002";

/** Patients younger than this use the pediatric ER checklist */
const PEDIATRIC_AGE_THRESHOLD = 15;

/** Fixed severity for urgency actions in OLDCARTS (always "Visit Urgently") */
const DEFAULT_URGENCY_SEVERITY = "sev002_5";

// --- Age computation ---

/**
 * Compute patient age in years from a date-of-birth string (ISO format).
 * Returns null if dob is missing or invalid.
 */
export function computeAge(dob: string | null | undefined): number | null {
  if (!dob) return null;
  try {
    const dobDate = new Date(dob);
    if (isNaN(dobDate.getTime())) return null;
    const today = new Date();
    let age = today.getFullYear() - dobDate.getFullYear();
    const monthDiff = today.getMonth() - dobDate.getMonth();
    if (
      monthDiff < 0 ||
      (monthDiff === 0 && today.getDate() < dobDate.getDate())
    ) {
      age--;
    }
    return age;
  } catch {
    return null;
  }
}

// --- Question lookup helpers ---

/** Build a map from qid → RawQuestion for quick lookup within a symptom's question list */
function buildQuestionMap(
  questions: RawQuestion[]
): Map<string, RawQuestion> {
  const map = new Map<string, RawQuestion>();
  for (const q of questions) {
    map.set(q.qid, q);
  }
  return map;
}

/** Get the first question ID for a source/symptom, or null if none exist */
export function getFirstQid(
  source: "oldcarts" | "opd",
  symptom: string,
  ruleData: SimulatorDataResponse
): string | null {
  const questions = ruleData[source]?.[symptom];
  if (!questions || questions.length === 0) return null;
  return questions[0].qid;
}

// --- Action extraction ---

/**
 * Determine which action to execute based on the question type and user answer.
 * Mirrors PrescreenEngine._determine_action.
 */
export function determineAction(
  question: RawQuestion,
  value: unknown
): RawAction | null {
  const qt = question.question_type;

  if (qt === "single_select" || qt === "image_single_select") {
    // value is the selected option ID
    for (const opt of question.options ?? []) {
      if (opt.id === value) return opt.action ?? null;
    }
    return null;
  }

  if (qt === "multi_select" || qt === "image_multi_select") {
    return question.next ?? null;
  }

  if (
    qt === "free_text" ||
    qt === "free_text_with_fields" ||
    qt === "number_range"
  ) {
    return question.on_submit ?? null;
  }

  return null;
}

// --- Action processing ---

/**
 * Result of processing an action: either null (goto — caller continues),
 * or a TerminationResult / phase-advance signal.
 */
export interface ActionResult {
  type: "continue" | "terminate" | "advance_to_opd";
  termination?: TerminationResult;
}

/**
 * Process an action and return what should happen next.
 *
 * For "goto": adds target qids to the front of pending, returns "continue".
 * For "opd": returns "advance_to_opd" signal.
 * For "terminate": returns a TerminationResult.
 */
export function processAction(
  action: RawAction,
  pending: string[],
  answers: Record<string, unknown>,
  ruleData: SimulatorDataResponse,
  currentPhase: number
): ActionResult {
  if (action.action === "goto") {
    // Add goto targets to front of pending, skipping already-answered ones
    const newQids = (action.qid ?? []).filter(
      (q) => !(q in answers) && !pending.includes(q)
    );
    pending.unshift(...newQids);
    return { type: "continue" };
  }

  if (action.action === "opd") {
    return { type: "advance_to_opd" };
  }

  if (action.action === "terminate") {
    const meta = action.metadata ?? {};
    const deptIds = (meta.department ?? []).map((d) => d.id);
    const sevIds = meta.severity ?? [];
    const sevId = sevIds.length > 0 ? sevIds[0].id : null;

    // Resolve human-readable names from constants
    const deptMap = new Map(ruleData.departments.map((d) => [d.id, d.name]));
    const sevMap = new Map(
      ruleData.severity_levels.map((s) => [s.id, s.name])
    );

    return {
      type: "terminate",
      termination: {
        type: currentPhase < 7 ? "terminated" : "completed",
        departments: deptIds.map((id) => ({
          id,
          name: deptMap.get(id) ?? id,
        })),
        severity: sevId
          ? { id: sevId, name: sevMap.get(sevId) ?? sevId }
          : null,
        reason: meta.reason ?? null,
        fromPhase: currentPhase,
      },
    };
  }

  if (action.action === "urgency") {
    // Immediate termination with urgency severity (sev002_5) and
    // departments from action metadata (may be empty).
    const meta = action.metadata ?? {};
    const deptIds = (meta.department ?? []).map((d) => d.id);
    return {
      type: "terminate",
      termination: buildUrgencyTermination(deptIds, ruleData, currentPhase),
    };
  }

  if (action.action === "emergency") {
    // Immediate termination with Emergency severity (sev003) and dept002
    const deptMap = new Map(ruleData.departments.map((d) => [d.id, d.name]));
    const sevMap = new Map(
      ruleData.severity_levels.map((s) => [s.id, s.name])
    );
    return {
      type: "terminate",
      termination: {
        type: currentPhase < 7 ? "terminated" : "completed",
        departments: [
          {
            id: DEFAULT_ER_DEPARTMENT,
            name: deptMap.get(DEFAULT_ER_DEPARTMENT) ?? DEFAULT_ER_DEPARTMENT,
          },
        ],
        severity: {
          id: DEFAULT_ER_SEVERITY,
          name: sevMap.get(DEFAULT_ER_SEVERITY) ?? DEFAULT_ER_SEVERITY,
        },
        reason: null,
        fromPhase: currentPhase,
      },
    };
  }

  return { type: "continue" };
}

// --- Core resolve loop ---

/**
 * Resolve the next user-facing question from the pending queue.
 *
 * Auto-evaluates filter/conditional questions transparently.
 * Returns either:
 *   - { question, pending } — the next user-facing question to show
 *   - { termination } — the simulation should terminate
 *   - { advanceToOpd: true } — should transition to past history (phase 5)
 *   - { exhausted: true } — pending queue empty, advance to next phase
 */
export type ResolveResult =
  | { kind: "question"; question: RawQuestion; pending: string[] }
  | { kind: "terminate"; termination: TerminationResult; pending: string[] }
  | { kind: "advance_to_opd"; pending: string[] }
  | { kind: "exhausted"; pending: string[] };

export function resolveNext(
  source: "oldcarts" | "opd",
  symptom: string,
  pending: string[],
  answers: Record<string, unknown>,
  demographics: Record<string, unknown>,
  ruleData: SimulatorDataResponse,
  currentPhase: number
): ResolveResult {
  const questions = ruleData[source]?.[symptom] ?? [];
  const qMap = buildQuestionMap(questions);

  // Ensure age is available for age_filter evaluation
  const demoWithAge = { ...demographics };
  if (!("age" in demoWithAge)) {
    const age = computeAge(demoWithAge.date_of_birth as string);
    if (age !== null) demoWithAge.age = age;
  }

  // Work on a copy to avoid mutating the caller's array unexpectedly
  const queue = [...pending];

  while (queue.length > 0) {
    const qid = queue.shift()!;

    // Skip already-answered questions
    if (qid in answers) continue;

    const question = qMap.get(qid);
    if (!question) continue;

    // Check if this is an auto-eval type
    if (AUTO_EVAL_TYPES.has(question.question_type)) {
      const action = autoEvaluate(question, answers, demoWithAge);
      if (!action) continue;

      const result = processAction(
        action,
        queue,
        answers,
        ruleData,
        currentPhase
      );
      if (result.type === "terminate") {
        return {
          kind: "terminate",
          termination: result.termination!,
          pending: queue,
        };
      }
      if (result.type === "advance_to_opd") {
        return { kind: "advance_to_opd", pending: queue };
      }
      // "continue" — goto added targets to queue, loop continues
      continue;
    }

    // User-facing question found
    return { kind: "question", question, pending: queue };
  }

  // Pending queue exhausted
  return { kind: "exhausted", pending: queue };
}

// --- Auto-evaluation dispatcher ---

/**
 * Auto-evaluate a filter/conditional question.
 * Returns the resolved action or null if no match.
 */
function autoEvaluate(
  question: RawQuestion,
  answers: Record<string, unknown>,
  demographics: Record<string, unknown>
): RawAction | null {
  const qt = question.question_type;

  if (qt === "conditional") {
    return evalConditional(
      question.rules ?? [],
      question.default,
      answers,
      demographics
    );
  }
  if (qt === "age_filter") {
    const age =
      typeof demographics.age === "number"
        ? demographics.age
        : computeAge(demographics.date_of_birth as string);
    return evalAgeFilter(question.options ?? [], age);
  }
  if (qt === "gender_filter") {
    return evalGenderFilter(
      question.options ?? [],
      String(demographics.gender ?? "")
    );
  }

  return null;
}

// --- ER critical conditional visibility ---

/**
 * Filter ER critical items to those visible for the given demographics.
 *
 * Items without a ``condition`` are always visible. Items with a condition
 * are visible only when the condition is satisfied (same semantics as the
 * Python ``_evaluate_field_condition``). A missing demographics value for
 * the condition field means the condition is not met → item hidden.
 */
export function getVisibleErCriticalItems(
  items: RawErCriticalItem[],
  demographics: Record<string, unknown>
): RawErCriticalItem[] {
  return items.filter((item) => {
    if (!item.condition) return true;
    const val = demographics[item.condition.field];
    if (val === undefined || val === null) return false;
    return compare(item.condition.op, val, item.condition.value);
  });
}

// --- Demographics enrichment ---

/**
 * Enrich demographics with computed fields for condition evaluation.
 *
 * Adds ``age_in_months`` (= age * 12 + age_months) so ER checklist
 * auto_complete conditions can reference sub-year ages (e.g. < 6 months).
 */
function enrichDemographics(
  demographics: Record<string, unknown>
): Record<string, unknown> {
  const enriched = { ...demographics };
  const age = typeof enriched.age === "number" ? enriched.age : null;
  const ageMonths =
    typeof enriched.age_months === "number" ? enriched.age_months : 0;
  if (age !== null) {
    enriched.age_in_months = age * 12 + ageMonths;
  }
  return enriched;
}

// --- ER checklist helpers ---

/** Resolve severity and department IDs from an ER checklist item */
function resolveErItemIds(
  item: RawErChecklistItem,
  pediatric: boolean
): { sevId: string; deptId: string } {
  const sevField = pediatric ? item.severity : item.min_severity;
  const sevId =
    sevField && typeof sevField === "object" && "id" in sevField
      ? sevField.id
      : DEFAULT_ER_SEVERITY;

  let deptId = DEFAULT_ER_DEPARTMENT;
  if (
    item.department &&
    Array.isArray(item.department) &&
    item.department.length > 0
  ) {
    const firstDept = item.department[0];
    if (typeof firstDept === "object" && "id" in firstDept) {
      deptId = firstDept.id;
    }
  }
  return { sevId, deptId };
}

/**
 * Check if any ER checklist auto_complete condition is met.
 *
 * Returns a TerminationResult for the first matching auto_complete item,
 * or null if none match.  Called when transitioning from phase 2 to 3
 * to auto-terminate before showing the checklist.
 */
export function checkErAutoComplete(
  symptoms: string[],
  age: number | null,
  demographics: Record<string, unknown>,
  ruleData: SimulatorDataResponse
): TerminationResult | null {
  const pediatric = age !== null && age < PEDIATRIC_AGE_THRESHOLD;
  const source = pediatric ? ruleData.er_pediatric : ruleData.er_adult;
  const enriched = enrichDemographics(demographics);

  const deptMap = new Map(ruleData.departments.map((d) => [d.id, d.name]));
  const sevMap = new Map(
    ruleData.severity_levels.map((s) => [s.id, s.name])
  );

  for (const symptom of symptoms) {
    const checklist = source[symptom] ?? [];
    for (const item of checklist) {
      if (!item.auto_complete) continue;
      const val = enriched[item.auto_complete.field];
      if (val === undefined || val === null) continue;
      if (!compare(item.auto_complete.op, val, item.auto_complete.value))
        continue;

      // Auto-complete condition met — build termination result
      const { sevId, deptId } = resolveErItemIds(item, pediatric);
      return {
        type: "terminated",
        departments: [{ id: deptId, name: deptMap.get(deptId) ?? deptId }],
        severity: { id: sevId, name: sevMap.get(sevId) ?? sevId },
        reason:
          item.reason ??
          `ER checklist auto-complete: ${item.qid} (default response)`,
        fromPhase: 3,
      };
    }
  }

  return null;
}

/**
 * Get the ER checklist items for the given symptoms, filtered by age,
 * condition, and excluding auto_complete items.
 *
 * - ``auto_complete`` items are never shown (handled by checkErAutoComplete).
 * - ``condition`` items are shown only when the condition is met.
 */
export function getErChecklistItems(
  symptoms: string[],
  age: number | null,
  demographics: Record<string, unknown>,
  ruleData: SimulatorDataResponse
): Array<{
  qid: string;
  text: string;
  symptom: string;
  raw: Record<string, unknown>;
}> {
  const pediatric = age !== null && age < PEDIATRIC_AGE_THRESHOLD;
  const source = pediatric ? ruleData.er_pediatric : ruleData.er_adult;
  const enriched = enrichDemographics(demographics);
  const items: Array<{
    qid: string;
    text: string;
    symptom: string;
    raw: Record<string, unknown>;
  }> = [];

  for (const symptom of symptoms) {
    const checklist = source[symptom] ?? [];
    for (const item of checklist) {
      // auto_complete items are never shown to the user
      if (item.auto_complete) continue;
      // condition items: only shown when condition is met
      if (item.condition) {
        const val = enriched[item.condition.field];
        if (val === undefined || val === null) continue;
        if (!compare(item.condition.op, val, item.condition.value)) continue;
      }
      items.push({
        qid: item.qid,
        text: item.text,
        symptom,
        raw: item as unknown as Record<string, unknown>,
      });
    }
  }

  return items;
}

/**
 * Find the first positive ER checklist item and resolve its severity/department.
 * Returns a TerminationResult or null if all items are negative.
 */
export function resolveErChecklistTermination(
  flags: Record<string, boolean>,
  symptoms: string[],
  age: number | null,
  ruleData: SimulatorDataResponse
): TerminationResult | null {
  const pediatric = age !== null && age < PEDIATRIC_AGE_THRESHOLD;
  const source = pediatric ? ruleData.er_pediatric : ruleData.er_adult;

  const deptMap = new Map(ruleData.departments.map((d) => [d.id, d.name]));
  const sevMap = new Map(ruleData.severity_levels.map((s) => [s.id, s.name]));

  for (const symptom of symptoms) {
    const checklist = source[symptom] ?? [];
    for (const item of checklist) {
      if (flags[item.qid] !== true) continue;

      const { sevId, deptId } = resolveErItemIds(item, pediatric);

      return {
        type: "terminated",
        departments: [{ id: deptId, name: deptMap.get(deptId) ?? deptId }],
        severity: { id: sevId, name: sevMap.get(sevId) ?? sevId },
        reason: item.reason ?? `ER checklist positive: ${item.qid} (default response)`,
        fromPhase: 3,
      };
    }
  }

  return null;
}

/** Build urgency termination result (sev002_5 with optional departments) */
export function buildUrgencyTermination(
  departmentIds: string[],
  ruleData: SimulatorDataResponse,
  currentPhase: number
): TerminationResult {
  const deptMap = new Map(ruleData.departments.map((d) => [d.id, d.name]));
  const sevMap = new Map(
    ruleData.severity_levels.map((s) => [s.id, s.name])
  );

  return {
    type: "terminated",
    departments: departmentIds.map((id) => ({
      id,
      name: deptMap.get(id) ?? id,
    })),
    severity: {
      id: DEFAULT_URGENCY_SEVERITY,
      name: sevMap.get(DEFAULT_URGENCY_SEVERITY) ?? DEFAULT_URGENCY_SEVERITY,
    },
    reason: null,
    fromPhase: currentPhase,
  };
}

/** Build ER critical termination result (any positive → Emergency) */
export function buildErCriticalTermination(
  positiveQids: string[],
  ruleData: SimulatorDataResponse
): TerminationResult {
  const deptMap = new Map(ruleData.departments.map((d) => [d.id, d.name]));
  const sevMap = new Map(ruleData.severity_levels.map((s) => [s.id, s.name]));

  // Use custom reasons from YAML if available, else fall back to
  // auto-generated format with qid identifiers.
  const qidToItem = new Map(ruleData.er_critical.map((item) => [item.qid, item]));
  const customReasons = positiveQids
    .map((qid) => qidToItem.get(qid)?.reason)
    .filter((r): r is string => !!r);
  const reason =
    customReasons.length > 0
      ? customReasons.join("; ")
      : `ER critical positive: ${positiveQids.join(", ")} (default response)`;

  return {
    type: "terminated",
    departments: [
      {
        id: DEFAULT_ER_DEPARTMENT,
        name: deptMap.get(DEFAULT_ER_DEPARTMENT) ?? DEFAULT_ER_DEPARTMENT,
      },
    ],
    severity: {
      id: DEFAULT_ER_SEVERITY,
      name: sevMap.get(DEFAULT_ER_SEVERITY) ?? DEFAULT_ER_SEVERITY,
    },
    reason,
    fromPhase: 1,
  };
}

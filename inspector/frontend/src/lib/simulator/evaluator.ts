/**
 * Client-side port of Python ConditionalEvaluator.
 *
 * Resolves auto-evaluated question types (conditional, age_filter,
 * gender_filter) without showing them to the user. These are pure
 * functions — no React state involved.
 */

import type {
  RawAction,
  RawConditionalRule,
  RawOption,
  RawPredicate,
} from "../types/simulator";

// --- Gender filter ---

/**
 * Match patient gender against gender_filter option IDs/labels.
 * Returns the matched option's action, or null if no match.
 */
export function evalGenderFilter(
  options: RawOption[],
  gender: string
): RawAction | null {
  const genderLower = gender.toLowerCase().trim();
  for (const opt of options) {
    if (
      opt.id.toLowerCase() === genderLower ||
      (opt.label && opt.label.toLowerCase() === genderLower)
    ) {
      return opt.action ?? null;
    }
  }
  return null;
}

// --- Age filter ---

/**
 * Match patient age against age_filter option thresholds.
 *
 * Option IDs use the convention "{operator}_{threshold}":
 *   lt_15  → age < 15
 *   gte_15 → age >= 15
 *   le_5   → age <= 5
 *   gt_65  → age > 65
 *
 * Falls back to label-based parsing (e.g. "<15", ">=65") if the ID
 * convention doesn't match. If nothing matches, returns the last
 * option's action as a fallback (age filters are typically binary).
 */
export function evalAgeFilter(
  options: RawOption[],
  age: number | null
): RawAction | null {
  if (age === null || age === undefined) return null;

  for (const opt of options) {
    const optId = opt.id.toLowerCase();

    // Try structured ID: "lt_15", "gte_15", etc.
    const idMatch = optId.match(/^(lt|lte|le|gt|gte|ge)_(\d+(?:\.\d+)?)$/);
    if (idMatch) {
      const [, op, threshStr] = idMatch;
      const threshold = parseFloat(threshStr);
      let matched = false;
      if (op === "lt") matched = age < threshold;
      else if (op === "le" || op === "lte") matched = age <= threshold;
      else if (op === "gt") matched = age > threshold;
      else if (op === "ge" || op === "gte") matched = age >= threshold;

      if (matched) return opt.action ?? null;
      continue;
    }

    // Fallback: parse label like "<15", ">=65"
    const labelMatch = opt.label.trim().match(/^([<>]=?)\s*(\d+(?:\.\d+)?)$/);
    if (labelMatch) {
      const [, opStr, threshStr] = labelMatch;
      const threshold = parseFloat(threshStr);
      let matched = false;
      if (opStr === "<") matched = age < threshold;
      else if (opStr === "<=") matched = age <= threshold;
      else if (opStr === ">") matched = age > threshold;
      else if (opStr === ">=") matched = age >= threshold;

      if (matched) return opt.action ?? null;
    }
  }

  // Fallback: return last option (age filters are typically binary)
  if (options.length > 0) {
    return options[options.length - 1].action ?? null;
  }
  return null;
}

// --- Conditional rules ---

/**
 * Evaluate conditional rules in order; first match wins.
 * Each rule has a list of "when" predicates that are AND-ed together.
 * Falls back to defaultAction if no rule matches.
 */
export function evalConditional(
  rules: RawConditionalRule[],
  defaultAction: RawAction | undefined,
  answers: Record<string, unknown>
): RawAction | null {
  for (const rule of rules) {
    if (rule.when.every((pred) => evalPredicate(pred, answers))) {
      return rule.then;
    }
  }
  return defaultAction ?? null;
}

// --- Predicate evaluation ---

/**
 * Evaluate a single predicate against the answers dict.
 * If the referenced qid hasn't been answered, returns false.
 */
function evalPredicate(
  pred: RawPredicate,
  answers: Record<string, unknown>
): boolean {
  let answer = answers[pred.qid];
  if (answer === undefined || answer === null) return false;

  // Drill into sub-field for free_text_with_fields
  if (pred.field !== undefined && pred.field !== null) {
    if (typeof answer === "object" && !Array.isArray(answer)) {
      answer = (answer as Record<string, unknown>)[pred.field];
    } else {
      return false;
    }
  }

  return compare(pred.op, answer, pred.value);
}

// --- Comparison operators ---

/**
 * Apply a comparison operator between an answer and an expected value.
 * Handles type coercion for numeric comparisons.
 */
export function compare(op: string, answer: unknown, value: unknown): boolean {
  if (op === "eq") return answer === value;
  if (op === "ne") return answer !== value;

  // Numeric comparisons
  if (["lt", "le", "gt", "ge", "between"].includes(op)) {
    const ansNum = Number(answer);
    if (isNaN(ansNum)) return false;

    if (op === "lt") return ansNum < Number(value);
    if (op === "le") return ansNum <= Number(value);
    if (op === "gt") return ansNum > Number(value);
    if (op === "ge") return ansNum >= Number(value);
    if (op === "between") {
      // value is expected to be [min, max]
      const arr = value as [number, number];
      return ansNum >= Number(arr[0]) && ansNum <= Number(arr[1]);
    }
  }

  // Collection / string membership
  if (op === "contains") {
    if (Array.isArray(answer)) return answer.includes(value);
    return String(answer).includes(String(value));
  }
  if (op === "not_contains") {
    if (Array.isArray(answer)) return !answer.includes(value);
    return !String(answer).includes(String(value));
  }
  if (op === "contains_any") {
    const vals = value as unknown[];
    if (Array.isArray(answer)) return vals.some((v) => answer.includes(v));
    const ansStr = String(answer);
    return vals.some((v) => ansStr.includes(String(v)));
  }
  if (op === "contains_all") {
    const vals = value as unknown[];
    if (Array.isArray(answer)) return vals.every((v) => answer.includes(v));
    const ansStr = String(answer);
    return vals.every((v) => ansStr.includes(String(v)));
  }
  if (op === "matches") {
    return new RegExp(String(value)).test(String(answer));
  }

  return false;
}

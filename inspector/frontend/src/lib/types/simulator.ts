/**
 * Type definitions for the client-side prescreening simulator.
 *
 * These mirror the raw YAML data structures served by GET /api/simulator_data,
 * plus internal state types used by the useSimulator hook and engine.
 */

// --- Raw YAML data types (from API response) ---

/** A single option in a question (single_select, multi_select, etc.) */
export interface RawOption {
  id: string;
  label: string;
  action?: RawAction;
}

/** An action attached to an option or as on_submit/next/default */
export interface RawAction {
  action: "goto" | "opd" | "terminate";
  qid?: string[];
  metadata?: {
    department?: Array<{ id: string }>;
    severity?: Array<{ id: string }>;
    reason?: string;
  };
}

/** A predicate in a conditional rule's "when" clause */
export interface RawPredicate {
  qid: string;
  op: string;
  value: unknown;
  field?: string;
}

/** A single conditional rule (when/then pair) */
export interface RawConditionalRule {
  when: RawPredicate[];
  then: RawAction;
}

/** A sub-field definition for free_text_with_fields questions */
export interface RawField {
  id: string;
  label?: string;
  kind?: string;
}

/** A raw question as loaded from OLDCARTS/OPD YAML */
export interface RawQuestion {
  qid: string;
  question: string;
  question_type: string;
  options?: RawOption[];
  /** Action fired on submit for free_text / number_range types */
  on_submit?: RawAction;
  /** Action fired after multi_select submission */
  next?: RawAction;
  /** Conditional rules (for question_type === "conditional") */
  rules?: RawConditionalRule[];
  /** Default action for conditional questions */
  default?: RawAction;
  /** Sub-fields for free_text_with_fields */
  fields?: RawField[];
  /** Image path for image_single_select / image_multi_select */
  image?: string;
  /** Number range constraints */
  min_value?: number;
  max_value?: number;
  step?: number;
  default_value?: number;
}

/** A demographic field definition from demographic.yaml */
export interface RawDemographicField {
  qid: string;
  key: string;
  field_name: string;
  field_name_th: string;
  type: "datetime" | "enum" | "float" | "from_yaml" | "str";
  optional?: boolean;
  values?: unknown[] | string;
  values_path?: string;
}

/** An ER critical symptom check item */
export interface RawErCriticalItem {
  qid: string;
  text: string;
  reason?: string;
}

/** An ER checklist item (adult or pediatric) */
export interface RawErChecklistItem {
  qid: string;
  text: string;
  reason?: string;
  severity?: { id: string };
  min_severity?: { id: string };
  department?: Array<{ id: string }>;
}

/** A constant entry (department, severity level, or NHSO symptom) */
export interface ConstantEntry {
  id: string;
  name: string;
  name_th?: string;
}

/** Full response from GET /api/simulator_data */
export interface SimulatorDataResponse {
  demographic: RawDemographicField[];
  er_critical: RawErCriticalItem[];
  er_adult: Record<string, RawErChecklistItem[]>;
  er_pediatric: Record<string, RawErChecklistItem[]>;
  oldcarts: Record<string, RawQuestion[]>;
  opd: Record<string, RawQuestion[]>;
  nhso_symptoms: ConstantEntry[];
  severity_levels: ConstantEntry[];
  departments: ConstantEntry[];
}

// --- Simulator internal state types ---

/** The result shown when the simulation terminates */
export interface TerminationResult {
  type: "terminated" | "completed";
  departments: Array<{ id: string; name: string }>;
  severity: { id: string; name: string } | null;
  reason: string | null;
}

/** Text overrides for inline editing within the simulator */
export interface TextOverride {
  questionText?: string;
  optionLabels?: Record<string, string>;
}

/** A snapshot of simulator state for back-navigation history */
export interface HistoryEntry {
  phase: number;
  demographics: Record<string, unknown>;
  allAnswers: Record<string, unknown>;
  primarySymptom: string;
  secondarySymptoms: string[];
  erCriticalFlags: Record<string, boolean>;
  erChecklistFlags: Record<string, boolean>;
  pending: string[];
  currentQuestion: RawQuestion | null;
  /** Label describing what was answered at this step */
  label: string;
  /** The answer value submitted */
  answerValue: unknown;
}

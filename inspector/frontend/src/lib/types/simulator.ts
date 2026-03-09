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
  type: "int" | "float" | "date" | "enum" | "from_yaml" | "yes_no_detail" | "str" | "datetime";
  optional?: boolean;
  values?: unknown[] | string;
  values_path?: string;
  max_value?: number;
  /** Conditional visibility: field is shown only when this condition is met */
  condition?: {
    field: string;
    op: string;
    value: unknown;
  };
  /** Sub-fields for yes_no_detail when answer is true */
  detail_fields?: Array<{
    key: string;
    type: string;
    field_name_th?: string;
    /** Allowed values for enum-type sub-fields (e.g. drinking_frequency) */
    values?: string[];
  }>;
}

/** An ER critical symptom check item */
export interface RawErCriticalItem {
  qid: string;
  text: string;
  reason?: string;
  /** Optional condition controlling visibility based on demographics.
   *  When present, the item is only shown if the condition is satisfied. */
  condition?: {
    field: string;
    op: string;
    value: unknown;
  };
}

/** An ER checklist item (adult or pediatric) */
export interface RawErChecklistItem {
  qid: string;
  text: string;
  reason?: string;
  severity?: { id: string };
  min_severity?: { id: string };
  department?: Array<{ id: string }>;
  /** Optional condition controlling visibility based on demographics.
   *  When present, the item is only shown if the condition is satisfied. */
  condition?: {
    field: string;
    op: string;
    value: unknown;
  };
  /** Optional auto-complete condition — when met, the item is automatically
   *  answered as positive and triggers termination.  When not met, the item
   *  is hidden (the answer is definitively false). */
  auto_complete?: {
    field: string;
    op: string;
    value: unknown;
  };
}

/** A constant entry (department, severity level, or NHSO symptom) */
export interface ConstantEntry {
  id: string;
  name: string;
  name_th?: string;
}

/** A disease entry for DDx display */
export interface DiseaseEntry {
  id: string;
  disease_name: string;
  name_th: string;
}

/** Full response from GET /api/simulator_data */
export interface SimulatorDataResponse {
  demographic: RawDemographicField[];
  past_history: RawDemographicField[];
  personal_history: RawDemographicField[];
  er_critical: RawErCriticalItem[];
  er_adult: Record<string, RawErChecklistItem[]>;
  er_pediatric: Record<string, RawErChecklistItem[]>;
  oldcarts: Record<string, RawQuestion[]>;
  opd: Record<string, RawQuestion[]>;
  nhso_symptoms: ConstantEntry[];
  severity_levels: ConstantEntry[];
  departments: ConstantEntry[];
  diseases: DiseaseEntry[];
}

// --- Simulator internal state types ---

/** The result shown when the simulation terminates */
export interface TerminationResult {
  type: "terminated" | "completed";
  departments: Array<{ id: string; name: string }>;
  severity: { id: string; name: string } | null;
  reason: string | null;
  /** Which phase triggered the termination — used to decide whether to insert LLM phase */
  fromPhase?: number;
  /** Differential diagnosis from LLM prediction */
  diagnoses?: Array<{ disease_id: string }>;
  /** Whether prediction was attempted but LLM was unavailable */
  predictionUnavailable?: boolean;
  /** Error message when prediction was attempted but failed */
  predictionError?: string;
  /** Whether prediction returned successfully but with no diagnoses or severity (e.g. transient API error) */
  predictionEmpty?: boolean;
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
  /** Pending termination result when LLM phase is active */
  pendingResult: TerminationResult | null;
  /** Phase 5 past history data snapshot */
  pastHistoryData: Record<string, unknown>;
  /** Phase 6 personal history data snapshot */
  personalHistoryData: Record<string, unknown>;
  /** Label describing what was answered at this step */
  label: string;
  /** The answer value submitted */
  answerValue: unknown;
}

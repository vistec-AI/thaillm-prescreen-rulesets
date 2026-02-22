// ── API response types ──────────────────────────────────────────────

/** A single demographic field definition from demographic.yaml. */
export interface DemographicItem {
  qid: string;
  key: string;
  field_name: string;
  field_name_th: string;
  type: "datetime" | "enum" | "float" | "from_yaml" | "str";
  optional?: boolean;
  values?: unknown[] | string;
  /** Present when type=from_yaml; the original YAML path before resolution. */
  values_path?: string;
}

/** GET /api/demographic response. */
export interface DemographicResponse {
  items: DemographicItem[];
}

/** A single ER checklist item returned by GET /api/er_checklist. */
export interface ErChecklistItem {
  qid: string;
  text: string;
  has_override: boolean;
  severity: string;
  severity_label: string;
  department: string[];
  department_labels: string[];
  reason: string | null;
  raw: Record<string, unknown>;
  source: string;
}

/** GET /api/er_checklist response. */
export interface ErChecklistResponse {
  items: ErChecklistItem[];
  mode: string;
  symptom: string | null;
}

/** GET /api/er_symptoms response. */
export interface ErSymptomsResponse {
  adult: string[];
  pediatric: string[];
}

/** Cytoscape node data from GET /api/graph. */
export interface GraphNodeData {
  id: string;
  label: string;
  type?: string;
  source?: string;
  image?: string;
  min_value?: number;
  max_value?: number;
  step?: number;
  default_value?: number;
  fields?: Array<{ id: string; label?: string }>;
  options?: Array<{
    id?: string;
    label?: string;
    action?: { action: string; qid?: string[]; metadata?: Record<string, unknown> };
  }>;
  rules?: Array<{
    when?: Array<{ qid: string; op: string; value: unknown }>;
    then?: { action: string; qid?: string[]; metadata?: Record<string, unknown> };
  }>;
  default?: { action: string; qid?: string[]; metadata?: Record<string, unknown> };
  raw?: Record<string, unknown>;
}

/** GET /api/graph response. */
export interface GraphResponse {
  nodes: Array<{ data: GraphNodeData }>;
  edges: Array<{ data: { source: string; target: string; label?: string } }>;
}

/** GET /api/symptoms response. */
export interface SymptomsResponse {
  symptoms: string[];
}

/** GET /api/constants response. */
export interface ConstantsResponse {
  severity_levels: Array<{ id: string; name: string }>;
  departments: Array<{ id: string; name: string }>;
}

/** GET /api/version response. */
export interface VersionResponse {
  version: string;
  mtime: number;
}

/** Generic mutation result from POST endpoints. */
export interface MutationResult {
  ok: boolean;
  error?: string;
  field?: string;
  version?: VersionResponse;
  message?: string;
  stdout?: string;
  stderr?: string;
  rolled_back?: boolean;
  cmd?: string;
  returncode?: number;
}

/** GET /api/validate response. */
export interface ValidateResult {
  ok: boolean;
  stdout?: string;
  stderr?: string;
  cmd?: string;
  returncode?: number;
  timeout?: boolean;
}

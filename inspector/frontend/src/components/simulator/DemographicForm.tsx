"use client";

import { useState } from "react";
import type { RawDemographicField, TextOverride } from "@/lib/types/simulator";
import EditableText from "./EditableText";

/** Age mode for random profile generation */
type AgeMode = "adult" | "children";

/** Generate a random integer in [min, max] inclusive */
function randInt(min: number, max: number): number {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

/** Pick a random element from an array */
function randPick<T>(arr: T[]): T {
  return arr[randInt(0, arr.length - 1)];
}

/**
 * Evaluate a field's condition against a set of values.
 * Returns true if the field should be visible (no condition or condition met).
 */
function isFieldVisible(
  field: RawDemographicField,
  values: Record<string, unknown>
): boolean {
  if (!field.condition) return true;
  const { field: condField, op, value: condValue } = field.condition;
  const actualValue = values[condField];

  // For numeric comparisons, convert both sides to numbers
  if (["lt", "le", "gt", "ge"].includes(op)) {
    const numActual = Number(actualValue);
    const numExpected = Number(condValue);
    if (isNaN(numActual) || isNaN(numExpected)) return false;
    switch (op) {
      case "lt": return numActual < numExpected;
      case "le": return numActual <= numExpected;
      case "gt": return numActual > numExpected;
      case "ge": return numActual >= numExpected;
    }
  }

  // For equality checks, compare as strings to handle mixed types
  const strActual = String(actualValue ?? "");
  const strExpected = String(condValue ?? "");
  switch (op) {
    case "eq": return strActual === strExpected;
    case "ne": return strActual !== strExpected && strActual !== "";
    default: return true;
  }
}

/**
 * Build a random demographic profile for the given age mode.
 * Children: age 1-14, Adult: age 15-80.
 * Returns form values and multi-select values.
 */
function generateRandomProfile(
  fields: RawDemographicField[],
  mode: AgeMode,
) {
  // --- Core values determined first (used by conditional fields) ---
  const ageMin = mode === "children" ? 1 : 15;
  const ageMax = mode === "children" ? 14 : 80;
  const age = randInt(ageMin, ageMax);
  const gender = randPick(["Male", "Female"]);
  // Only relevant for Female; determines which pregnancy sub-fields appear
  const pregnancyStatus = gender === "Female"
    ? randPick(["pregnant", "not_pregnant"])
    : "";

  // --- Underlying diseases (from_yaml multi-select) ---
  const multiVals: Record<string, string[]> = {};
  for (const f of fields) {
    if (f.type === "from_yaml" && Array.isArray(f.values)) {
      const options = f.values as unknown[];
      const numPicks = mode === "children" ? randInt(0, 1) : randInt(0, 3);
      const shuffled = [...options].sort(() => Math.random() - 0.5);
      const picked = shuffled.slice(0, numPicks).map((opt) => {
        if (typeof opt === "object" && opt !== null && "name" in opt) {
          return (opt as { name: string }).name;
        }
        return String(opt);
      });
      multiVals[f.key] = picked;
    }
  }

  // --- Build values map for every field ---
  const vals: Record<string, unknown> = {};

  // Pre-populate lookup so conditional checks can reference already-decided values
  const lookup: Record<string, unknown> = {
    age: String(age),
    gender,
    pregnancy_status: pregnancyStatus,
  };

  for (const f of fields) {
    // Skip fields whose condition is not met
    if (f.condition && !isFieldVisible(f, lookup)) {
      vals[f.key] = f.type === "yes_no_detail"
        ? { answer: false, detail: null }
        : "";
      continue;
    }

    // Generate a value based on the field key and type
    switch (f.key) {
      case "age":
        vals[f.key] = String(age);
        break;
      case "age_months":
        // Only meaningful for children under 6
        vals[f.key] = age < 6 ? String(randInt(0, 11)) : "";
        break;
      case "gender":
        vals[f.key] = gender;
        break;
      case "pregnancy_status":
        vals[f.key] = pregnancyStatus;
        break;
      case "total_pregnancies":
        vals[f.key] = String(randInt(1, 5));
        break;
      case "fetuses_count":
        vals[f.key] = String(randInt(1, 2));
        break;
      case "gestational_age_weeks":
        vals[f.key] = String(randInt(4, f.max_value ?? 42));
        break;
      case "menstrual_duration_days":
        vals[f.key] = String(randInt(3, 7));
        break;
      case "menstrual_flow":
        vals[f.key] = randPick(["same", "more", "less"]);
        break;
      case "last_menstrual_period": {
        // Random date within the last 30 days (ISO format)
        const now = new Date();
        const lmp = new Date(now);
        lmp.setDate(lmp.getDate() - randInt(1, 30));
        vals[f.key] = lmp.toISOString().split("T")[0];
        break;
      }
      default:
        if (f.type === "yes_no_detail") {
          // ~20% chance of "yes" for a more interesting profile
          const answer = Math.random() < 0.2;
          vals[f.key] = { answer, detail: answer ? "Random detail" : null };
        } else if (f.type === "from_yaml") {
          vals[f.key] = "";
        } else if (f.type === "enum" && Array.isArray(f.values)) {
          vals[f.key] = randPick(f.values as string[]);
        } else {
          vals[f.key] = "";
        }
    }
  }

  return { vals, multiVals };
}

interface DemographicFormProps {
  fields: RawDemographicField[];
  onSubmit: (value: Record<string, unknown>) => void;
  textOverrides?: Record<string, TextOverride>;
  onOverrideText?: (qid: string, text: string) => void;
  /** Custom heading — defaults to "ข้อมูลผู้ป่วย" (Patient Info) */
  title?: string;
  /** External values from earlier phases for condition evaluation
   *  (e.g. phase 5 fields check `age` from phase 0 demographics) */
  externalValues?: Record<string, unknown>;
  /** Whether to show the Adult/Children toggle + Random button (default true) */
  showRandomFill?: boolean;
}

/**
 * Bulk form for demographic-style fields (phases 0, 5, 6).
 * Supports conditional visibility, yes_no_detail with detail_fields sub-structure,
 * and optional random profile generation.
 */
export default function DemographicForm({
  fields,
  onSubmit,
  textOverrides = {},
  onOverrideText,
  title = "ข้อมูลผู้ป่วย",
  externalValues = {},
  showRandomFill = true,
}: DemographicFormProps) {
  // Initialize form values: each field keyed by its "key" property
  const [values, setValues] = useState<Record<string, unknown>>(() => {
    const init: Record<string, unknown> = {};
    for (const f of fields) {
      if (f.type === "yes_no_detail") {
        init[f.key] = { answer: false, detail: null };
      } else {
        init[f.key] = "";
      }
    }
    return init;
  });

  // For from_yaml multi-select fields (like underlying_diseases)
  const [multiValues, setMultiValues] = useState<Record<string, string[]>>({});

  // Validation errors keyed by field key
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

  // Age mode for random profile generation
  const [ageMode, setAgeMode] = useState<AgeMode>("adult");

  /** Fill the form with a randomly generated profile */
  const handleRandomFill = () => {
    const { vals, multiVals } = generateRandomProfile(fields, ageMode);
    setValues(vals);
    setMultiValues(multiVals);
    setValidationErrors({});
  };

  const handleChange = (key: string, val: unknown) => {
    setValues((prev) => ({ ...prev, [key]: val }));
    // Clear validation error when user starts filling in the field
    if (val !== "" && val !== null) {
      setValidationErrors((prev) => {
        if (!(key in prev)) return prev;
        const next = { ...prev };
        delete next[key];
        return next;
      });
    }
  };

  const handleMultiToggle = (key: string, item: string) => {
    setMultiValues((prev) => {
      const current = prev[key] ?? [];
      const next = current.includes(item)
        ? current.filter((v) => v !== item)
        : [...current, item];
      return { ...prev, [key]: next };
    });
  };

  /** Merge externalValues (from earlier phases) with local form values
   *  so that condition checks can reference fields from prior phases
   *  (e.g. past_history fields checking `age` from demographics). */
  const combinedValues = { ...externalValues, ...values };

  const handleSubmit = () => {
    // Validate required fields (those without optional: true and currently visible)
    const errors: Record<string, string> = {};
    for (const f of fields) {
      if (f.optional) continue;
      if (!isFieldVisible(f, combinedValues)) continue;
      // from_yaml multi-select and yes_no_detail fields are never strictly required
      if (f.type === "from_yaml" && Array.isArray(f.values)) continue;
      if (f.type === "yes_no_detail") continue;
      const v = values[f.key];
      if (v === "" || v === null || v === undefined) {
        errors[f.key] = "This field is required";
      }
    }
    if (Object.keys(errors).length > 0) {
      setValidationErrors(errors);
      return;
    }
    setValidationErrors({});

    // Build the final demographics object (only visible fields)
    const result: Record<string, unknown> = {};
    for (const f of fields) {
      if (!isFieldVisible(f, combinedValues)) continue;

      if (f.type === "from_yaml" && Array.isArray(f.values)) {
        result[f.key] = multiValues[f.key] ?? [];
      } else if (f.type === "int") {
        const v = values[f.key];
        result[f.key] = v !== "" && v !== null && v !== undefined ? Number(v) : null;
      } else if (f.type === "float") {
        const v = values[f.key];
        result[f.key] = v !== "" ? Number(v) : null;
      } else if (f.type === "yes_no_detail") {
        result[f.key] = values[f.key];
      } else {
        result[f.key] = values[f.key] || null;
      }
    }
    onSubmit(result);
  };

  /** Render a label with a red asterisk if the field is required */
  const renderLabel = (field: RawDemographicField, displayLabel: string) => {
    // from_yaml multi-select and yes_no_detail fields are never strictly required
    const isRequired =
      !field.optional &&
      !(field.type === "from_yaml" && Array.isArray(field.values)) &&
      field.type !== "yes_no_detail";
    return (
      <div className="flex items-baseline gap-0.5">
        {onOverrideText ? (
          <EditableText
            text={displayLabel}
            onSave={(t) => onOverrideText(field.qid, t)}
            as="label"
            className="text-sm font-medium text-gray-700"
          />
        ) : (
          <label className="text-sm font-medium text-gray-700">{displayLabel}</label>
        )}
        {isRequired && <span className="text-red-500 text-sm">*</span>}
      </div>
    );
  };

  const renderField = (field: RawDemographicField) => {
    // Skip fields whose condition is not met (check against combined values
    // so conditions referencing fields from earlier phases work correctly)
    if (!isFieldVisible(field, combinedValues)) return null;

    const displayLabel =
      textOverrides[field.qid]?.questionText ?? field.field_name_th;
    const hasError = !!validationErrors[field.key];
    const borderCls = hasError ? "border-red-400 bg-red-50" : "border-gray-300";

    // --- Integer input (age, counts, etc.) ---
    if (field.type === "int") {
      return (
        <div key={field.qid} className="flex flex-col gap-1">
          {renderLabel(field, displayLabel)}
          <span className="text-xs text-gray-400 mobile-hide">{field.field_name}</span>
          <input
            type="number"
            step="1"
            min="0"
            max={field.max_value ?? undefined}
            value={String(values[field.key] ?? "")}
            onChange={(e) => handleChange(field.key, e.target.value)}
            className={`border rounded px-2 py-1.5 text-sm ${borderCls}`}
          />
          {hasError && (
            <span className="text-xs text-red-500">{validationErrors[field.key]}</span>
          )}
        </div>
      );
    }

    // --- Date input (e.g. last menstrual period) ---
    if (field.type === "date") {
      return (
        <div key={field.qid} className="flex flex-col gap-1">
          {renderLabel(field, displayLabel)}
          <span className="text-xs text-gray-400 mobile-hide">{field.field_name}</span>
          <input
            type="date"
            value={String(values[field.key] ?? "")}
            onChange={(e) => handleChange(field.key, e.target.value)}
            className={`border rounded px-2 py-1.5 text-sm ${borderCls}`}
          />
          {hasError && (
            <span className="text-xs text-red-500">{validationErrors[field.key]}</span>
          )}
        </div>
      );
    }

    // --- Enum dropdown ---
    if (field.type === "enum") {
      const options = Array.isArray(field.values) ? field.values : [];
      return (
        <div key={field.qid} className="flex flex-col gap-1">
          {renderLabel(field, displayLabel)}
          <span className="text-xs text-gray-400 mobile-hide">{field.field_name}</span>
          <select
            value={String(values[field.key] ?? "")}
            onChange={(e) => handleChange(field.key, e.target.value)}
            className={`border rounded px-2 py-1.5 text-sm ${borderCls}`}
          >
            <option value="">-- เลือก --</option>
            {options.map((opt) => (
              <option key={String(opt)} value={String(opt)}>
                {String(opt)}
              </option>
            ))}
          </select>
          {hasError && (
            <span className="text-xs text-red-500">{validationErrors[field.key]}</span>
          )}
        </div>
      );
    }

    // --- Float input ---
    if (field.type === "float") {
      return (
        <div key={field.qid} className="flex flex-col gap-1">
          {renderLabel(field, displayLabel)}
          <span className="text-xs text-gray-400 mobile-hide">{field.field_name}</span>
          <input
            type="number"
            step="any"
            value={String(values[field.key] ?? "")}
            onChange={(e) => handleChange(field.key, e.target.value)}
            className={`border rounded px-2 py-1.5 text-sm ${borderCls}`}
          />
          {hasError && (
            <span className="text-xs text-red-500">{validationErrors[field.key]}</span>
          )}
        </div>
      );
    }

    // --- Yes/No with optional detail text or detail_fields sub-structure ---
    if (field.type === "yes_no_detail") {
      const ynd = values[field.key] as Record<string, unknown> | undefined;
      const answer = (ynd?.answer as boolean) ?? false;
      const detail = (ynd?.detail as string) ?? "";

      /** Update a sub-field value within the yes_no_detail object */
      const handleSubFieldChange = (subKey: string, subVal: unknown) => {
        handleChange(field.key, { ...ynd, answer: true, [subKey]: subVal });
      };

      return (
        <div key={field.qid} className="flex flex-col gap-1">
          {renderLabel(field, displayLabel)}
          <span className="text-xs text-gray-400 mobile-hide">{field.field_name}</span>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-1.5 text-sm cursor-pointer">
              <input
                type="radio"
                name={field.key}
                checked={!answer}
                onChange={() => handleChange(field.key, { answer: false, detail: null })}
              />
              ไม่มี
            </label>
            <label className="flex items-center gap-1.5 text-sm cursor-pointer">
              <input
                type="radio"
                name={field.key}
                checked={answer}
                onChange={() => handleChange(field.key, { answer: true, detail: "" })}
              />
              มี
            </label>
          </div>
          {/* When answer is true: render detail_fields sub-structure if defined,
              otherwise fall back to a single text input */}
          {answer && field.detail_fields && field.detail_fields.length > 0 ? (
            <div className="ml-4 space-y-2 border-l-2 border-blue-200 pl-3">
              {field.detail_fields.map((sf) => (
                <div key={sf.key} className="flex flex-col gap-0.5">
                  <label className="text-xs font-medium text-gray-600">
                    {sf.field_name_th ?? sf.key}
                  </label>
                  {sf.type === "int" && (
                    <input
                      type="number"
                      step="1"
                      min="0"
                      value={String(ynd?.[sf.key] ?? "")}
                      onChange={(e) => handleSubFieldChange(sf.key, e.target.value)}
                      className="border rounded px-2 py-1 text-sm border-gray-300 w-40"
                    />
                  )}
                  {sf.type === "enum" && (
                    <select
                      value={String(ynd?.[sf.key] ?? "")}
                      onChange={(e) => handleSubFieldChange(sf.key, e.target.value)}
                      className="border rounded px-2 py-1 text-sm border-gray-300 w-56"
                    >
                      <option value="">-- เลือก --</option>
                      {(sf.values ?? []).map((v) => (
                        <option key={v} value={v}>{v}</option>
                      ))}
                    </select>
                  )}
                  {sf.type === "str" && (
                    <input
                      type="text"
                      value={String(ynd?.[sf.key] ?? "")}
                      onChange={(e) => handleSubFieldChange(sf.key, e.target.value)}
                      className="border rounded px-2 py-1 text-sm border-gray-300"
                    />
                  )}
                </div>
              ))}
            </div>
          ) : answer ? (
            <input
              type="text"
              placeholder="รายละเอียด..."
              value={detail}
              onChange={(e) =>
                handleChange(field.key, { answer: true, detail: e.target.value || null })
              }
              className="border rounded px-2 py-1.5 text-sm border-gray-300"
            />
          ) : null}
        </div>
      );
    }

    // --- Multi-select checkboxes (from_yaml, e.g. underlying diseases) ---
    if (field.type === "from_yaml" && Array.isArray(field.values)) {
      const options = field.values as unknown[];
      const selected = multiValues[field.key] ?? [];

      /** Extract a stable key from a from_yaml value (object with "name" or plain string) */
      const optionKey = (opt: unknown): string => {
        if (typeof opt === "object" && opt !== null && "name" in opt) {
          return (opt as { name: string }).name;
        }
        return String(opt);
      };

      /** Display label -- prefer name_th (Thai) with English fallback */
      const optionLabel = (opt: unknown): string => {
        if (typeof opt === "object" && opt !== null) {
          const o = opt as Record<string, unknown>;
          const th = o.name_th ? String(o.name_th) : "";
          const en = o.name ? String(o.name) : "";
          return th ? `${th} (${en})` : en || String(opt);
        }
        return String(opt);
      };

      return (
        <div key={field.qid} className="flex flex-col gap-1">
          {renderLabel(field, displayLabel)}
          <span className="text-xs text-gray-400 mobile-hide">{field.field_name}</span>
          <div className="max-h-32 overflow-y-auto border border-gray-300 rounded p-2 space-y-1">
            {options.map((opt) => {
              const key = optionKey(opt);
              const label = optionLabel(opt);
              return (
                <label key={key} className="flex items-center gap-2 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selected.includes(key)}
                    onChange={() => handleMultiToggle(field.key, key)}
                    className="rounded"
                  />
                  {label}
                </label>
              );
            })}
          </div>
        </div>
      );
    }

    // --- Default: text input ---
    return (
      <div key={field.qid} className="flex flex-col gap-1">
        {renderLabel(field, displayLabel)}
        <span className="text-xs text-gray-400 mobile-hide">{field.field_name}</span>
        <input
          type="text"
          value={String(values[field.key] ?? "")}
          onChange={(e) => handleChange(field.key, e.target.value)}
          className={`border rounded px-2 py-1.5 text-sm ${borderCls}`}
        />
        {hasError && (
          <span className="text-xs text-red-500">{validationErrors[field.key]}</span>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h3 className="text-lg font-semibold text-gray-800">{title}</h3>
        {showRandomFill && (
          <div className="flex items-center gap-2">
            <div className="flex rounded-md overflow-hidden border border-gray-300 text-xs">
              <button
                type="button"
                onClick={() => setAgeMode("adult")}
                className={`px-3 py-1.5 transition-colors ${
                  ageMode === "adult"
                    ? "bg-blue-500 text-white"
                    : "bg-white text-gray-600 hover:bg-gray-50"
                }`}
              >
                Adult
              </button>
              <button
                type="button"
                onClick={() => setAgeMode("children")}
                className={`px-3 py-1.5 transition-colors ${
                  ageMode === "children"
                    ? "bg-blue-500 text-white"
                    : "bg-white text-gray-600 hover:bg-gray-50"
                }`}
              >
                Children
              </button>
            </div>
            <button
              type="button"
              onClick={handleRandomFill}
              className="bg-gray-100 hover:bg-gray-200 text-gray-700 px-3 py-1.5 rounded text-xs font-medium transition-colors border border-gray-300"
            >
              Random
            </button>
          </div>
        )}
      </div>
      <p className="text-xs text-gray-400">
        <span className="text-red-500">*</span> จำเป็นต้องกรอก
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {fields.map(renderField)}
      </div>
      <div className="sticky-submit">
        <button
          onClick={handleSubmit}
          className="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors text-sm font-medium"
        >
          ถัดไป
        </button>
      </div>
    </div>
  );
}

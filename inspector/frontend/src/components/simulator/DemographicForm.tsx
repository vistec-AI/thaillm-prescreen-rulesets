"use client";

import { useState } from "react";
import type { RawDemographicField, TextOverride } from "@/lib/types/simulator";
import EditableText from "./EditableText";

/** Buddhist Era offset: BE year = AD year + 543 */
const BE_OFFSET = 543;

/** Thai month names for the DOB dropdown */
const THAI_MONTHS = [
  "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน",
  "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม",
  "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
];

interface DemographicFormProps {
  fields: RawDemographicField[];
  onSubmit: (value: Record<string, unknown>) => void;
  textOverrides: Record<string, TextOverride>;
  onOverrideText: (qid: string, text: string) => void;
}

/**
 * Phase 0 form: collects all demographic fields (DOB, gender, height, weight, etc.)
 */
export default function DemographicForm({
  fields,
  onSubmit,
  textOverrides,
  onOverrideText,
}: DemographicFormProps) {
  // Initialize form values: each field keyed by its "key" property
  const [values, setValues] = useState<Record<string, unknown>>(() => {
    const init: Record<string, unknown> = {};
    for (const f of fields) {
      if (f.type === "datetime") init[f.key] = "";
      else if (f.type === "float") init[f.key] = "";
      else if (f.type === "enum" || f.type === "from_yaml") init[f.key] = "";
      else init[f.key] = "";
    }
    return init;
  });

  // Separate state for the 3-part BE date selector (day, month, year in BE)
  const [dobParts, setDobParts] = useState({ day: "", month: "", year: "" });

  // For from_yaml multi-select fields (like underlying_diseases)
  const [multiValues, setMultiValues] = useState<Record<string, string[]>>({});

  // Validation errors keyed by field key
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

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

  /**
   * Update one part of the BE date (day/month/year) and sync to the
   * main values store as an ISO AD date string for the engine.
   */
  const handleDobPartChange = (
    key: string,
    part: "day" | "month" | "year",
    val: string
  ) => {
    const next = { ...dobParts, [part]: val };
    setDobParts(next);

    // Build ISO date string (AD) only when all three parts are filled
    if (next.day && next.month && next.year) {
      const adYear = Number(next.year) - BE_OFFSET;
      const isoDate = `${adYear}-${next.month.padStart(2, "0")}-${next.day.padStart(2, "0")}`;
      handleChange(key, isoDate);
    } else {
      // Partial — clear the value so validation catches it
      handleChange(key, "");
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

  const handleSubmit = () => {
    // Validate required fields (those without optional: true)
    const errors: Record<string, string> = {};
    for (const f of fields) {
      if (f.optional) continue;
      // from_yaml multi-select fields are never strictly required
      if (f.type === "from_yaml" && Array.isArray(f.values)) continue;
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

    // Build the final demographics object
    const result: Record<string, unknown> = {};
    for (const f of fields) {
      if (f.key === "underlying_diseases" || (f.type === "from_yaml" && Array.isArray(f.values))) {
        result[f.key] = multiValues[f.key] ?? [];
      } else if (f.type === "float") {
        const v = values[f.key];
        result[f.key] = v !== "" ? Number(v) : null;
      } else {
        result[f.key] = values[f.key] || null;
      }
    }
    onSubmit(result);
  };

  const renderField = (field: RawDemographicField) => {
    const displayLabel =
      textOverrides[field.qid]?.questionText ?? field.field_name_th;

    if (field.type === "datetime") {
      // Manual BE (พ.ศ.) date selector: 3 dropdowns for day / month / year
      const currentBeYear = new Date().getFullYear() + BE_OFFSET;
      const hasError = !!validationErrors[field.key];
      const borderCls = hasError ? "border-red-400 bg-red-50" : "border-gray-300";

      return (
        <div key={field.qid} className="flex flex-col gap-1">
          <EditableText
            text={displayLabel}
            onSave={(t) => onOverrideText(field.qid, t)}
            as="label"
            className="text-sm font-medium text-gray-700"
          />
          <span className="text-xs text-gray-400">{field.field_name}</span>
          <div className="flex gap-2">
            {/* Day */}
            <select
              value={dobParts.day}
              onChange={(e) => handleDobPartChange(field.key, "day", e.target.value)}
              className={`border rounded px-2 py-1.5 text-sm flex-1 ${borderCls}`}
            >
              <option value="">วัน</option>
              {Array.from({ length: 31 }, (_, i) => i + 1).map((d) => (
                <option key={d} value={String(d)}>{d}</option>
              ))}
            </select>
            {/* Month */}
            <select
              value={dobParts.month}
              onChange={(e) => handleDobPartChange(field.key, "month", e.target.value)}
              className={`border rounded px-2 py-1.5 text-sm flex-[2] ${borderCls}`}
            >
              <option value="">เดือน</option>
              {THAI_MONTHS.map((name, i) => (
                <option key={i + 1} value={String(i + 1)}>{name}</option>
              ))}
            </select>
            {/* Year (BE) — range: current BE year down to 100 years ago */}
            <select
              value={dobParts.year}
              onChange={(e) => handleDobPartChange(field.key, "year", e.target.value)}
              className={`border rounded px-2 py-1.5 text-sm flex-1 ${borderCls}`}
            >
              <option value="">พ.ศ.</option>
              {Array.from({ length: 101 }, (_, i) => currentBeYear - i).map((y) => (
                <option key={y} value={String(y)}>{y}</option>
              ))}
            </select>
          </div>
          {hasError && (
            <span className="text-xs text-red-500">{validationErrors[field.key]}</span>
          )}
        </div>
      );
    }

    if (field.type === "enum") {
      const options = Array.isArray(field.values) ? field.values : [];
      return (
        <div key={field.qid} className="flex flex-col gap-1">
          <EditableText
            text={displayLabel}
            onSave={(t) => onOverrideText(field.qid, t)}
            as="label"
            className="text-sm font-medium text-gray-700"
          />
          <span className="text-xs text-gray-400">{field.field_name}</span>
          <select
            value={String(values[field.key] ?? "")}
            onChange={(e) => handleChange(field.key, e.target.value)}
            className={`border rounded px-2 py-1.5 text-sm ${
              validationErrors[field.key]
                ? "border-red-400 bg-red-50"
                : "border-gray-300"
            }`}
          >
            <option value="">-- Select --</option>
            {options.map((opt) => (
              <option key={String(opt)} value={String(opt)}>
                {String(opt)}
              </option>
            ))}
          </select>
          {validationErrors[field.key] && (
            <span className="text-xs text-red-500">{validationErrors[field.key]}</span>
          )}
        </div>
      );
    }

    if (field.type === "float") {
      return (
        <div key={field.qid} className="flex flex-col gap-1">
          <EditableText
            text={displayLabel}
            onSave={(t) => onOverrideText(field.qid, t)}
            as="label"
            className="text-sm font-medium text-gray-700"
          />
          <span className="text-xs text-gray-400">{field.field_name}</span>
          <input
            type="number"
            step="any"
            value={String(values[field.key] ?? "")}
            onChange={(e) => handleChange(field.key, e.target.value)}
            className={`border rounded px-2 py-1.5 text-sm ${
              validationErrors[field.key]
                ? "border-red-400 bg-red-50"
                : "border-gray-300"
            }`}
          />
          {validationErrors[field.key] && (
            <span className="text-xs text-red-500">{validationErrors[field.key]}</span>
          )}
        </div>
      );
    }

    if (field.type === "from_yaml" && Array.isArray(field.values)) {
      // Multi-select checkboxes (e.g., underlying diseases).
      // Values may be objects like {name, name_th} or plain strings.
      const options = field.values as unknown[];
      const selected = multiValues[field.key] ?? [];

      /** Extract a stable key from a from_yaml value (object with "name" or plain string) */
      const optionKey = (opt: unknown): string => {
        if (typeof opt === "object" && opt !== null && "name" in opt) {
          return (opt as { name: string }).name;
        }
        return String(opt);
      };

      /** Display label — prefer name_th (Thai) with English fallback */
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
          <EditableText
            text={displayLabel}
            onSave={(t) => onOverrideText(field.qid, t)}
            as="label"
            className="text-sm font-medium text-gray-700"
          />
          <span className="text-xs text-gray-400">{field.field_name}</span>
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

    // Default: text input
    return (
      <div key={field.qid} className="flex flex-col gap-1">
        <EditableText
          text={displayLabel}
          onSave={(t) => onOverrideText(field.qid, t)}
          as="label"
          className="text-sm font-medium text-gray-700"
        />
        <span className="text-xs text-gray-400">{field.field_name}</span>
        <input
          type="text"
          value={String(values[field.key] ?? "")}
          onChange={(e) => handleChange(field.key, e.target.value)}
          className={`border rounded px-2 py-1.5 text-sm ${
            validationErrors[field.key]
              ? "border-red-400 bg-red-50"
              : "border-gray-300"
          }`}
        />
        {validationErrors[field.key] && (
          <span className="text-xs text-red-500">{validationErrors[field.key]}</span>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-800">Demographics</h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {fields.map(renderField)}
      </div>
      <button
        onClick={handleSubmit}
        className="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors text-sm font-medium"
      >
        Next
      </button>
    </div>
  );
}

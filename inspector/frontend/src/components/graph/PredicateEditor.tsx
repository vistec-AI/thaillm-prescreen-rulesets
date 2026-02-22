"use client";

import { useState } from "react";

/** Shape of a single predicate in a conditional rule's `when` array. */
export interface PredicateObj {
  qid: string;
  field?: string;
  op: string;
  value: unknown;
}

/** All supported comparison operators for conditional rules. */
const ALL_OPERATORS = [
  "eq",
  "ne",
  "lt",
  "le",
  "gt",
  "ge",
  "between",
  "contains",
  "not_contains",
  "contains_any",
  "contains_all",
  "matches",
] as const;

/** Operators that take a single text value. */
const TEXT_OPS = new Set(["eq", "ne", "contains", "not_contains", "matches"]);
/** Operators that take a single number value. */
const NUMBER_OPS = new Set(["lt", "le", "gt", "ge"]);
/** Operators that take an array of text values. */
const ARRAY_OPS = new Set(["contains_any", "contains_all"]);

interface Props {
  value: PredicateObj;
  onChange: (updated: PredicateObj) => void;
  onRemove: () => void;
  disabled?: boolean;
}

/**
 * Edits a single predicate `{qid, field?, op, value}`.
 *
 * The value input changes dynamically based on the selected operator:
 * - Text ops → text input
 * - Number ops → number input
 * - between → two number inputs [min, max]
 * - Array ops → list of text inputs (each value gets its own input to avoid
 *   splitting Thai medical terms on commas)
 */
export default function PredicateEditor({ value, onChange, onRemove, disabled }: Props) {
  // Whether the optional `field` sub-property input is visible.
  // Auto-show if the predicate already has a field value.
  const [showField, setShowField] = useState(!!value.field);

  /** Produce a type-appropriate default value when the operator changes. */
  const defaultValueForOp = (op: string): unknown => {
    if (TEXT_OPS.has(op)) return "";
    if (NUMBER_OPS.has(op)) return 0;
    if (op === "between") return [0, 0];
    if (ARRAY_OPS.has(op)) return [];
    return "";
  };

  const handleOpChange = (newOp: string) => {
    // Reset value to match the new operator's expected type
    onChange({ ...value, op: newOp, value: defaultValueForOp(newOp) });
  };

  // --- Array value helpers (for contains_any / contains_all) ---

  const arrayValues = Array.isArray(value.value) ? (value.value as string[]) : [];

  const updateArrayItem = (index: number, text: string) => {
    const updated = arrayValues.map((v, i) => (i === index ? text : v));
    onChange({ ...value, value: updated });
  };

  const addArrayItem = () => {
    onChange({ ...value, value: [...arrayValues, ""] });
  };

  const removeArrayItem = (index: number) => {
    onChange({ ...value, value: arrayValues.filter((_, i) => i !== index) });
  };

  // --- Between value helpers ---

  const betweenValues: [number, number] = Array.isArray(value.value)
    ? [Number(value.value[0]) || 0, Number(value.value[1]) || 0]
    : [0, 0];

  // --- Render the value input based on operator type ---

  const renderValueInput = () => {
    const op = value.op;

    if (TEXT_OPS.has(op)) {
      return (
        <input
          type="text"
          className="w-full border border-gray-200 rounded px-2 py-0.5 text-sm"
          value={String(value.value ?? "")}
          onChange={(e) => onChange({ ...value, value: e.target.value })}
          disabled={disabled}
          placeholder="value"
        />
      );
    }

    if (NUMBER_OPS.has(op)) {
      return (
        <input
          type="number"
          className="w-full border border-gray-200 rounded px-2 py-0.5 text-sm"
          value={value.value as number ?? ""}
          onChange={(e) => onChange({ ...value, value: Number(e.target.value) })}
          disabled={disabled}
          placeholder="0"
        />
      );
    }

    if (op === "between") {
      return (
        <div className="flex gap-1 items-center">
          <input
            type="number"
            className="flex-1 border border-gray-200 rounded px-2 py-0.5 text-sm"
            value={betweenValues[0]}
            onChange={(e) =>
              onChange({ ...value, value: [Number(e.target.value), betweenValues[1]] })
            }
            disabled={disabled}
            placeholder="min"
          />
          <span className="text-xs text-gray-400">–</span>
          <input
            type="number"
            className="flex-1 border border-gray-200 rounded px-2 py-0.5 text-sm"
            value={betweenValues[1]}
            onChange={(e) =>
              onChange({ ...value, value: [betweenValues[0], Number(e.target.value)] })
            }
            disabled={disabled}
            placeholder="max"
          />
        </div>
      );
    }

    if (ARRAY_OPS.has(op)) {
      // Each value gets its own text input — Thai medical terms must not be
      // split by commas, so we use individual inputs like DemographicEditor
      // does for enum values.
      return (
        <div className="space-y-1">
          {arrayValues.map((item, i) => (
            <div key={i} className="flex gap-1">
              <input
                type="text"
                className="flex-1 border border-gray-200 rounded px-2 py-0.5 text-sm"
                value={item}
                onChange={(e) => updateArrayItem(i, e.target.value)}
                disabled={disabled}
                placeholder={`Value ${i + 1}`}
              />
              <button
                type="button"
                className="px-1.5 text-red-500 hover:text-red-700 text-sm disabled:opacity-50"
                onClick={() => removeArrayItem(i)}
                disabled={disabled}
                title="Remove value"
              >
                &times;
              </button>
            </div>
          ))}
          <button
            type="button"
            className="px-2 py-0.5 text-xs bg-gray-100 rounded hover:bg-gray-200 disabled:opacity-50"
            onClick={addArrayItem}
            disabled={disabled}
          >
            + Add value
          </button>
        </div>
      );
    }

    // Fallback: plain text input
    return (
      <input
        type="text"
        className="w-full border border-gray-200 rounded px-2 py-0.5 text-sm"
        value={String(value.value ?? "")}
        onChange={(e) => onChange({ ...value, value: e.target.value })}
        disabled={disabled}
        placeholder="value"
      />
    );
  };

  return (
    <div className="border border-gray-200 rounded p-1.5 bg-white space-y-1">
      {/* Row 1: QID + remove button */}
      <div className="flex items-start gap-1">
        <div className="flex-1">
          <label className="text-[11px] text-gray-500 block mb-0.5">QID</label>
          <input
            type="text"
            className="w-full border border-gray-200 rounded px-2 py-0.5 text-xs font-mono"
            value={value.qid}
            onChange={(e) => onChange({ ...value, qid: e.target.value })}
            disabled={disabled}
            placeholder="question_id"
          />
        </div>
        <button
          type="button"
          className="text-red-400 hover:text-red-600 text-sm px-1 pt-4 disabled:opacity-30"
          onClick={onRemove}
          disabled={disabled}
          title="Remove condition"
        >
          &times;
        </button>
      </div>

      {/* Optional field sub-property (hidden by default, rarely used) */}
      {showField ? (
        <div>
          <label className="text-[11px] text-gray-500 block mb-0.5">Field</label>
          <input
            type="text"
            className="w-full border border-gray-200 rounded px-2 py-0.5 text-xs font-mono"
            value={value.field || ""}
            onChange={(e) =>
              onChange({ ...value, field: e.target.value || undefined })
            }
            disabled={disabled}
            placeholder="sub-field"
          />
        </div>
      ) : (
        <button
          type="button"
          className="text-[11px] text-blue-500 hover:text-blue-700 disabled:opacity-50"
          onClick={() => setShowField(true)}
          disabled={disabled}
        >
          + sub-field
        </button>
      )}

      {/* Operator dropdown */}
      <div>
        <label className="text-[11px] text-gray-500 block mb-0.5">Operator</label>
        <select
          className="w-full border border-gray-300 rounded px-2 py-0.5 text-xs"
          value={value.op}
          onChange={(e) => handleOpChange(e.target.value)}
          disabled={disabled}
        >
          {ALL_OPERATORS.map((op) => (
            <option key={op} value={op}>{op}</option>
          ))}
          {/* If current op is not in the list, still show it */}
          {!(ALL_OPERATORS as readonly string[]).includes(value.op) && (
            <option value={value.op}>{value.op}</option>
          )}
        </select>
      </div>

      {/* Value input — shape depends on operator */}
      <div>
        <label className="text-[11px] text-gray-500 block mb-0.5">Value</label>
        {renderValueInput()}
      </div>
    </div>
  );
}

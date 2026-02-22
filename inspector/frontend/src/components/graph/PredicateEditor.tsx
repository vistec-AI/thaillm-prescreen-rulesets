"use client";

import { useState, useMemo } from "react";
import QidPicker, { type QidOption } from "./QidPicker";

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

// --- Recommended operators by question type ---
// Shown first in the operator dropdown when the referenced question's type is known.
const RECOMMENDED_OPS: Record<string, string[]> = {
  single_select: ["eq", "ne"],
  image_single_select: ["eq", "ne"],
  gender_filter: ["eq", "ne"],
  age_filter: ["eq", "ne"],
  multi_select: ["contains_any", "contains_all", "contains", "not_contains"],
  image_multi_select: ["contains_any", "contains_all", "contains", "not_contains"],
  number_range: ["lt", "le", "gt", "ge", "between", "eq", "ne"],
  free_text: ["eq", "ne", "contains", "matches"],
  free_text_with_fields: ["eq", "ne", "contains", "matches"],
};

// Question types whose options should be shown as a dropdown for single-value ops
const SELECT_TYPES = new Set([
  "single_select",
  "image_single_select",
  "gender_filter",
  "age_filter",
  "multi_select",
  "image_multi_select",
]);

interface Props {
  value: PredicateObj;
  onChange: (updated: PredicateObj) => void;
  onRemove: () => void;
  disabled?: boolean;
  /** Available QIDs for the searchable dropdown. */
  availableQids?: QidOption[];
}

/**
 * Edits a single predicate `{qid, field?, op, value}`.
 *
 * Context-aware: when the selected QID references a known question, the value
 * input adapts to that question's type (dropdown for single_select, checkboxes
 * for multi_select with array ops, constrained number input for number_range, etc.).
 * Falls back to generic text/number inputs for unknown question types.
 */
export default function PredicateEditor({ value, onChange, onRemove, disabled, availableQids = [] }: Props) {
  // Whether the optional `field` sub-property input is visible.
  // Auto-show if the predicate already has a field value.
  const [showField, setShowField] = useState(!!value.field);
  // Manual entry mode — when true, shows a plain text input instead of dropdown/checkboxes
  const [manualEntry, setManualEntry] = useState(false);

  // Look up the referenced question so we can adapt the value editor
  const refQuestion = useMemo(
    () => availableQids.find((q) => q.id === value.qid),
    [availableQids, value.qid],
  );

  // Extract option labels from the referenced question (used for dropdowns/checkboxes)
  const refOptionLabels = useMemo(() => {
    if (!refQuestion?.options) return [];
    return refQuestion.options
      .map((o) => o.label ?? o.id ?? "")
      .filter((l) => l !== "");
  }, [refQuestion]);

  /** Produce a type-appropriate default value when the operator changes. */
  const defaultValueForOp = (op: string): unknown => {
    if (TEXT_OPS.has(op)) return "";
    if (NUMBER_OPS.has(op)) return 0;
    if (op === "between") return [0, 0];
    if (ARRAY_OPS.has(op)) return [];
    return "";
  };

  const handleQidChange = (qid: string) => {
    const newRef = availableQids.find((q) => q.id === qid);
    // Reset value when the referenced question type changes, because the old
    // value (e.g. an option label from a single_select) won't be valid for
    // the new question (e.g. a free_text).
    if (newRef?.type !== refQuestion?.type) {
      setManualEntry(false);
      onChange({ ...value, qid, value: defaultValueForOp(value.op) });
    } else {
      onChange({ ...value, qid });
    }
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

  // --- Checkbox toggle helper (for array ops with known options) ---

  const toggleCheckbox = (label: string) => {
    const current = new Set(arrayValues);
    if (current.has(label)) {
      current.delete(label);
    } else {
      current.add(label);
    }
    onChange({ ...value, value: Array.from(current) });
  };

  // --- Render the value input based on operator type + referenced question ---

  const renderValueInput = () => {
    const op = value.op;
    const hasOptions = refOptionLabels.length > 0 && SELECT_TYPES.has(refQuestion?.type ?? "");
    const isNumberRange = refQuestion?.type === "number_range";

    // ----- Context-aware: select-type question with single-value text ops → dropdown -----
    if (hasOptions && TEXT_OPS.has(op) && !manualEntry) {
      const currentVal = String(value.value ?? "");
      // If the current value doesn't match any option, show it as a "custom" option
      const hasCustomValue = currentVal !== "" && !refOptionLabels.includes(currentVal);
      return (
        <div className="space-y-0.5">
          <select
            className="w-full border border-gray-300 rounded px-2 py-0.5 text-sm"
            value={currentVal}
            onChange={(e) => onChange({ ...value, value: e.target.value })}
            disabled={disabled}
          >
            <option value="">— select —</option>
            {hasCustomValue && (
              <option value={currentVal}>{currentVal} (custom)</option>
            )}
            {refOptionLabels.map((label) => (
              <option key={label} value={label}>{label}</option>
            ))}
          </select>
          <button
            type="button"
            className="text-[10px] text-gray-400 hover:text-blue-500"
            onClick={() => setManualEntry(true)}
            disabled={disabled}
          >
            manual entry
          </button>
        </div>
      );
    }

    // ----- Context-aware: select-type question with array ops → checkboxes -----
    if (hasOptions && ARRAY_OPS.has(op)) {
      // Values in the predicate that don't match any known option (historical/cross-ref)
      const extraValues = arrayValues.filter((v) => !refOptionLabels.includes(v));
      return (
        <div className="space-y-1">
          <div className="space-y-0.5 max-h-40 overflow-auto">
            {refOptionLabels.map((label) => (
              <label
                key={label}
                className="flex items-center gap-1.5 text-sm cursor-pointer hover:bg-gray-50 px-1 rounded"
              >
                <input
                  type="checkbox"
                  className="rounded border-gray-300"
                  checked={arrayValues.includes(label)}
                  onChange={() => toggleCheckbox(label)}
                  disabled={disabled}
                />
                <span className="truncate">{label}</span>
              </label>
            ))}
          </div>
          {/* Show any extra values that don't match known options (with remove button) */}
          {extraValues.map((item, i) => (
            <div key={`extra-${i}`} className="flex gap-1 items-center">
              <input
                type="text"
                className="flex-1 border border-gray-200 rounded px-2 py-0.5 text-sm"
                value={item}
                onChange={(e) => {
                  const idx = arrayValues.indexOf(item);
                  if (idx >= 0) updateArrayItem(idx, e.target.value);
                }}
                disabled={disabled}
                placeholder="Custom value"
              />
              <button
                type="button"
                className="px-1.5 text-red-500 hover:text-red-700 text-sm disabled:opacity-50"
                onClick={() => {
                  const idx = arrayValues.indexOf(item);
                  if (idx >= 0) removeArrayItem(idx);
                }}
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
            + Add custom value
          </button>
        </div>
      );
    }

    // ----- Context-aware: number_range with numeric ops → constrained number input -----
    if (isNumberRange && NUMBER_OPS.has(op)) {
      return (
        <input
          type="number"
          className="w-full border border-gray-200 rounded px-2 py-0.5 text-sm"
          value={value.value as number ?? ""}
          onChange={(e) => onChange({ ...value, value: Number(e.target.value) })}
          disabled={disabled}
          placeholder="0"
          min={refQuestion?.min_value}
          max={refQuestion?.max_value}
          step={refQuestion?.step}
        />
      );
    }

    // ----- Context-aware: number_range with between → two constrained number inputs -----
    if (isNumberRange && op === "between") {
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
            min={refQuestion?.min_value}
            max={refQuestion?.max_value}
            step={refQuestion?.step}
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
            min={refQuestion?.min_value}
            max={refQuestion?.max_value}
            step={refQuestion?.step}
          />
        </div>
      );
    }

    // ----- Generic fallbacks (original behavior) -----

    if (TEXT_OPS.has(op)) {
      return (
        <div className="space-y-0.5">
          <input
            type="text"
            className="w-full border border-gray-200 rounded px-2 py-0.5 text-sm"
            value={String(value.value ?? "")}
            onChange={(e) => onChange({ ...value, value: e.target.value })}
            disabled={disabled}
            placeholder="value"
          />
          {/* If in manual entry mode and there are known options, offer to switch back */}
          {manualEntry && hasOptions && (
            <button
              type="button"
              className="text-[10px] text-gray-400 hover:text-blue-500"
              onClick={() => setManualEntry(false)}
              disabled={disabled}
            >
              pick from options
            </button>
          )}
        </div>
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

  // --- Build the operator list with recommended ops grouped first ---
  const operatorOptions = useMemo(() => {
    const recommended = RECOMMENDED_OPS[refQuestion?.type ?? ""] ?? [];
    if (recommended.length === 0) {
      // No type info — return all operators flat (original behavior)
      return ALL_OPERATORS.map((op) => ({ op, recommended: false }));
    }
    const recSet = new Set(recommended);
    const recOps = ALL_OPERATORS.filter((op) => recSet.has(op)).map((op) => ({ op, recommended: true }));
    const otherOps = ALL_OPERATORS.filter((op) => !recSet.has(op)).map((op) => ({ op, recommended: false }));
    return [...recOps, ...otherOps];
  }, [refQuestion?.type]);

  return (
    <div className="border border-gray-200 rounded p-1.5 bg-white space-y-1">
      {/* Row 1: QID + remove button */}
      <div className="flex items-start gap-1">
        <div className="flex-1">
          <div className="flex items-center gap-1 mb-0.5">
            <label className="text-[11px] text-gray-500">QID</label>
            {refQuestion?.type && (
              <span className="text-[10px] px-1 py-px rounded bg-blue-100 text-blue-700 font-medium leading-tight">
                {refQuestion.type}
              </span>
            )}
          </div>
          <QidPicker
            value={value.qid}
            onChange={handleQidChange}
            availableQids={availableQids}
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

      {/* Operator dropdown — recommended ops shown first when question type is known */}
      <div>
        <label className="text-[11px] text-gray-500 block mb-0.5">Operator</label>
        <select
          className="w-full border border-gray-300 rounded px-2 py-0.5 text-xs"
          value={value.op}
          onChange={(e) => handleOpChange(e.target.value)}
          disabled={disabled}
        >
          {(() => {
            const recOps = operatorOptions.filter((o) => o.recommended);
            const otherOps = operatorOptions.filter((o) => !o.recommended);
            const hasGroups = recOps.length > 0 && otherOps.length > 0;
            return (
              <>
                {hasGroups ? (
                  <>
                    <optgroup label="recommended">
                      {recOps.map(({ op }) => (
                        <option key={op} value={op}>{op}</option>
                      ))}
                    </optgroup>
                    <optgroup label="other">
                      {otherOps.map(({ op }) => (
                        <option key={op} value={op}>{op}</option>
                      ))}
                    </optgroup>
                  </>
                ) : (
                  operatorOptions.map(({ op }) => (
                    <option key={op} value={op}>{op}</option>
                  ))
                )}
                {/* If current op is not in the list, still show it */}
                {!(ALL_OPERATORS as readonly string[]).includes(value.op) && (
                  <option value={value.op}>{value.op}</option>
                )}
              </>
            );
          })()}
        </select>
      </div>

      {/* Value input — shape depends on operator + referenced question type */}
      <div>
        <label className="text-[11px] text-gray-500 block mb-0.5">Value</label>
        {renderValueInput()}
      </div>
    </div>
  );
}

"use client";

import ActionEditor, { type ActionObj } from "./ActionEditor";

/** Comparison operators available for age filter options. */
const AGE_OPERATORS = [
  { value: "lt", symbol: "<" },
  { value: "gte", symbol: ">=" },
  { value: "gt", symbol: ">" },
  { value: "lte", symbol: "<=" },
] as const;

type OpValue = (typeof AGE_OPERATORS)[number]["value"];

/** Shape of a single age_filter option in the YAML. */
export interface AgeOptionObj {
  id?: string;
  label?: string;
  action?: ActionObj;
}

interface Props {
  options: AgeOptionObj[];
  onChange: (updated: AgeOptionObj[]) => void;
  disabled?: boolean;
  source?: string;
}

/** Parse an age_filter label like "<15" or ">=50" into operator + age value. */
function parseLabel(label: string): { op: OpValue; age: number } {
  // Try longest prefix first to avoid matching "<" before "<="
  if (label.startsWith(">=")) return { op: "gte", age: Number(label.slice(2)) };
  if (label.startsWith("<=")) return { op: "lte", age: Number(label.slice(2)) };
  if (label.startsWith(">")) return { op: "gt", age: Number(label.slice(1)) };
  if (label.startsWith("<")) return { op: "lt", age: Number(label.slice(1)) };
  // Fallback: try to extract number from the label
  const num = Number(label.replace(/\D/g, ""));
  return { op: "lt", age: isNaN(num) ? 0 : num };
}

/** Build the display label from operator + age (e.g. "lt" + 15 → "<15"). */
function buildLabel(op: OpValue, age: number): string {
  const sym = AGE_OPERATORS.find((o) => o.value === op)?.symbol ?? "<";
  return `${sym}${age}`;
}

/** Build the option id from operator + age (e.g. "lt" + 15 → "lt_15"). */
function buildId(op: OpValue, age: number): string {
  return `${op}_${age}`;
}

/**
 * Specialized editor for age_filter options.
 * Instead of free-text ID/label fields, shows a comparison operator dropdown
 * and a numeric age input. The ID and label are auto-derived.
 */
export default function AgeFilterEditor({
  options,
  onChange,
  disabled,
  source,
}: Props) {
  const updateOption = (
    index: number,
    op: OpValue,
    age: number,
  ) => {
    const updated = options.map((o, i) => {
      if (i !== index) return o;
      return {
        ...o,
        id: buildId(op, age),
        label: buildLabel(op, age),
      };
    });
    onChange(updated);
  };

  const updateOptionAction = (index: number, action: ActionObj) => {
    const updated = options.map((o, i) =>
      i === index ? { ...o, action } : o,
    );
    onChange(updated);
  };

  const addOption = () => {
    onChange([
      ...options,
      { id: "lt_0", label: "<0", action: { action: "goto", qid: [] } },
    ]);
  };

  const removeOption = (index: number) => {
    onChange(options.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-2">
      {options.map((opt, i) => {
        const { op, age } = parseLabel(opt.label || "");
        return (
          <div
            key={i}
            className="border border-gray-200 rounded p-1.5 bg-gray-50"
          >
            {/* Operator + Age row */}
            <div className="flex items-end gap-1.5 mb-1">
              <div className="flex-1">
                <label className="text-[11px] text-gray-500 block mb-0.5">
                  Condition
                </label>
                <div className="flex gap-1">
                  <select
                    className="border border-gray-200 rounded px-1.5 py-0.5 text-sm bg-white"
                    value={op}
                    onChange={(e) =>
                      updateOption(i, e.target.value as OpValue, age)
                    }
                    disabled={disabled}
                  >
                    {AGE_OPERATORS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.symbol}
                      </option>
                    ))}
                  </select>
                  <input
                    type="number"
                    className="flex-1 border border-gray-200 rounded px-2 py-0.5 text-sm"
                    value={age}
                    onChange={(e) =>
                      updateOption(i, op, Number(e.target.value))
                    }
                    disabled={disabled}
                    min={0}
                    max={200}
                    placeholder="Age"
                  />
                </div>
              </div>
              <button
                type="button"
                className="text-red-400 hover:text-red-600 text-sm px-1 pb-0.5 disabled:opacity-30"
                onClick={() => removeOption(i)}
                disabled={disabled}
                title="Remove option"
              >
                &times;
              </button>
            </div>

            {/* Auto-derived ID preview */}
            <div className="text-[10px] text-gray-400 mb-1">
              id: <code className="bg-gray-100 px-1 rounded">{opt.id}</code>
              {" · "}
              label: <code className="bg-gray-100 px-1 rounded">{opt.label}</code>
            </div>

            {/* Per-option action */}
            {opt.action && (
              <div className="mt-1">
                <label className="text-[11px] font-semibold block mb-0.5">
                  Action
                </label>
                <ActionEditor
                  value={opt.action}
                  onChange={(a) => updateOptionAction(i, a)}
                  disabled={disabled}
                  source={source}
                />
              </div>
            )}
          </div>
        );
      })}

      {/* Add option button */}
      <button
        type="button"
        className="w-full border border-dashed border-gray-300 rounded py-1 text-xs text-gray-500 hover:border-blue-400 hover:text-blue-600 disabled:opacity-30"
        onClick={addOption}
        disabled={disabled}
      >
        + Add Age Option
      </button>
    </div>
  );
}

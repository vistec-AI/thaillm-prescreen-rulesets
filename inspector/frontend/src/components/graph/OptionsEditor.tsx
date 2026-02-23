"use client";

import ActionEditor, { type ActionObj } from "./ActionEditor";
import type { QidOption } from "./QidPicker";

/** Shape of a single option in the YAML graph data. */
export interface OptionObj {
  id?: string;
  label?: string;
  action?: ActionObj;
}

interface Props {
  options: OptionObj[];
  onChange: (updated: OptionObj[]) => void;
  /** Whether each option has its own action (single_select, image_single_select, age_filter, gender_filter). */
  hasPerOptionAction: boolean;
  disabled?: boolean;
  /** Source of the question ("oldcarts" | "opd") — passed to ActionEditor. */
  source?: string;
  /** Available QIDs for searchable dropdowns — forwarded to ActionEditor. */
  availableQids?: QidOption[];
}

/**
 * Sub-component for editing an array of options.
 * Per option: editable ID, editable label, optional ActionEditor,
 * and a remove button. An "Add Option" button at the bottom lets users
 * create new choices.
 */
export default function OptionsEditor({
  options,
  onChange,
  hasPerOptionAction,
  disabled,
  source,
  availableQids,
}: Props) {
  const updateOption = (index: number, patch: Partial<OptionObj>) => {
    const updated = options.map((o, i) =>
      i === index ? { ...o, ...patch } : o,
    );
    onChange(updated);
  };

  const updateOptionAction = (index: number, action: ActionObj) => {
    const updated = options.map((o, i) =>
      i === index ? { ...o, action } : o,
    );
    onChange(updated);
  };

  const addOption = () => {
    const newOpt: OptionObj = { id: "", label: "" };
    // Per-option-action types need a default action on the new option
    if (hasPerOptionAction) {
      newOpt.action = { action: "goto", qid: [] };
    }
    onChange([...options, newOpt]);
  };

  const removeOption = (index: number) => {
    onChange(options.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-2">
      {options.map((opt, i) => (
        <div
          key={i}
          className="border border-gray-200 rounded p-1.5 bg-gray-50"
        >
          {/* Header row: ID input + remove button */}
          <div className="flex items-start gap-1 mb-1">
            <div className="flex-1">
              <label className="text-[11px] text-gray-500 block mb-0.5">ID</label>
              <input
                type="text"
                className="w-full border border-gray-200 rounded px-2 py-0.5 text-xs font-mono"
                value={opt.id || ""}
                onChange={(e) => updateOption(i, { id: e.target.value })}
                disabled={disabled}
                placeholder="option_id"
              />
            </div>
            <button
              type="button"
              className="text-red-400 hover:text-red-600 text-sm px-1 pt-4 disabled:opacity-30"
              onClick={() => removeOption(i)}
              disabled={disabled}
              title="Remove option"
            >
              &times;
            </button>
          </div>

          {/* Option label — editable */}
          <div className="mb-1">
            <label className="text-[11px] font-semibold block mb-0.5">Label</label>
            <input
              type="text"
              className="w-full border border-gray-200 rounded px-2 py-0.5 text-sm"
              value={opt.label || ""}
              onChange={(e) => updateOption(i, { label: e.target.value })}
              disabled={disabled}
            />
          </div>

          {/* Per-option action (for single_select, image_single_select, age_filter, gender_filter) */}
          {hasPerOptionAction && opt.action && (
            <div className="mt-1">
              <label className="text-[11px] font-semibold block mb-0.5">Action</label>
              <ActionEditor
                value={opt.action}
                onChange={(a) => updateOptionAction(i, a)}
                disabled={disabled}
                source={source}
                availableQids={availableQids}
              />
            </div>
          )}
        </div>
      ))}

      {/* Add option button */}
      <button
        type="button"
        className="w-full border border-dashed border-gray-300 rounded py-1 text-xs text-gray-500 hover:border-blue-400 hover:text-blue-600 disabled:opacity-30"
        onClick={addOption}
        disabled={disabled}
      >
        + Add Option
      </button>
    </div>
  );
}

"use client";

import ActionEditor, { type ActionObj } from "./ActionEditor";
import type { QidOption } from "./QidPicker";

/** Shape of a single gender_filter option in the YAML. */
export interface GenderOptionObj {
  id?: string;
  label?: string;
  action?: ActionObj;
}

interface Props {
  options: GenderOptionObj[];
  onChange: (updated: GenderOptionObj[]) => void;
  disabled?: boolean;
  source?: string;
  /** Available QIDs for searchable dropdowns — forwarded to ActionEditor. */
  availableQids?: QidOption[];
}

/** The only valid gender choices — id and label are always "male" or "female". */
const GENDERS = ["male", "female"] as const;

/**
 * Specialized editor for gender_filter options.
 * Shows exactly two fixed options (male / female) — only the action
 * for each gender is editable. Users cannot add, remove, or rename options.
 */
export default function GenderFilterEditor({
  options,
  onChange,
  disabled,
  source,
  availableQids,
}: Props) {
  // Ensure we always have exactly the two gender options in the correct order,
  // preserving existing actions when available.
  const normalized: GenderOptionObj[] = GENDERS.map((g) => {
    const existing = options.find((o) => o.id === g);
    return existing ?? { id: g, label: g, action: { action: "goto", qid: [] } };
  });

  const updateAction = (gender: string, action: ActionObj) => {
    const updated = normalized.map((o) =>
      o.id === gender ? { ...o, action } : o,
    );
    onChange(updated);
  };

  return (
    <div className="space-y-2">
      {normalized.map((opt) => (
        <div
          key={opt.id}
          className="border border-gray-200 rounded p-1.5 bg-gray-50"
        >
          {/* Gender label — read-only */}
          <div className="mb-1">
            <span className="inline-block text-sm font-medium capitalize bg-blue-50 text-blue-700 px-2 py-0.5 rounded">
              {opt.id}
            </span>
          </div>

          {/* Per-option action — editable */}
          {opt.action && (
            <div>
              <label className="text-[11px] font-semibold block mb-0.5">
                Action
              </label>
              <ActionEditor
                value={opt.action}
                onChange={(a) => updateAction(opt.id!, a)}
                disabled={disabled}
                source={source}
                availableQids={availableQids}
              />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

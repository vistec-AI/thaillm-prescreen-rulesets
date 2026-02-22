"use client";

import { useState, useEffect } from "react";
import type { ConstantsResponse } from "@/lib/types";
import { useApp } from "@/lib/context/AppContext";
import QidPicker, { type QidOption } from "./QidPicker";

/** Shape of an action object in the YAML graph data. */
export interface ActionObj {
  action: string;
  qid?: string[];
  metadata?: Record<string, unknown>;
}

/** All possible action types. OPD does not allow "opd". */
const ALL_ACTION_TYPES = ["goto", "opd", "terminate"] as const;
const OPD_ACTION_TYPES = ["goto", "terminate"] as const;

interface Props {
  value: ActionObj;
  onChange: (updated: ActionObj) => void;
  disabled?: boolean;
  /** Source of the question ("oldcarts" | "opd") — controls which action types are available. */
  source?: string;
  /** Available QIDs for the searchable dropdown in goto actions. */
  availableQids?: QidOption[];
}

/**
 * Sub-component for editing a single action object ({action, qid?, metadata?}).
 * Includes an action type dropdown to switch between goto/opd/terminate,
 * then renders type-specific controls:
 * - goto: comma-separated QID input
 * - opd: no editable params (label only)
 * - terminate: department checkboxes + severity dropdown
 */
export default function ActionEditor({ value, onChange, disabled, source, availableQids = [] }: Props) {
  const { loadConstants } = useApp();
  const [consts, setConsts] = useState<ConstantsResponse | null>(null);

  // Load constants for terminate action dropdowns
  useEffect(() => {
    if (value.action === "terminate") {
      loadConstants().then(setConsts);
    }
  }, [value.action, loadConstants]);

  // Available action types depend on source (OPD cannot use "opd" action)
  const actionTypes = source === "opd" ? OPD_ACTION_TYPES : ALL_ACTION_TYPES;

  /** Switch to a different action type, resetting type-specific fields. */
  const handleActionTypeChange = (newType: string) => {
    if (newType === value.action) return;
    if (newType === "goto") {
      onChange({ action: "goto", qid: [] });
    } else if (newType === "opd") {
      onChange({ action: "opd" });
    } else if (newType === "terminate") {
      onChange({ action: "terminate", metadata: {} });
    } else {
      onChange({ action: newType });
    }
  };

  // --- Action type selector (always shown) ---
  const actionTypeSelector = (
    <select
      className="border border-gray-300 rounded px-1.5 py-0.5 text-xs font-semibold"
      value={value.action}
      onChange={(e) => handleActionTypeChange(e.target.value)}
      disabled={disabled}
    >
      {actionTypes.map((t) => (
        <option key={t} value={t}>{t}</option>
      ))}
      {/* If current action is not in the list, still show it */}
      {!(actionTypes as readonly string[]).includes(value.action) && (
        <option value={value.action}>{value.action}</option>
      )}
    </select>
  );

  // --- Type-specific controls ---

  if (value.action === "goto") {
    const qids = value.qid || [];

    const updateQid = (index: number, newQid: string) => {
      const updated = qids.map((q, i) => (i === index ? newQid : q));
      onChange({ ...value, qid: updated });
    };

    const addQid = () => {
      onChange({ ...value, qid: [...qids, ""] });
    };

    const removeQid = (index: number) => {
      onChange({ ...value, qid: qids.filter((_, i) => i !== index) });
    };

    return (
      <div className="space-y-1">
        <div className="flex items-center gap-1.5">
          {actionTypeSelector}
        </div>
        {/* One QidPicker per target QID, with remove button */}
        {qids.map((qid, i) => (
          <div key={i} className="flex gap-1 items-center">
            <div className="flex-1">
              <QidPicker
                value={qid}
                onChange={(val) => updateQid(i, val)}
                availableQids={availableQids}
                disabled={disabled}
                placeholder="question_id"
              />
            </div>
            <button
              type="button"
              className="px-1.5 text-red-500 hover:text-red-700 text-sm disabled:opacity-50"
              onClick={() => removeQid(i)}
              disabled={disabled}
              title="Remove QID"
            >
              &times;
            </button>
          </div>
        ))}
        <button
          type="button"
          className="px-2 py-0.5 text-xs bg-gray-100 rounded hover:bg-gray-200 disabled:opacity-50"
          onClick={addQid}
          disabled={disabled}
        >
          + Add QID
        </button>
      </div>
    );
  }

  if (value.action === "opd") {
    return (
      <div className="flex items-center gap-1.5">
        {actionTypeSelector}
        <span className="text-xs text-gray-500">Routes to OPD flow</span>
      </div>
    );
  }

  if (value.action === "terminate") {
    const meta = value.metadata || {};
    const rawSev = meta.severity as { id?: string } | undefined;
    const sevValue = rawSev?.id || "";
    const rawDept = meta.department as Array<{ id: string }> | undefined;
    const checkedDepts = Array.isArray(rawDept) ? rawDept.map((d) => d.id) : [];

    const updateMeta = (newSev: string, newDepts: string[]) => {
      const newMeta: Record<string, unknown> = { ...meta };
      if (newSev) {
        newMeta.severity = { id: newSev };
      } else {
        delete newMeta.severity;
      }
      if (newDepts.length > 0) {
        newMeta.department = newDepts.map((id) => ({ id }));
      } else {
        delete newMeta.department;
      }
      onChange({ ...value, metadata: newMeta });
    };

    const toggleDept = (deptId: string) => {
      const newDepts = checkedDepts.includes(deptId)
        ? checkedDepts.filter((d) => d !== deptId)
        : [...checkedDepts, deptId];
      updateMeta(sevValue, newDepts);
    };

    return (
      <div>
        <div className="flex items-center gap-1.5 mb-1">
          {actionTypeSelector}
        </div>

        {consts && (
          <div className="mb-1">
            <label className="text-[11px] font-semibold block mb-0.5">Severity</label>
            <select
              className="w-full border border-gray-300 rounded px-2 py-0.5 text-xs"
              value={sevValue}
              onChange={(e) => updateMeta(e.target.value, checkedDepts)}
              disabled={disabled}
            >
              <option value="">(none)</option>
              {consts.severity_levels.map((sev) => (
                <option key={sev.id} value={sev.id}>
                  {sev.name} ({sev.id})
                </option>
              ))}
            </select>
          </div>
        )}

        {consts && (
          <div className="mb-1">
            <label className="text-[11px] font-semibold block mb-0.5">Department</label>
            <div className="max-h-28 overflow-auto text-xs">
              {consts.departments.map((dept) => (
                <label key={dept.id} className="block py-0.5">
                  <input
                    type="checkbox"
                    checked={checkedDepts.includes(dept.id)}
                    onChange={() => toggleDept(dept.id)}
                    disabled={disabled}
                  />{" "}
                  {dept.name} ({dept.id})
                </label>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  // Fallback for unknown action types
  return (
    <div className="flex items-center gap-1.5">
      {actionTypeSelector}
      <span className="text-xs text-gray-500">No editable parameters</span>
    </div>
  );
}

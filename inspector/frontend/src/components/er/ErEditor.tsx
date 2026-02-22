"use client";

import { useState, useEffect } from "react";
import type { ErChecklistItem, ConstantsResponse } from "@/lib/types";
import { useApp } from "@/lib/context/AppContext";

interface Props {
  item: ErChecklistItem;
  mode: string;
  onSave: (data: Record<string, unknown>) => Promise<void>;
  onCancel: () => void;
}

/**
 * Structured ER editor: text textarea + severity dropdown + department
 * checkboxes.  For ``er_symptom`` mode only the text is editable.
 */
export default function ErEditor({ item, mode, onSave, onCancel }: Props) {
  const { loadConstants } = useApp();

  const [text, setText] = useState(item.raw.text as string || "");
  const [sevValue, setSevValue] = useState("");
  const [checkedDepts, setCheckedDepts] = useState<string[]>([]);
  const [consts, setConsts] = useState<ConstantsResponse | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);

  const isSymptomMode = mode === "er_symptom";

  // Load constants for dropdowns
  useEffect(() => {
    if (!isSymptomMode) {
      loadConstants().then(setConsts);
    }
  }, [isSymptomMode, loadConstants]);

  // Initialize form values from item
  useEffect(() => {
    setText(item.raw.text as string || "");
    const sevKey = mode === "er_adult" ? "min_severity" : "severity";
    const rawSev = item.raw[sevKey] as { id?: string } | undefined;
    setSevValue(rawSev?.id || "");
    const rawDept = item.raw.department as Array<{ id: string }> | undefined;
    setCheckedDepts(Array.isArray(rawDept) ? rawDept.map((d) => d.id) : []);
    setErrors([]);
    setStatus("");
  }, [item, mode]);

  const validate = (): string[] => {
    const errs: string[] = [];
    if (!text.trim()) errs.push("Question text must not be empty.");
    if (!isSymptomMode) {
      if (checkedDepts.length > 0 && !sevValue) {
        errs.push("Department override requires a severity override. Select a severity or uncheck all departments.");
      }
      const effectiveSev = sevValue || "sev003";
      if (effectiveSev === "sev003" && checkedDepts.length > 0 && !checkedDepts.includes("dept002")) {
        errs.push("Emergency severity (sev003) requires Emergency Medicine (dept002) in the department list.");
      }
    }
    return errs;
  };

  const handleSave = async () => {
    const validationErrors = validate();
    if (validationErrors.length > 0) {
      setErrors(validationErrors);
      return;
    }
    setErrors([]);

    // Build data object from form fields
    const obj: Record<string, unknown> = { qid: item.qid, text: text.trim() };
    if (!isSymptomMode) {
      if (sevValue) {
        const sevKey = mode === "er_adult" ? "min_severity" : "severity";
        obj[sevKey] = { id: sevValue };
      }
      if (checkedDepts.length > 0) {
        obj.department = checkedDepts.map((id) => ({ id }));
      }
    }

    setSaving(true);
    setStatus("Saving and running tests...");
    try {
      await onSave(obj);
      setStatus("Saved");
    } catch {
      setStatus("Error");
    } finally {
      setSaving(false);
    }
  };

  const toggleDept = (deptId: string) => {
    setCheckedDepts((prev) =>
      prev.includes(deptId) ? prev.filter((d) => d !== deptId) : [...prev, deptId],
    );
  };

  return (
    <div className="mt-2">
      <div className="flex items-center gap-1.5 mb-1.5">
        <b className="text-sm">Edit Question</b>
        {status && <span className="ml-auto text-xs text-gray-500">{status}</span>}
      </div>

      {/* Question text */}
      <div className="mb-1.5">
        <label className="text-xs font-semibold block mb-0.5">Question Text</label>
        <textarea
          className="w-full h-16 text-[13px] p-1.5 border border-gray-200 rounded"
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={saving}
        />
      </div>

      {/* Severity dropdown (hidden for er_symptom) */}
      {!isSymptomMode && consts && (
        <div className="mb-1.5">
          <label className="text-xs font-semibold block mb-0.5">Severity</label>
          <select
            className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
            value={sevValue}
            onChange={(e) => setSevValue(e.target.value)}
            disabled={saving}
          >
            <option value="">(Default — Emergency)</option>
            {consts.severity_levels.map((sev) => (
              <option key={sev.id} value={sev.id}>
                {sev.name} ({sev.id})
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Department checkboxes (hidden for er_symptom) */}
      {!isSymptomMode && consts && (
        <div className="mb-1.5">
          <label className="text-xs font-semibold block mb-0.5">Department</label>
          <div className="max-h-40 overflow-auto text-xs">
            {consts.departments.map((dept) => (
              <label key={dept.id} className="block py-0.5">
                <input
                  type="checkbox"
                  checked={checkedDepts.includes(dept.id)}
                  onChange={() => toggleDept(dept.id)}
                  disabled={saving}
                />{" "}
                {dept.name} ({dept.id})
              </label>
            ))}
            <div className="text-[11px] text-gray-500 mt-1">
              Leave all unchecked for default routing (Emergency Medicine).
            </div>
          </div>
        </div>
      )}

      {/* Validation errors */}
      {errors.length > 0 && (
        <div className="text-red-700 text-xs mb-1.5">
          {errors.map((e, i) => (
            <div key={i}>{e}</div>
          ))}
        </div>
      )}

      <div className="flex gap-2 mt-1.5">
        <button
          className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          onClick={handleSave}
          disabled={saving}
        >
          Save
        </button>
        <button
          className="px-3 py-1 text-sm bg-gray-200 rounded hover:bg-gray-300 disabled:opacity-50"
          onClick={onCancel}
          disabled={saving}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

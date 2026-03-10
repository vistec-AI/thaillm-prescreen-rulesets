"use client";

import { useState, useEffect } from "react";
import type { DemographicItem, FieldCondition, DetailField } from "@/lib/types";

// All valid field types across demographic, past_history, and personal_history
const FIELD_TYPES = ["date", "datetime", "enum", "float", "from_yaml", "int", "str", "yes_no_detail"] as const;

// Operators available for field conditions
const CONDITION_OPS = ["eq", "ne", "lt", "le", "gt", "ge"] as const;

// Types available for detail sub-fields within yes_no_detail
const DETAIL_FIELD_TYPES = ["str", "date", "enum"] as const;

interface Props {
  item: DemographicItem | null;
  /** When true the editor creates a new entry instead of editing an existing one. */
  isNew?: boolean;
  /** Display label for the editor heading (e.g. "Demographic", "Past History"). */
  label?: string;
  /** QID prefix hint for the placeholder (e.g. "demo_", "past_", "pers_"). */
  qidPrefix?: string;
  onSave: (data: Record<string, unknown>) => Promise<void>;
  onCancel: () => void;
}

/**
 * Structured form editor for demographic/past-history/personal-history items.
 * Supports all field types including conditional visibility, max_value for int,
 * and detail_fields for yes_no_detail.
 */
export default function DemographicEditor({ item, isNew, label = "Demographic", qidPrefix = "demo_", onSave, onCancel }: Props) {
  const [qid, setQid] = useState(item?.qid ?? "");
  const [key, setKey] = useState(item?.key ?? "");
  const [fieldName, setFieldName] = useState(item?.field_name ?? "");
  const [fieldNameTh, setFieldNameTh] = useState(item?.field_name_th ?? "");
  const [type, setType] = useState<DemographicItem["type"]>(item?.type ?? "str");
  const [optional, setOptional] = useState(item?.optional ?? false);
  // For enum type: editable list of string values
  const [enumValues, setEnumValues] = useState<string[]>([]);
  // Condition editor state
  const [hasCondition, setHasCondition] = useState(false);
  const [condField, setCondField] = useState("");
  const [condOp, setCondOp] = useState<string>("eq");
  const [condValue, setCondValue] = useState("");
  // Max value for int type
  const [maxValue, setMaxValue] = useState<string>("");
  // Detail fields for yes_no_detail type
  const [detailFields, setDetailFields] = useState<DetailField[]>([]);

  const [errors, setErrors] = useState<string[]>([]);
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);

  // Re-initialize form when the selected item changes
  useEffect(() => {
    setQid(item?.qid ?? "");
    setKey(item?.key ?? "");
    setFieldName(item?.field_name ?? "");
    setFieldNameTh(item?.field_name_th ?? "");
    setType(item?.type ?? "str");
    setOptional(item?.optional ?? false);
    // Populate enum values from the item if it's an enum type
    if (item?.type === "enum" && Array.isArray(item.values)) {
      setEnumValues(item.values.map(String));
    } else {
      setEnumValues([]);
    }
    // Condition
    if (item?.condition) {
      setHasCondition(true);
      setCondField(item.condition.field);
      setCondOp(item.condition.op);
      setCondValue(String(item.condition.value ?? ""));
    } else {
      setHasCondition(false);
      setCondField("");
      setCondOp("eq");
      setCondValue("");
    }
    // Max value
    setMaxValue(item?.max_value != null ? String(item.max_value) : "");
    // Detail fields
    setDetailFields(item?.detail_fields ? [...item.detail_fields] : []);
    setErrors([]);
    setStatus("");
  }, [item]);

  const validate = (): string[] => {
    const errs: string[] = [];
    if (isNew && !qid.trim()) errs.push("QID must not be empty.");
    if (!key.trim()) errs.push("Key must not be empty.");
    if (!fieldName.trim()) errs.push("Field Name must not be empty.");
    if (!fieldNameTh.trim()) errs.push("Field Name (TH) must not be empty.");
    if (type === "enum" && enumValues.filter((v) => v.trim()).length === 0) {
      errs.push("Enum type must have at least one value.");
    }
    if (hasCondition && !condField.trim()) {
      errs.push("Condition field must not be empty.");
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

    // Build the data object matching the YAML schema
    const obj: Record<string, unknown> = {
      qid: isNew ? qid.trim() : item!.qid,
      key: key.trim(),
      field_name: fieldName.trim(),
      field_name_th: fieldNameTh.trim(),
      type,
      optional,
    };

    if (type === "enum") {
      // Send cleaned enum values (remove empty strings)
      obj.values = enumValues.filter((v) => v.trim()).map((v) => v.trim());
    } else if (type === "from_yaml") {
      // Send back the original path string, not the resolved array
      obj.values = item?.values_path || "";
    }

    // Condition — include only when user has it enabled
    if (hasCondition && condField.trim()) {
      // Try to parse value as number, fall back to string
      let parsedValue: unknown = condValue;
      if (condValue !== "" && !isNaN(Number(condValue))) {
        parsedValue = Number(condValue);
      }
      obj.condition = { field: condField.trim(), op: condOp, value: parsedValue };
    }

    // Max value for int type
    if (type === "int" && maxValue.trim()) {
      obj.max_value = Number(maxValue);
    }

    // Detail fields for yes_no_detail type
    if (type === "yes_no_detail" && detailFields.length > 0) {
      obj.detail_fields = detailFields.filter((df) => df.key.trim());
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

  // --- Enum value helpers ---
  const addEnumValue = () => setEnumValues((prev) => [...prev, ""]);
  const removeEnumValue = (index: number) => setEnumValues((prev) => prev.filter((_, i) => i !== index));
  const updateEnumValue = (index: number, value: string) =>
    setEnumValues((prev) => prev.map((v, i) => (i === index ? value : v)));

  // --- Detail field helpers ---
  const addDetailField = () =>
    setDetailFields((prev) => [...prev, { key: "", type: "str", field_name_th: "" }]);
  const removeDetailField = (index: number) =>
    setDetailFields((prev) => prev.filter((_, i) => i !== index));
  const updateDetailField = (index: number, patch: Partial<DetailField>) =>
    setDetailFields((prev) => prev.map((df, i) => (i === index ? { ...df, ...patch } : df)));

  return (
    <div className="mt-2">
      <div className="flex items-center gap-1.5 mb-1.5">
        <b className="text-sm">{isNew ? `Add ${label} Item` : `Edit ${label} Item`}</b>
        {status && <span className="ml-auto text-xs text-gray-500">{status}</span>}
      </div>

      {/* QID — editable when creating, read-only when editing */}
      <div className="mb-1.5">
        <label className="text-xs font-semibold block mb-0.5">QID</label>
        {isNew ? (
          <input
            type="text"
            className="w-full border border-gray-200 rounded px-2 py-1 text-sm font-mono"
            value={qid}
            onChange={(e) => setQid(e.target.value)}
            disabled={saving}
            placeholder={`e.g. ${qidPrefix}new_field`}
          />
        ) : (
          <code className="text-xs bg-gray-50 px-1.5 py-0.5 rounded block">{item!.qid}</code>
        )}
      </div>

      {/* Key */}
      <div className="mb-1.5">
        <label className="text-xs font-semibold block mb-0.5">Key</label>
        <input
          type="text"
          className="w-full border border-gray-200 rounded px-2 py-1 text-sm"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          disabled={saving}
        />
      </div>

      {/* Field Name */}
      <div className="mb-1.5">
        <label className="text-xs font-semibold block mb-0.5">Field Name</label>
        <input
          type="text"
          className="w-full border border-gray-200 rounded px-2 py-1 text-sm"
          value={fieldName}
          onChange={(e) => setFieldName(e.target.value)}
          disabled={saving}
        />
      </div>

      {/* Field Name (TH) */}
      <div className="mb-1.5">
        <label className="text-xs font-semibold block mb-0.5">Field Name (TH)</label>
        <input
          type="text"
          className="w-full border border-gray-200 rounded px-2 py-1 text-sm"
          value={fieldNameTh}
          onChange={(e) => setFieldNameTh(e.target.value)}
          disabled={saving}
        />
      </div>

      {/* Type dropdown */}
      <div className="mb-1.5">
        <label className="text-xs font-semibold block mb-0.5">Type</label>
        <select
          className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
          value={type}
          onChange={(e) => setType(e.target.value as DemographicItem["type"])}
          disabled={saving}
        >
          {FIELD_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>

      {/* Optional checkbox */}
      <div className="mb-1.5">
        <label className="text-xs font-semibold flex items-center gap-1.5">
          <input
            type="checkbox"
            checked={optional}
            onChange={(e) => setOptional(e.target.checked)}
            disabled={saving}
          />
          Optional
        </label>
      </div>

      {/* --- Condition editor --- */}
      <div className="mb-1.5">
        <label className="text-xs font-semibold flex items-center gap-1.5">
          <input
            type="checkbox"
            checked={hasCondition}
            onChange={(e) => setHasCondition(e.target.checked)}
            disabled={saving}
          />
          Has condition
        </label>
        {hasCondition && (
          <div className="mt-1 flex gap-1 items-center">
            <input
              type="text"
              className="flex-1 border border-gray-200 rounded px-2 py-0.5 text-sm"
              value={condField}
              onChange={(e) => setCondField(e.target.value)}
              disabled={saving}
              placeholder="field key"
            />
            <select
              className="border border-gray-300 rounded px-1 py-0.5 text-sm"
              value={condOp}
              onChange={(e) => setCondOp(e.target.value)}
              disabled={saving}
            >
              {CONDITION_OPS.map((op) => (
                <option key={op} value={op}>{op}</option>
              ))}
            </select>
            <input
              type="text"
              className="w-20 border border-gray-200 rounded px-2 py-0.5 text-sm"
              value={condValue}
              onChange={(e) => setCondValue(e.target.value)}
              disabled={saving}
              placeholder="value"
            />
          </div>
        )}
      </div>

      {/* --- Max value for int type --- */}
      {type === "int" && (
        <div className="mb-1.5">
          <label className="text-xs font-semibold block mb-0.5">Max Value</label>
          <input
            type="number"
            className="w-full border border-gray-200 rounded px-2 py-1 text-sm"
            value={maxValue}
            onChange={(e) => setMaxValue(e.target.value)}
            disabled={saving}
            placeholder="e.g. 11"
          />
        </div>
      )}

      {/* Enum values — editable list (only shown when type=enum) */}
      {type === "enum" && (
        <div className="mb-1.5">
          <label className="text-xs font-semibold block mb-0.5">Values</label>
          <div className="space-y-1">
            {enumValues.map((val, i) => (
              <div key={i} className="flex gap-1">
                <input
                  type="text"
                  className="flex-1 border border-gray-200 rounded px-2 py-0.5 text-sm"
                  value={val}
                  onChange={(e) => updateEnumValue(i, e.target.value)}
                  disabled={saving}
                  placeholder={`Value ${i + 1}`}
                />
                <button
                  type="button"
                  className="px-1.5 text-red-500 hover:text-red-700 text-sm disabled:opacity-50"
                  onClick={() => removeEnumValue(i)}
                  disabled={saving}
                  title="Remove value"
                >
                  x
                </button>
              </div>
            ))}
          </div>
          <button
            type="button"
            className="mt-1 px-2 py-0.5 text-xs bg-gray-100 rounded hover:bg-gray-200 disabled:opacity-50"
            onClick={addEnumValue}
            disabled={saving}
          >
            + Add value
          </button>
        </div>
      )}

      {/* from_yaml source path — read-only */}
      {type === "from_yaml" && item?.values_path && (
        <div className="mb-1.5">
          <label className="text-xs font-semibold block mb-0.5">Source Path</label>
          <code className="text-xs bg-gray-50 px-1.5 py-0.5 rounded block break-all">
            {item.values_path}
          </code>
        </div>
      )}

      {/* --- Detail fields for yes_no_detail type --- */}
      {type === "yes_no_detail" && (
        <div className="mb-1.5">
          <label className="text-xs font-semibold block mb-0.5">Detail Fields</label>
          <div className="space-y-1.5">
            {detailFields.map((df, i) => (
              <div key={i} className="border border-gray-200 rounded p-1.5 bg-gray-50">
                <div className="flex gap-1 mb-1">
                  <input
                    type="text"
                    className="flex-1 border border-gray-200 rounded px-2 py-0.5 text-sm"
                    value={df.key}
                    onChange={(e) => updateDetailField(i, { key: e.target.value })}
                    disabled={saving}
                    placeholder="key"
                  />
                  <select
                    className="border border-gray-300 rounded px-1 py-0.5 text-sm"
                    value={df.type}
                    onChange={(e) => updateDetailField(i, { type: e.target.value })}
                    disabled={saving}
                  >
                    {DETAIL_FIELD_TYPES.map((t) => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="px-1.5 text-red-500 hover:text-red-700 text-sm disabled:opacity-50"
                    onClick={() => removeDetailField(i)}
                    disabled={saving}
                    title="Remove detail field"
                  >
                    x
                  </button>
                </div>
                <input
                  type="text"
                  className="w-full border border-gray-200 rounded px-2 py-0.5 text-sm"
                  value={df.field_name_th}
                  onChange={(e) => updateDetailField(i, { field_name_th: e.target.value })}
                  disabled={saving}
                  placeholder="Thai label"
                />
              </div>
            ))}
          </div>
          <button
            type="button"
            className="mt-1 px-2 py-0.5 text-xs bg-gray-100 rounded hover:bg-gray-200 disabled:opacity-50"
            onClick={addDetailField}
            disabled={saving}
          >
            + Add detail field
          </button>
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

"use client";

import { useState, useEffect } from "react";
import type { GraphNodeData } from "@/lib/types";
import ActionEditor, { type ActionObj } from "./ActionEditor";
import OptionsEditor, { type OptionObj } from "./OptionsEditor";
import RulesEditor, { type RuleObj } from "./RulesEditor";

// Valid question types per source.
// OLDCARTS supports all 10 types; OPD only allows a subset.
const OLDCARTS_QUESTION_TYPES = [
  "free_text",
  "free_text_with_fields",
  "number_range",
  "single_select",
  "multi_select",
  "image_single_select",
  "image_multi_select",
  "conditional",
  "gender_filter",
  "age_filter",
] as const;

const OPD_QUESTION_TYPES = [
  "age_filter",
  "gender_filter",
  "single_select",
  "number_range",
  "conditional",
] as const;

/** Question types that use on_submit (single action after answering). */
const ON_SUBMIT_TYPES = new Set([
  "free_text",
  "free_text_with_fields",
  "number_range",
]);

/** Question types that use next (unified action for all selected options). */
const NEXT_ACTION_TYPES = new Set(["multi_select", "image_multi_select"]);

interface Props {
  data: GraphNodeData;
  onSave: (data: Record<string, unknown>) => Promise<void>;
  onCancel: () => void;
}

/** Deep-clone a value via JSON round-trip. */
function deepClone<T>(val: T): T {
  return JSON.parse(JSON.stringify(val));
}

/** Default empty action for initializing new on_submit/next fields. */
function defaultAction(): ActionObj {
  return { action: "goto", qid: [] };
}

/**
 * Master form editor for OLDCARTS/OPD graph questions.
 * Shows common fields (QID, question text, question type dropdown) at the top,
 * then renders type-specific sections based on question_type.
 *
 * The question_type is editable — the backend runs pytest after save and
 * rolls back if the new type is invalid or incompatible.
 */
export default function GraphEditor({ data, onSave, onCancel }: Props) {
  const raw = data.raw ?? (data as unknown as Record<string, unknown>);
  const source = data.source || "";

  // Editable question text (separate from raw clone)
  const [question, setQuestion] = useState(data.label || "");
  // Editable question type
  const [qType, setQType] = useState(data.type || "");
  // Deep clone of raw data for type-specific field editing
  const [rawClone, setRawClone] = useState<Record<string, unknown>>(() => deepClone(raw));
  const [errors, setErrors] = useState<string[]>([]);
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);

  // Re-initialize when the selected node changes
  useEffect(() => {
    setQuestion(data.label || "");
    setQType(data.type || "");
    setRawClone(deepClone(data.raw ?? (data as unknown as Record<string, unknown>)));
    setErrors([]);
    setStatus("");
  }, [data]);

  // Available question types based on source
  const questionTypes = source === "opd" ? OPD_QUESTION_TYPES : OLDCARTS_QUESTION_TYPES;

  // --- Helpers to read/write nested rawClone fields ---

  const getOptions = (): OptionObj[] => {
    const opts = rawClone.options as OptionObj[] | undefined;
    return Array.isArray(opts) ? opts : [];
  };

  const setOptions = (opts: OptionObj[]) => {
    setRawClone((prev) => ({ ...prev, options: opts }));
  };

  const getOnSubmit = (): ActionObj => {
    const a = rawClone.on_submit as ActionObj | undefined;
    return a || defaultAction();
  };

  const setOnSubmit = (a: ActionObj) => {
    setRawClone((prev) => ({ ...prev, on_submit: a }));
  };

  const getNextAction = (): ActionObj => {
    const a = rawClone.next as ActionObj | undefined;
    return a || defaultAction();
  };

  const setNextAction = (a: ActionObj) => {
    setRawClone((prev) => ({ ...prev, next: a }));
  };

  const getRules = (): RuleObj[] => {
    const r = rawClone.rules as RuleObj[] | undefined;
    return Array.isArray(r) ? r : [];
  };

  const getDefault = (): ActionObj | null => {
    const d = rawClone.default as ActionObj | undefined;
    return d || null;
  };

  /** Callback for RulesEditor — writes both rules[] and default to rawClone. */
  const handleRulesChange = (rules: RuleObj[], defaultAction: ActionObj | null) => {
    setRawClone((prev) => {
      const updated: Record<string, unknown> = { ...prev, rules };
      if (defaultAction) {
        updated.default = defaultAction;
      } else {
        delete updated.default;
      }
      return updated;
    });
  };

  // --- Question type change handler ---
  // When the type changes, update rawClone.question_type and ensure
  // the action field matches the new type's pattern (on_submit vs next).
  const handleTypeChange = (newType: string) => {
    setQType(newType);
    setRawClone((prev) => {
      const updated: Record<string, unknown> = { ...prev, question_type: newType };

      // Ensure on_submit exists for types that need it
      if (ON_SUBMIT_TYPES.has(newType) && !updated.on_submit) {
        updated.on_submit = defaultAction();
      }
      // Ensure next exists for multi-select types
      if (NEXT_ACTION_TYPES.has(newType) && !updated.next) {
        updated.next = defaultAction();
      }

      return updated;
    });
  };

  // --- Validation ---

  const validate = (): string[] => {
    const errs: string[] = [];
    if (!question.trim()) errs.push("Question text must not be empty.");
    if (!qType) errs.push("Question type must be selected.");
    return errs;
  };

  // --- Save handler ---

  const handleSave = async () => {
    const validationErrors = validate();
    if (validationErrors.length > 0) {
      setErrors(validationErrors);
      return;
    }
    setErrors([]);

    // Merge question text and question type back into the raw clone
    const obj: Record<string, unknown> = {
      ...rawClone,
      question: question.trim(),
      question_type: qType,
    };

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

  // --- Type-specific sections ---

  const renderOnSubmitAction = () => (
    <div>
      <label className="text-xs font-semibold block mb-0.5">On Submit</label>
      <ActionEditor
        value={getOnSubmit()}
        onChange={setOnSubmit}
        disabled={saving}
        source={source}
      />
    </div>
  );

  const renderNumberRange = () => (
    <div className="space-y-1.5">
      <div className="grid grid-cols-2 gap-1.5">
        <div>
          <label className="text-[11px] font-semibold block mb-0.5">Min Value</label>
          <input
            type="number"
            className="w-full border border-gray-200 rounded px-2 py-0.5 text-sm"
            value={(rawClone.min_value as number) ?? ""}
            onChange={(e) =>
              setRawClone((prev) => ({ ...prev, min_value: Number(e.target.value) }))
            }
            disabled={saving}
          />
        </div>
        <div>
          <label className="text-[11px] font-semibold block mb-0.5">Max Value</label>
          <input
            type="number"
            className="w-full border border-gray-200 rounded px-2 py-0.5 text-sm"
            value={(rawClone.max_value as number) ?? ""}
            onChange={(e) =>
              setRawClone((prev) => ({ ...prev, max_value: Number(e.target.value) }))
            }
            disabled={saving}
          />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-1.5">
        <div>
          <label className="text-[11px] font-semibold block mb-0.5">Step</label>
          <input
            type="number"
            className="w-full border border-gray-200 rounded px-2 py-0.5 text-sm"
            value={(rawClone.step as number) ?? ""}
            onChange={(e) =>
              setRawClone((prev) => ({ ...prev, step: Number(e.target.value) }))
            }
            disabled={saving}
          />
        </div>
        <div>
          <label className="text-[11px] font-semibold block mb-0.5">Default Value</label>
          <input
            type="number"
            className="w-full border border-gray-200 rounded px-2 py-0.5 text-sm"
            value={(rawClone.default_value as number) ?? ""}
            onChange={(e) =>
              setRawClone((prev) => ({ ...prev, default_value: Number(e.target.value) }))
            }
            disabled={saving}
          />
        </div>
      </div>
      {renderOnSubmitAction()}
    </div>
  );

  const renderFreeText = () => renderOnSubmitAction();

  const renderFreeTextWithFields = () => {
    const fields = (rawClone.fields as Array<{ id: string; label?: string; kind?: string }>) || [];

    const setFields = (updated: Array<{ id: string; label?: string; kind?: string }>) => {
      setRawClone((prev) => ({ ...prev, fields: updated }));
    };

    const updateField = (index: number, patch: Partial<{ id: string; label: string; kind: string }>) => {
      setFields(fields.map((f, i) => (i === index ? { ...f, ...patch } : f)));
    };

    const addField = () => {
      setFields([...fields, { id: "", label: "", kind: "text" }]);
    };

    const removeField = (index: number) => {
      setFields(fields.filter((_, i) => i !== index));
    };

    return (
      <div className="space-y-1.5">
        <div>
          <label className="text-xs font-semibold block mb-0.5">Fields</label>
          <div className="space-y-1.5">
            {fields.map((f, i) => (
              <div
                key={i}
                className="border border-gray-200 rounded p-1.5 bg-gray-50"
              >
                <div className="flex items-start gap-1">
                  <div className="flex-1 space-y-1">
                    <div>
                      <label className="text-[11px] text-gray-500 block mb-0.5">ID</label>
                      <input
                        type="text"
                        className="w-full border border-gray-200 rounded px-2 py-0.5 text-xs font-mono"
                        value={f.id || ""}
                        onChange={(e) => updateField(i, { id: e.target.value })}
                        disabled={saving}
                        placeholder="field_id"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] text-gray-500 block mb-0.5">Label</label>
                      <input
                        type="text"
                        className="w-full border border-gray-200 rounded px-2 py-0.5 text-sm"
                        value={f.label || ""}
                        onChange={(e) => updateField(i, { label: e.target.value })}
                        disabled={saving}
                      />
                    </div>
                  </div>
                  <button
                    type="button"
                    className="text-red-400 hover:text-red-600 text-sm px-1 pt-4 disabled:opacity-30"
                    onClick={() => removeField(i)}
                    disabled={saving}
                    title="Remove field"
                  >
                    &times;
                  </button>
                </div>
              </div>
            ))}
            {/* Add field button */}
            <button
              type="button"
              className="w-full border border-dashed border-gray-300 rounded py-1 text-xs text-gray-500 hover:border-blue-400 hover:text-blue-600 disabled:opacity-30"
              onClick={addField}
              disabled={saving}
            >
              + Add Field
            </button>
          </div>
        </div>
        {renderOnSubmitAction()}
      </div>
    );
  };

  const renderSingleSelect = () => (
    <div>
      <label className="text-xs font-semibold block mb-0.5">Options</label>
      <OptionsEditor
        options={getOptions()}
        onChange={setOptions}
        hasPerOptionAction={true}
        disabled={saving}
        source={source}
      />
    </div>
  );

  const renderMultiSelect = () => (
    <div className="space-y-1.5">
      <div>
        <label className="text-xs font-semibold block mb-0.5">Options</label>
        <OptionsEditor
          options={getOptions()}
          onChange={setOptions}
          hasPerOptionAction={false}
          disabled={saving}
          source={source}
        />
      </div>
      <div>
        <label className="text-xs font-semibold block mb-0.5">Next Action</label>
        <ActionEditor
          value={getNextAction()}
          onChange={setNextAction}
          disabled={saving}
          source={source}
        />
      </div>
    </div>
  );

  const renderImageSingleSelect = () => (
    <div className="space-y-1.5">
      {data.image && (
        <div>
          <label className="text-xs font-semibold block mb-0.5">Image</label>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={data.image}
            alt="question image"
            className="max-w-full max-h-32 border border-gray-200 rounded"
          />
        </div>
      )}
      <div>
        <label className="text-xs font-semibold block mb-0.5">Options</label>
        <OptionsEditor
          options={getOptions()}
          onChange={setOptions}
          hasPerOptionAction={true}
          disabled={saving}
          source={source}
        />
      </div>
    </div>
  );

  const renderImageMultiSelect = () => (
    <div className="space-y-1.5">
      {data.image && (
        <div>
          <label className="text-xs font-semibold block mb-0.5">Image</label>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={data.image}
            alt="question image"
            className="max-w-full max-h-32 border border-gray-200 rounded"
          />
        </div>
      )}
      <div>
        <label className="text-xs font-semibold block mb-0.5">Options</label>
        <OptionsEditor
          options={getOptions()}
          onChange={setOptions}
          hasPerOptionAction={false}
          disabled={saving}
          source={source}
        />
      </div>
      <div>
        <label className="text-xs font-semibold block mb-0.5">Next Action</label>
        <ActionEditor
          value={getNextAction()}
          onChange={setNextAction}
          disabled={saving}
          source={source}
        />
      </div>
    </div>
  );

  const renderConditional = () => (
    <RulesEditor
      rules={getRules()}
      defaultAction={getDefault()}
      onChange={handleRulesChange}
      disabled={saving}
      source={source}
    />
  );

  const renderTypeSpecific = () => {
    switch (qType) {
      case "free_text":
        return renderFreeText();
      case "free_text_with_fields":
        return renderFreeTextWithFields();
      case "number_range":
        return renderNumberRange();
      case "single_select":
      case "age_filter":
      case "gender_filter":
        // age_filter and gender_filter use the same options-with-per-option-action
        // structure as single_select (not rules like conditional).
        return renderSingleSelect();
      case "multi_select":
        return renderMultiSelect();
      case "image_single_select":
        return renderImageSingleSelect();
      case "image_multi_select":
        return renderImageMultiSelect();
      case "conditional":
        return renderConditional();
      default:
        return (
          <div className="text-xs text-gray-500">
            No structured editor for type &quot;{qType}&quot;.
          </div>
        );
    }
  };

  return (
    <div className="mt-2">
      <div className="flex items-center gap-1.5 mb-1.5">
        <b className="text-sm">Edit Question</b>
        {status && <span className="ml-auto text-xs text-gray-500">{status}</span>}
      </div>

      {/* QID — read-only */}
      <div className="mb-1.5">
        <label className="text-xs font-semibold block mb-0.5">QID</label>
        <code className="text-xs bg-gray-50 px-1.5 py-0.5 rounded block">{data.id}</code>
      </div>

      {/* Question text — editable textarea */}
      <div className="mb-1.5">
        <label className="text-xs font-semibold block mb-0.5">Question</label>
        <textarea
          className="w-full h-16 text-[13px] p-1.5 border border-gray-200 rounded"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          disabled={saving}
        />
      </div>

      {/* Question type — editable dropdown */}
      <div className="mb-2">
        <label className="text-xs font-semibold block mb-0.5">Question Type</label>
        <select
          className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
          value={qType}
          onChange={(e) => handleTypeChange(e.target.value)}
          disabled={saving}
        >
          {questionTypes.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
          {/* If current type is not in the list, still show it */}
          {!(questionTypes as readonly string[]).includes(qType) && qType && (
            <option value={qType}>{qType}</option>
          )}
        </select>
        <div className="text-[11px] text-gray-400 mt-0.5">
          {source === "opd" ? "OPD" : "OLDCARTS"} — tests will validate compatibility on save.
        </div>
      </div>

      {/* Type-specific fields */}
      <div className="mb-2">{renderTypeSpecific()}</div>

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

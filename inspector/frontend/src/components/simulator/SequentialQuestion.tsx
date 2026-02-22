"use client";

import { useState } from "react";
import type { RawQuestion, TextOverride } from "@/lib/types/simulator";
import EditableText from "./EditableText";

interface SequentialQuestionProps {
  question: RawQuestion;
  onSubmit: (value: unknown) => void;
  textOverrides: Record<string, TextOverride>;
  onOverrideText: (qid: string, text: string) => void;
  onOverrideOptionLabel: (qid: string, optionId: string, label: string) => void;
  phaseName: string;
}

/**
 * Renders a single question for phases 4 (OLDCARTS) and 5 (OPD).
 * Adapts its UI based on question_type: free_text, single_select,
 * multi_select, number_range, image variants, free_text_with_fields.
 */
export default function SequentialQuestion({
  question,
  onSubmit,
  textOverrides,
  onOverrideText,
  onOverrideOptionLabel,
  phaseName,
}: SequentialQuestionProps) {
  const [textValue, setTextValue] = useState("");
  const [selectedOption, setSelectedOption] = useState("");
  const [selectedOptions, setSelectedOptions] = useState<string[]>([]);
  const [numberValue, setNumberValue] = useState(question.default_value ?? question.min_value ?? 0);
  const [fieldValues, setFieldValues] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const f of question.fields ?? []) init[f.id] = "";
    return init;
  });

  const displayQuestion =
    textOverrides[question.qid]?.questionText ?? question.question;
  const overrideLabels = textOverrides[question.qid]?.optionLabels ?? {};

  const handleSubmit = () => {
    const qt = question.question_type;
    if (qt === "free_text") {
      onSubmit(textValue);
    } else if (qt === "single_select" || qt === "image_single_select") {
      if (!selectedOption) return;
      onSubmit(selectedOption);
    } else if (qt === "multi_select" || qt === "image_multi_select") {
      onSubmit(selectedOptions);
    } else if (qt === "number_range") {
      onSubmit(numberValue);
    } else if (qt === "free_text_with_fields") {
      onSubmit(fieldValues);
    } else {
      // Fallback for unknown types
      onSubmit(textValue);
    }
  };

  const qt = question.question_type;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-blue-500 bg-blue-50 px-2 py-0.5 rounded">
          {phaseName}
        </span>
        <span className="text-xs text-gray-400">{question.qid}</span>
      </div>

      <EditableText
        text={displayQuestion}
        onSave={(t) => onOverrideText(question.qid, t)}
        as="h3"
        className="text-base font-semibold text-gray-800"
      />

      {/* Image (if present) */}
      {question.image && (
        <div className="border border-gray-200 rounded p-2 bg-gray-50">
          <img
            src={`/assets/${question.image}`}
            alt="Question image"
            className="max-w-full max-h-96 object-contain mx-auto"
          />
        </div>
      )}

      {/* Free text */}
      {(qt === "free_text") && (
        <textarea
          value={textValue}
          onChange={(e) => setTextValue(e.target.value)}
          rows={3}
          className="w-full border border-gray-300 rounded px-3 py-2 text-sm resize-y"
          placeholder="Type your answer..."
        />
      )}

      {/* Single select (radio buttons) */}
      {(qt === "single_select" || qt === "image_single_select") && (
        <div className="space-y-2">
          {(question.options ?? []).map((opt) => {
            const displayLabel = overrideLabels[opt.id] ?? opt.label;
            return (
              <label
                key={opt.id}
                className={`flex items-center gap-3 p-2.5 rounded border cursor-pointer transition-colors ${
                  selectedOption === opt.id
                    ? "bg-blue-50 border-blue-300"
                    : "bg-white border-gray-200 hover:bg-gray-50"
                }`}
              >
                <input
                  type="radio"
                  name={question.qid}
                  value={opt.id}
                  checked={selectedOption === opt.id}
                  onChange={() => setSelectedOption(opt.id)}
                  className="text-blue-500"
                />
                <EditableText
                  text={displayLabel}
                  onSave={(t) => onOverrideOptionLabel(question.qid, opt.id, t)}
                  className="text-sm text-gray-700"
                />
              </label>
            );
          })}
        </div>
      )}

      {/* Multi select (checkboxes) */}
      {(qt === "multi_select" || qt === "image_multi_select") && (
        <div className="space-y-2">
          {(question.options ?? []).map((opt) => {
            const displayLabel = overrideLabels[opt.id] ?? opt.label;
            const checked = selectedOptions.includes(opt.id);
            return (
              <label
                key={opt.id}
                className={`flex items-center gap-3 p-2.5 rounded border cursor-pointer transition-colors ${
                  checked
                    ? "bg-blue-50 border-blue-300"
                    : "bg-white border-gray-200 hover:bg-gray-50"
                }`}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => {
                    setSelectedOptions((prev) =>
                      checked
                        ? prev.filter((id) => id !== opt.id)
                        : [...prev, opt.id]
                    );
                  }}
                  className="rounded text-blue-500"
                />
                <EditableText
                  text={displayLabel}
                  onSave={(t) => onOverrideOptionLabel(question.qid, opt.id, t)}
                  className="text-sm text-gray-700"
                />
              </label>
            );
          })}
        </div>
      )}

      {/* Number range (slider + number input) */}
      {qt === "number_range" && (
        <div className="space-y-2">
          <div className="flex items-center gap-4">
            <input
              type="range"
              min={question.min_value ?? 0}
              max={question.max_value ?? 100}
              step={question.step ?? 1}
              value={numberValue}
              onChange={(e) => setNumberValue(Number(e.target.value))}
              className="flex-1"
            />
            <input
              type="number"
              min={question.min_value ?? 0}
              max={question.max_value ?? 100}
              step={question.step ?? 1}
              value={numberValue}
              onChange={(e) => setNumberValue(Number(e.target.value))}
              className="w-20 border border-gray-300 rounded px-2 py-1 text-sm text-center"
            />
          </div>
          <div className="flex justify-between text-xs text-gray-400">
            <span>{question.min_value ?? 0}</span>
            <span>{question.max_value ?? 100}</span>
          </div>
        </div>
      )}

      {/* Free text with fields (multiple sub-fields) */}
      {qt === "free_text_with_fields" && (
        <div className="space-y-3">
          {(question.fields ?? []).map((field) => (
            <div key={field.id} className="flex flex-col gap-1">
              <label className="text-sm font-medium text-gray-600">
                {field.label ?? field.id}
              </label>
              <textarea
                value={fieldValues[field.id] ?? ""}
                onChange={(e) =>
                  setFieldValues((prev) => ({
                    ...prev,
                    [field.id]: e.target.value,
                  }))
                }
                rows={2}
                className="border border-gray-300 rounded px-2 py-1.5 text-sm resize-y"
                placeholder={field.label ?? field.id}
              />
            </div>
          ))}
        </div>
      )}

      <button
        onClick={handleSubmit}
        className="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors text-sm font-medium"
      >
        Submit
      </button>
    </div>
  );
}

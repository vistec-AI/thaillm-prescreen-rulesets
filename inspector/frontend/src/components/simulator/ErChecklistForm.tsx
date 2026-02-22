"use client";

import { useState } from "react";
import type { TextOverride } from "@/lib/types/simulator";
import { getErChecklistItems } from "@/lib/simulator/engine";
import type { SimulatorDataResponse } from "@/lib/types/simulator";
import EditableText from "./EditableText";

interface ErChecklistFormProps {
  symptoms: string[];
  age: number | null;
  ruleData: SimulatorDataResponse;
  onSubmit: (flags: Record<string, boolean>) => void;
  textOverrides: Record<string, TextOverride>;
  onOverrideText: (qid: string, text: string) => void;
}

/**
 * Phase 3 form: age-dependent ER checklist yes/no toggles.
 * Items are filtered based on the patient's age and selected symptoms.
 */
export default function ErChecklistForm({
  symptoms,
  age,
  ruleData,
  onSubmit,
  textOverrides,
  onOverrideText,
}: ErChecklistFormProps) {
  const items = getErChecklistItems(symptoms, age, ruleData);

  const [flags, setFlags] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {};
    for (const item of items) init[item.qid] = false;
    return init;
  });

  const toggle = (qid: string) => {
    setFlags((prev) => ({ ...prev, [qid]: !prev[qid] }));
  };

  if (items.length === 0) {
    return (
      <div className="space-y-4">
        <h3 className="text-lg font-semibold text-gray-800">ER Checklist</h3>
        <p className="text-sm text-gray-500">
          No ER checklist items for the selected symptoms.
        </p>
        <button
          onClick={() => onSubmit({})}
          className="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors text-sm font-medium"
        >
          Next
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-800">ER Checklist</h3>
      <p className="text-sm text-gray-500">
        {age !== null && age < 15 ? "Pediatric" : "Adult"} checklist for:{" "}
        {symptoms.join(", ")}
      </p>
      <div className="space-y-2">
        {items.map((item) => {
          const displayText =
            textOverrides[item.qid]?.questionText ?? item.text;
          const isYes = flags[item.qid];
          return (
            <div
              key={item.qid}
              className={`flex items-center justify-between p-3 rounded border transition-colors ${
                isYes
                  ? "bg-orange-50 border-orange-300"
                  : "bg-white border-gray-200"
              }`}
            >
              <div className="flex-1 mr-3">
                <EditableText
                  text={displayText}
                  onSave={(t) => onOverrideText(item.qid, t)}
                  className="text-sm text-gray-700"
                />
                <span className="text-xs text-gray-400 block mt-0.5">
                  {item.qid} ({item.symptom})
                </span>
              </div>
              <button
                onClick={() => toggle(item.qid)}
                className={`relative w-12 h-6 rounded-full transition-colors flex-shrink-0 ${
                  isYes ? "bg-orange-500" : "bg-gray-300"
                }`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${
                    isYes ? "translate-x-6" : ""
                  }`}
                />
              </button>
              <span
                className={`ml-2 text-xs font-semibold w-6 ${
                  isYes ? "text-orange-600" : "text-gray-400"
                }`}
              >
                {isYes ? "Yes" : "No"}
              </span>
            </div>
          );
        })}
      </div>
      <button
        onClick={() => onSubmit(flags)}
        className="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors text-sm font-medium"
      >
        Next
      </button>
    </div>
  );
}

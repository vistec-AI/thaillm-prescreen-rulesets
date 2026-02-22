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
        <h3 className="text-lg font-semibold text-gray-800">
          รายการตรวจคัดกรอง ER
        </h3>
        <p className="text-sm text-gray-500">
          ไม่มีรายการตรวจ ER สำหรับอาการที่เลือก
        </p>
        <div className="sticky-submit">
          <button
            onClick={() => onSubmit({})}
            className="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors text-sm font-medium"
          >
            ถัดไป
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="bg-orange-50 border-l-4 border-orange-500 p-3 rounded-r">
        <h3 className="text-lg font-semibold text-orange-800">
          รายการตรวจคัดกรอง ER
        </h3>
        <p className="text-sm text-orange-600">
          {age !== null && age < 15 ? "เด็ก" : "ผู้ใหญ่"} — อาการ:{" "}
          {symptoms.join(", ")}
        </p>
      </div>

      <p className="text-xs text-gray-400 text-right">
        {items.length} รายการ
      </p>

      <div className="space-y-2">
        {items.map((item, idx) => {
          const displayText =
            textOverrides[item.qid]?.questionText ?? item.text;
          const isYes = flags[item.qid];
          return (
            <div
              key={item.qid}
              className={`flex items-center justify-between p-3 rounded-lg border transition-colors ${
                isYes
                  ? "bg-orange-50 border-orange-300"
                  : "bg-white border-gray-200"
              }`}
            >
              <div className="flex-1 mr-3">
                <span className="text-xs text-gray-400 mr-1">{idx + 1}.</span>
                <EditableText
                  text={displayText}
                  onSave={(t) => onOverrideText(item.qid, t)}
                  className="text-sm text-gray-700"
                />
                <span className="text-xs text-gray-400 block mt-0.5 mobile-hide">
                  {item.qid} ({item.symptom})
                </span>
              </div>
              <button
                onClick={() => toggle(item.qid)}
                className={`toggle-switch relative w-12 h-6 rounded-full transition-colors flex-shrink-0 ${
                  isYes ? "bg-orange-500" : "bg-gray-300"
                }`}
              >
                <span
                  className={`toggle-thumb absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${
                    isYes ? "translate-x-6" : ""
                  }`}
                />
              </button>
              <span
                className={`ml-2 text-xs font-semibold w-10 ${
                  isYes ? "text-orange-600" : "text-gray-400"
                }`}
              >
                {isYes ? "ใช่" : "ไม่ใช่"}
              </span>
            </div>
          );
        })}
      </div>
      <div className="sticky-submit">
        <button
          onClick={() => onSubmit(flags)}
          className="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors text-sm font-medium"
        >
          ถัดไป
        </button>
      </div>
    </div>
  );
}

"use client";

import { useState } from "react";
import type { RawErCriticalItem, TextOverride } from "@/lib/types/simulator";
import EditableText from "./EditableText";

interface ErCriticalFormProps {
  items: RawErCriticalItem[];
  onSubmit: (flags: Record<string, boolean>) => void;
  textOverrides: Record<string, TextOverride>;
  onOverrideText: (qid: string, text: string) => void;
}

/**
 * Phase 1 form: 11 ER critical yes/no toggle switches.
 * Any "Yes" answer triggers immediate emergency termination.
 */
export default function ErCriticalForm({
  items,
  onSubmit,
  textOverrides,
  onOverrideText,
}: ErCriticalFormProps) {
  const [flags, setFlags] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {};
    for (const item of items) init[item.qid] = false;
    return init;
  });

  const toggle = (qid: string) => {
    setFlags((prev) => ({ ...prev, [qid]: !prev[qid] }));
  };

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-800">ER Critical Screen</h3>
      <p className="text-sm text-gray-500">
        Any positive answer will route the patient directly to Emergency.
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
                  ? "bg-red-50 border-red-300"
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
                  {item.qid}
                </span>
              </div>
              <button
                onClick={() => toggle(item.qid)}
                className={`relative w-12 h-6 rounded-full transition-colors flex-shrink-0 ${
                  isYes ? "bg-red-500" : "bg-gray-300"
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
                  isYes ? "text-red-600" : "text-gray-400"
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

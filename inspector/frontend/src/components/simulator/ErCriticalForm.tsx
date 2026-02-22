"use client";

import { useState } from "react";
import type { RawErCriticalItem, TextOverride } from "@/lib/types/simulator";
import EditableText from "./EditableText";

/** Threshold (in characters) for collapsing long question text on mobile */
const LONG_TEXT_THRESHOLD = 80;

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

  // Track which long questions are expanded (for mobile line-clamp)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const toggle = (qid: string) => {
    setFlags((prev) => ({ ...prev, [qid]: !prev[qid] }));
  };

  const toggleExpand = (qid: string) => {
    setExpanded((prev) => ({ ...prev, [qid]: !prev[qid] }));
  };

  return (
    <div className="space-y-4">
      {/* Urgency-styled header to convey ER severity */}
      <div className="bg-red-50 border-l-4 border-red-500 p-3 rounded-r">
        <h3 className="text-lg font-semibold text-red-800">
          คัดกรองภาวะฉุกเฉิน
        </h3>
        <p className="text-sm text-red-600">
          หากตอบ &quot;ใช่&quot; ข้อใดข้อหนึ่ง ผู้ป่วยจะถูกส่งไปห้องฉุกเฉินทันที
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
          const isLong = displayText.length > LONG_TEXT_THRESHOLD;
          const isExpanded = expanded[item.qid];
          return (
            <div
              key={item.qid}
              className={`flex items-center justify-between p-3 rounded-lg border transition-colors ${
                isYes
                  ? "bg-red-50 border-red-300"
                  : "bg-white border-gray-200"
              }`}
            >
              <div className="flex-1 mr-3">
                {/* Question number badge for mobile progress tracking */}
                <span className="text-xs text-gray-400 mr-1">{idx + 1}.</span>
                {/* Wrap in clampable container; CSS only applies inside .mobile-preview */}
                <div
                  className={
                    isLong && !isExpanded ? "er-question-clamp" : ""
                  }
                >
                  <EditableText
                    text={displayText}
                    onSave={(t) => onOverrideText(item.qid, t)}
                    className="text-sm text-gray-700"
                  />
                </div>
                {/* Expand/collapse toggle — only visible in mobile via CSS */}
                {isLong && (
                  <button
                    onClick={() => toggleExpand(item.qid)}
                    className="text-xs text-blue-500 mt-1 hover:underline er-expand-btn"
                  >
                    {isExpanded ? "ย่อ" : "อ่านเพิ่มเติม..."}
                  </button>
                )}
                <span className="text-xs text-gray-400 block mt-0.5 mobile-hide">
                  {item.qid}
                </span>
              </div>
              <button
                onClick={() => toggle(item.qid)}
                className={`toggle-switch relative w-12 h-6 rounded-full transition-colors flex-shrink-0 ${
                  isYes ? "bg-red-500" : "bg-gray-300"
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
                  isYes ? "text-red-600" : "text-gray-400"
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

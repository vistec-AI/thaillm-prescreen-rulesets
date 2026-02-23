"use client";

import type { ErChecklistItem } from "@/lib/types";
import Badge from "../shared/Badge";

interface Props {
  items: ErChecklistItem[];
  selectedQid: string | null;
  onSelect: (item: ErChecklistItem) => void;
}

export default function ErTable({ items, selectedQid, onSelect }: Props) {
  if (items.length === 0) {
    return (
      <div className="text-center text-gray-400 py-8">No items for this symptom.</div>
    );
  }

  return (
    <div className="overflow-auto border border-gray-200">
      <table className="w-full border-collapse text-[13px]">
        <thead className="sticky top-0 z-[1]">
          <tr>
            <th className="bg-gray-100 px-2 py-1.5 text-left border-b-2 border-gray-200 whitespace-nowrap">#</th>
            <th className="bg-gray-100 px-2 py-1.5 text-left border-b-2 border-gray-200 whitespace-nowrap">QID</th>
            <th className="bg-gray-100 px-2 py-1.5 text-left border-b-2 border-gray-200">Text</th>
            <th className="bg-gray-100 px-2 py-1.5 text-left border-b-2 border-gray-200 whitespace-nowrap">Severity</th>
            <th className="bg-gray-100 px-2 py-1.5 text-left border-b-2 border-gray-200">Department</th>
            <th className="bg-gray-100 px-2 py-1.5 text-left border-b-2 border-gray-200">Reason</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => {
            // Severity-based row highlight via left border color
            const sevBorder =
              item.severity === "sev003"
                ? "border-l-[3px] border-l-red-400"
                : item.severity === "sev002_5"
                ? "border-l-[3px] border-l-orange-400"
                : "";

            return (
              <tr
                key={item.qid}
                onClick={() => onSelect(item)}
                className={`cursor-pointer transition-colors hover:bg-blue-50 ${
                  selectedQid === item.qid ? "bg-blue-100" : ""
                }`}
              >
                <td className={`px-2 py-1.5 border-b border-gray-100 ${sevBorder}`}>{idx + 1}</td>
                <td className="px-2 py-1.5 border-b border-gray-100 font-mono text-[11px]">{item.qid}</td>
                <td className="px-2 py-1.5 border-b border-gray-100">{item.text}</td>
                <td className="px-2 py-1.5 border-b border-gray-100">
                  <Badge variant={item.severity}>{item.severity_label}</Badge>
                </td>
                <td className="px-2 py-1.5 border-b border-gray-100">{item.department_labels.join(", ")}</td>
                <td className="px-2 py-1.5 border-b border-gray-100 text-gray-500">{item.reason ?? ""}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

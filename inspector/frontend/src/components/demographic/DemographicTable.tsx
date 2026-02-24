"use client";

import type { DemographicItem } from "@/lib/types";
import Badge from "../shared/Badge";

interface Props {
  items: DemographicItem[];
  selectedQid: string | null;
  onSelect: (item: DemographicItem) => void;
  onAdd: () => void;
}

export default function DemographicTable({ items, selectedQid, onSelect, onAdd }: Props) {
  return (
    <div className="overflow-auto border border-gray-200">
      {/* Action bar above the table */}
      <div className="flex items-center justify-between bg-gray-50 px-2 py-1.5 border-b border-gray-200">
        <span className="text-xs text-gray-500">{items.length} field(s)</span>
        <button
          className="px-2.5 py-1 text-xs bg-green-600 text-white rounded hover:bg-green-700"
          onClick={onAdd}
        >
          + Add Field
        </button>
      </div>
      {items.length === 0 ? (
        <div className="text-center text-gray-400 py-8">No demographic fields loaded.</div>
      ) : (
      <table className="w-full border-collapse text-[13px]">
        <thead className="sticky top-0 z-[1]">
          <tr>
            <th className="bg-gray-100 px-2 py-1.5 text-left border-b-2 border-gray-200 whitespace-nowrap">#</th>
            <th className="bg-gray-100 px-2 py-1.5 text-left border-b-2 border-gray-200 whitespace-nowrap">QID</th>
            <th className="bg-gray-100 px-2 py-1.5 text-left border-b-2 border-gray-200 whitespace-nowrap">Key</th>
            <th className="bg-gray-100 px-2 py-1.5 text-left border-b-2 border-gray-200">Field Name</th>
            <th className="bg-gray-100 px-2 py-1.5 text-left border-b-2 border-gray-200">Field Name (TH)</th>
            <th className="bg-gray-100 px-2 py-1.5 text-left border-b-2 border-gray-200 whitespace-nowrap">Type</th>
            <th className="bg-gray-100 px-2 py-1.5 text-left border-b-2 border-gray-200 whitespace-nowrap">Optional</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => (
            <tr
              key={item.qid}
              onClick={() => onSelect(item)}
              className={`cursor-pointer transition-colors hover:bg-blue-50 ${
                selectedQid === item.qid ? "bg-blue-100" : ""
              }`}
            >
              <td className="px-2 py-1.5 border-b border-gray-100">{idx + 1}</td>
              <td className="px-2 py-1.5 border-b border-gray-100 font-mono text-[11px]">{item.qid}</td>
              <td className="px-2 py-1.5 border-b border-gray-100 font-mono text-[11px]">{item.key}</td>
              <td className="px-2 py-1.5 border-b border-gray-100">{item.field_name}</td>
              <td className="px-2 py-1.5 border-b border-gray-100">{item.field_name_th}</td>
              <td className="px-2 py-1.5 border-b border-gray-100">
                <Badge variant="type">{item.type}</Badge>
              </td>
              <td className="px-2 py-1.5 border-b border-gray-100">{item.optional ? "Yes" : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      )}
    </div>
  );
}

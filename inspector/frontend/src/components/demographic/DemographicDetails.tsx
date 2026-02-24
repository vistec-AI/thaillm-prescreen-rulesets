"use client";

import type { DemographicItem } from "@/lib/types";
import Badge from "../shared/Badge";

interface Props {
  item: DemographicItem;
  onEdit: () => void;
  onDelete: () => void;
}

export default function DemographicDetails({ item, onEdit, onDelete }: Props) {
  return (
    <div>
      <div className="mb-1">
        <b>QID</b>: <code className="text-xs bg-gray-50 px-1 rounded">{item.qid}</code>
      </div>
      <div className="mb-1">
        <b>Key</b>: <code className="text-xs bg-gray-50 px-1 rounded">{item.key}</code>
      </div>
      <div className="mb-1">
        <b>Field Name</b>: {item.field_name}
      </div>
      <div className="mb-1">
        <b>Field Name (TH)</b>: {item.field_name_th}
      </div>
      <div className="mb-1">
        <b>Type</b>: <Badge variant="type">{item.type}</Badge>
      </div>
      <div className="mb-1">
        <b>Optional</b>: {item.optional ? "Yes" : "No"}
      </div>

      {/* enum type: show allowed values */}
      {item.type === "enum" && Array.isArray(item.values) && (
        <div className="mt-2">
          <b>Values</b>:
          <ul className="list-disc pl-5 text-sm mt-0.5">
            {item.values.map((v, i) => (
              <li key={i}>{String(v)}</li>
            ))}
          </ul>
        </div>
      )}

      {/* from_yaml type: show source path + resolved values */}
      {item.type === "from_yaml" && (
        <div className="mt-2">
          {item.values_path && (
            <div className="mb-1">
              <b>Source</b>: <code className="text-xs bg-gray-50 px-1 rounded">{item.values_path}</code>
            </div>
          )}
          {Array.isArray(item.values) && (
            <>
              <b>Resolved values</b> ({item.values.length}):
              <ul className="list-disc pl-5 text-sm mt-0.5 max-h-40 overflow-auto">
                {item.values.map((v, i) => {
                  const label =
                    typeof v === "object" && v !== null && "name" in v
                      ? `${(v as Record<string, string>).name} — ${(v as Record<string, string>).name_th || ""}`
                      : String(v);
                  return <li key={i}>{label}</li>;
                })}
              </ul>
            </>
          )}
        </div>
      )}

      <div className="mt-3 flex gap-2">
        <button
          className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
          onClick={onEdit}
        >
          Edit
        </button>
        <button
          className="px-3 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700"
          onClick={onDelete}
        >
          Delete
        </button>
      </div>
    </div>
  );
}

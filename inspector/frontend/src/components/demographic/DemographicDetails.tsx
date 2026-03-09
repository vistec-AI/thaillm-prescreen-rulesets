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

      {/* Condition — show when field has conditional visibility */}
      {item.condition && (
        <div className="mt-2">
          <b>Condition</b>:{" "}
          <code className="text-xs bg-amber-50 text-amber-800 px-1.5 py-0.5 rounded border border-amber-200">
            {item.condition.field} {item.condition.op} {JSON.stringify(item.condition.value)}
          </code>
        </div>
      )}

      {/* Max Value — show for int type */}
      {item.max_value != null && (
        <div className="mt-1">
          <b>Max Value</b>: {item.max_value}
        </div>
      )}

      {/* Detail Fields — show for yes_no_detail type */}
      {item.type === "yes_no_detail" && item.detail_fields && item.detail_fields.length > 0 && (
        <div className="mt-2">
          <b>Detail Fields</b>:
          <ul className="list-disc pl-5 text-sm mt-0.5">
            {item.detail_fields.map((df, i) => (
              <li key={i}>
                <code className="text-xs bg-gray-50 px-1 rounded">{df.key}</code>{" "}
                <span className="text-gray-500">({df.type})</span> — {df.field_name_th}
              </li>
            ))}
          </ul>
        </div>
      )}

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

"use client";

import type { ErChecklistItem } from "@/lib/types";
import Badge from "../shared/Badge";

interface Props {
  item: ErChecklistItem;
  onEdit: () => void;
  onDelete: () => void;
}

export default function ErDetails({ item, onEdit, onDelete }: Props) {
  return (
    <div>
      <div className="mb-1">
        <b>QID</b>: <code className="text-xs bg-gray-50 px-1 rounded">{item.qid}</code>
      </div>
      <div className="my-1">
        <b>Text</b>: {item.text}
      </div>
      <div className="mb-1">
        <b>Severity</b>: <Badge variant={item.severity}>{item.severity_label}</Badge>{" "}
        <small className="text-gray-500">({item.severity})</small>
      </div>
      <div className="mb-1">
        <b>Department</b>: {item.department_labels.join(", ")}{" "}
        <small className="text-gray-500">({item.department.join(", ")})</small>
      </div>
      {item.reason && (
        <div className="mb-1">
          <b>Reason</b>: {item.reason}
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

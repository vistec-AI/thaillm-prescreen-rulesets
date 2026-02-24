"use client";

import type { GraphNodeData } from "@/lib/types";

interface Props {
  data: GraphNodeData;
  onEdit: () => void;
  onDelete: () => void;
}

function escapeHtml(s: unknown): string {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatDeptList(dept: unknown): string {
  const list = Array.isArray(dept) ? dept : dept ? [dept] : [];
  return list.map((d) => (typeof d === "object" && d !== null && "id" in d ? (d as { id: string }).id : String(d))).join(", ");
}

export default function GraphDetails({ data: d, onEdit, onDelete }: Props) {
  return (
    <div className="text-sm">
      <div><b>QID</b>: {d.id}</div>
      <div><b>Type</b>: {d.type || ""}</div>
      <div className="my-1"><b>Question</b>: {d.label || ""}</div>

      {d.image && (
        <div>
          <b>Image</b>:
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={d.image} alt="question image" className="max-w-full border border-gray-200 mt-1" />
        </div>
      )}

      {d.type === "number_range" && (
        <>
          <div><b>Range</b>: {d.min_value} .. {d.max_value} step {d.step}</div>
          {d.default_value !== undefined && <div><b>Default</b>: {d.default_value}</div>}
        </>
      )}

      {d.fields && (
        <div>
          <b>Fields</b>:
          <ul className="list-disc pl-5 mt-0.5">
            {d.fields.map((f, i) => <li key={i}>{f.label || f.id}</li>)}
          </ul>
        </div>
      )}

      {d.options && (
        <div>
          <b>Options</b>:
          <ul className="list-disc pl-5 mt-0.5">
            {d.options.map((o, i) => {
              const lbl = o.label || o.id || "";
              const a = o.action;
              let actionStr = "";
              if (a?.action === "goto") actionStr = `→ ${(a.qid || []).join(", ")}`;
              else if (a?.action === "opd") actionStr = "→ OPD";
              else if (a?.action === "terminate") actionStr = `↳ ${formatDeptList(a.metadata?.department)}`;
              return (
                <li key={i}>
                  {escapeHtml(lbl)} <small className="text-gray-500">{actionStr}</small>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {d.rules && (
        <div>
          <b>Rules</b>:
          <ol className="list-decimal pl-5 mt-0.5">
            {d.rules.map((r, i) => {
              const cond = (r.when || [])
                .map((w) => `${w.qid} ${w.op} ${typeof w.value === "object" ? JSON.stringify(w.value) : String(w.value)}`)
                .join(" AND ");
              const a = r.then;
              let thenStr = "";
              if (a?.action === "goto") thenStr = `goto → ${(a.qid || []).join(", ")}`;
              else if (a?.action === "terminate") thenStr = `terminate ↳ ${formatDeptList(a.metadata?.department)}`;
              return (
                <li key={i}>
                  <div><b>When</b>: {cond || "(none)"}</div>
                  <div><b>Then</b>: {thenStr}</div>
                </li>
              );
            })}
          </ol>
          {d.default && (
            <div>
              <b>Default</b>:{" "}
              {d.default.action === "goto"
                ? `goto → ${(d.default.qid || []).join(", ")}`
                : d.default.action === "terminate"
                ? `terminate ↳ ${formatDeptList(d.default.metadata?.department)}`
                : ""}
            </div>
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

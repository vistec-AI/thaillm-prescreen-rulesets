"use client";

import { useState, useEffect } from "react";

interface Props {
  /** Initial JSON value (object or array). */
  value: unknown;
  /** Called on save with the parsed object. */
  onSave: (obj: Record<string, unknown>) => Promise<void>;
  /** Called on cancel. */
  onCancel: () => void;
  /** Whether the editor controls should be disabled (e.g. during save). */
  disabled?: boolean;
}

export default function RawJsonEditor({ value, onSave, onCancel, disabled }: Props) {
  const [text, setText] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    setText(JSON.stringify(value, null, 2));
    setStatus("");
  }, [value]);

  const handleSave = async () => {
    let obj: Record<string, unknown>;
    try {
      obj = JSON.parse(text);
    } catch {
      setStatus("Invalid JSON");
      return;
    }
    setStatus("Saving...");
    try {
      await onSave(obj);
      setStatus("Saved");
    } catch (e: unknown) {
      setStatus("Error");
      const msg = e instanceof Error ? e.message : String(e);
      alert("Save error:\n" + msg);
    }
  };

  return (
    <div className="mt-2">
      <div className="flex items-center gap-1.5 mb-1">
        <b className="text-sm">Raw Editor</b>
        {status && <span className="ml-auto text-xs text-gray-500">{status}</span>}
      </div>
      <textarea
        className="w-full h-56 font-mono text-xs p-2 border border-gray-200 rounded disabled:bg-gray-50"
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={disabled}
        readOnly={disabled}
      />
      <div className="flex gap-2 mt-1.5">
        <button
          className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          onClick={handleSave}
          disabled={disabled}
        >
          Save
        </button>
        <button
          className="px-3 py-1 text-sm bg-gray-200 rounded hover:bg-gray-300 disabled:opacity-50"
          onClick={onCancel}
          disabled={disabled}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

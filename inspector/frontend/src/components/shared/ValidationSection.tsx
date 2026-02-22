"use client";

import { useApp } from "@/lib/context/AppContext";

export default function ValidationSection() {
  const { validation, validationLoading, triggerValidation } = useApp();

  return (
    <details className="mb-2">
      <summary className="cursor-pointer text-sm font-medium select-none">Validation</summary>
      <div className="flex gap-2 items-center mt-1">
        <button
          className="px-3 py-1 text-sm bg-gray-200 rounded hover:bg-gray-300 disabled:opacity-50"
          onClick={triggerValidation}
          disabled={validationLoading}
        >
          Run tests
        </button>
        {validationLoading && <span className="text-xs text-gray-500">Running tests...</span>}
        {!validationLoading && validation && (
          <span className={`text-xs font-semibold ${validation.ok ? "text-green-700" : "text-red-700"}`}>
            {validation.ok ? "OK" : "FAILED"}
          </span>
        )}
      </div>
      {validation && (
        <pre className="text-xs leading-tight max-h-32 overflow-auto bg-gray-50 p-1.5 rounded border border-gray-100 mt-1">
          {(validation.stdout || "") + (validation.stderr || "")}
        </pre>
      )}
    </details>
  );
}

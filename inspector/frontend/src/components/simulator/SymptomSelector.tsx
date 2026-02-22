"use client";

import { useState } from "react";
import type { ConstantEntry } from "@/lib/types/simulator";

interface SymptomSelectorProps {
  /** NHSO symptom list (id = English name, name_th = Thai name) */
  symptoms: ConstantEntry[];
  /** Available symptoms that have OLDCARTS/OPD rules */
  availableSymptoms: string[];
  onSubmit: (value: {
    primary_symptom: string;
    secondary_symptoms: string[];
  }) => void;
}

/**
 * Phase 2 form: primary symptom dropdown + secondary symptoms multi-select.
 */
export default function SymptomSelector({
  symptoms,
  availableSymptoms,
  onSubmit,
}: SymptomSelectorProps) {
  const [primary, setPrimary] = useState("");
  const [secondary, setSecondary] = useState<string[]>([]);

  // Filter symptoms to only those with available rules
  const available = symptoms.filter((s) =>
    availableSymptoms.includes(s.name ?? s.id)
  );

  const toggleSecondary = (name: string) => {
    setSecondary((prev) =>
      prev.includes(name) ? prev.filter((s) => s !== name) : [...prev, name]
    );
  };

  const handleSubmit = () => {
    if (!primary) return;
    onSubmit({
      primary_symptom: primary,
      secondary_symptoms: secondary.filter((s) => s !== primary),
    });
  };

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-800">Symptom Selection</h3>

      {/* Primary symptom */}
      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">
          Primary Symptom
        </label>
        <select
          value={primary}
          onChange={(e) => setPrimary(e.target.value)}
          className="border border-gray-300 rounded px-2 py-1.5 text-sm"
        >
          <option value="">-- Select primary symptom --</option>
          {available.map((s) => (
            <option key={s.id ?? s.name} value={s.name ?? s.id}>
              {s.name_th ?? s.name ?? s.id}{" "}
              {s.name && s.name_th ? `(${s.name})` : ""}
            </option>
          ))}
        </select>
      </div>

      {/* Secondary symptoms */}
      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">
          Secondary Symptoms (optional)
        </label>
        <div className="max-h-40 overflow-y-auto border border-gray-300 rounded p-2 space-y-1">
          {available
            .filter((s) => (s.name ?? s.id) !== primary)
            .map((s) => {
              const name = s.name ?? s.id;
              return (
                <label
                  key={s.id ?? s.name}
                  className="flex items-center gap-2 text-sm cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={secondary.includes(name)}
                    onChange={() => toggleSecondary(name)}
                    className="rounded"
                  />
                  {s.name_th ?? name}{" "}
                  {s.name_th ? `(${name})` : ""}
                </label>
              );
            })}
        </div>
      </div>

      <button
        onClick={handleSubmit}
        disabled={!primary}
        className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
          primary
            ? "bg-blue-500 text-white hover:bg-blue-600"
            : "bg-gray-300 text-gray-500 cursor-not-allowed"
        }`}
      >
        Next
      </button>
    </div>
  );
}

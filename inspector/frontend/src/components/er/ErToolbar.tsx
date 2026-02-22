"use client";

interface Props {
  mode: string;
  onModeChange: (mode: string) => void;
  symptoms: string[];
  symptom: string;
  onSymptomChange: (s: string) => void;
  symptomDisabled: boolean;
  onLoad: () => void;
}

export default function ErToolbar({
  mode,
  onModeChange,
  symptoms,
  symptom,
  onSymptomChange,
  symptomDisabled,
  onLoad,
}: Props) {
  return (
    <div className="flex gap-2 items-center flex-wrap pb-1.5">
      <label className="text-sm">
        Sub-mode:{" "}
        <select
          className="border border-gray-300 rounded px-2 py-1 text-sm"
          value={mode}
          onChange={(e) => onModeChange(e.target.value)}
        >
          <option value="er_symptom">ER Critical Symptoms</option>
          <option value="er_adult">ER Adult Checklist</option>
          <option value="er_pediatric">ER Pediatric Checklist</option>
        </select>
      </label>
      <label className="text-sm">
        Symptom:{" "}
        <select
          className="border border-gray-300 rounded px-2 py-1 text-sm disabled:bg-gray-100"
          value={symptom}
          onChange={(e) => onSymptomChange(e.target.value)}
          disabled={symptomDisabled}
        >
          {symptomDisabled ? (
            <option value="">(not applicable)</option>
          ) : (
            symptoms.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))
          )}
        </select>
      </label>
      <button
        className="px-3 py-1 text-sm bg-gray-200 rounded hover:bg-gray-300"
        onClick={onLoad}
      >
        Load
      </button>
    </div>
  );
}

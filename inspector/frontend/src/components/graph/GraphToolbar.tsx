"use client";

interface Props {
  symptoms: string[];
  symptom: string;
  onSymptomChange: (s: string) => void;
  mode: string;
  onModeChange: (m: string) => void;
  onLoad: () => void;
  onReset: () => void;
  onAdd: () => void;
}

export default function GraphToolbar({
  symptoms,
  symptom,
  onSymptomChange,
  mode,
  onModeChange,
  onLoad,
  onReset,
  onAdd,
}: Props) {
  return (
    <div className="flex gap-2 items-center flex-wrap pb-1.5">
      <label className="text-sm">
        Symptom:{" "}
        <select
          className="border border-gray-300 rounded px-2 py-1 text-sm"
          value={symptom}
          onChange={(e) => onSymptomChange(e.target.value)}
        >
          {symptoms.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>
      <label className="text-sm">
        Mode:{" "}
        <select
          className="border border-gray-300 rounded px-2 py-1 text-sm"
          value={mode}
          onChange={(e) => onModeChange(e.target.value)}
        >
          <option value="combined">Combined</option>
          <option value="oldcarts">Oldcarts</option>
          <option value="opd">OPD</option>
        </select>
      </label>
      <button className="px-3 py-1 text-sm bg-gray-200 rounded hover:bg-gray-300" onClick={onLoad}>
        Load
      </button>
      <button className="px-3 py-1 text-sm bg-gray-200 rounded hover:bg-gray-300" onClick={onReset}>
        Reset view
      </button>
      <button className="px-2.5 py-1 text-sm bg-green-600 text-white rounded hover:bg-green-700" onClick={onAdd}>
        + Add Question
      </button>
      <span className="text-xs text-gray-500 ml-1">Node colors: terminate=red, opd=blue, others=gray.</span>
    </div>
  );
}

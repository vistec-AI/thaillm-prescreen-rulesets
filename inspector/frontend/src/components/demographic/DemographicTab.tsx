"use client";

import { useState, useEffect, useCallback } from "react";
import { useApp } from "@/lib/context/AppContext";
import type { DemographicItem, DemographicResponse, MutationResult } from "@/lib/types";
import { fetchDemographic, updateDemographic, addDemographic, deleteDemographic } from "@/lib/api/demographic";
import { fetchPastHistory, updatePastHistory, addPastHistory, deletePastHistory } from "@/lib/api/pastHistory";
import { fetchPersonalHistory, updatePersonalHistory, addPersonalHistory, deletePersonalHistory } from "@/lib/api/personalHistory";
import DetailsPanel from "../shared/DetailsPanel";
import DemographicTable from "./DemographicTable";
import DemographicDetails from "./DemographicDetails";
import DemographicEditor from "./DemographicEditor";

// --- Sub-mode configuration ---

type FieldsSubMode = "demographic" | "past_history" | "personal_history";

interface SubModeConfig {
  label: string;
  qidPrefix: string;
  fetch: () => Promise<DemographicResponse>;
  update: (qid: string, payload: Record<string, unknown>) => Promise<MutationResult>;
  add: (payload: Record<string, unknown>) => Promise<MutationResult>;
  remove: (qid: string) => Promise<MutationResult>;
}

const SUB_MODE_CONFIG: Record<FieldsSubMode, SubModeConfig> = {
  demographic: {
    label: "Demographic",
    qidPrefix: "demo_",
    fetch: fetchDemographic,
    update: updateDemographic,
    add: addDemographic,
    remove: deleteDemographic,
  },
  past_history: {
    label: "Past History",
    qidPrefix: "past_",
    fetch: fetchPastHistory,
    update: updatePastHistory,
    add: addPastHistory,
    remove: deletePastHistory,
  },
  personal_history: {
    label: "Personal History",
    qidPrefix: "pers_",
    fetch: fetchPersonalHistory,
    update: updatePersonalHistory,
    add: addPersonalHistory,
    remove: deletePersonalHistory,
  },
};

const SUB_TABS: { id: FieldsSubMode; label: string }[] = [
  { id: "demographic", label: "Demographics" },
  { id: "past_history", label: "Past History" },
  { id: "personal_history", label: "Personal History" },
];

export default function DemographicTab() {
  const { reloadKey, showOverlay, hideOverlay, triggerValidation, setIsEditing } = useApp();

  const [subMode, setSubMode] = useState<FieldsSubMode>("demographic");
  const [items, setItems] = useState<DemographicItem[]>([]);
  const [selected, setSelected] = useState<DemographicItem | null>(null);
  const [editing, setEditing] = useState(false);
  /** When true the editor is in "add new" mode instead of editing an existing item. */
  const [adding, setAdding] = useState(false);

  const config = SUB_MODE_CONFIG[subMode];

  const load = useCallback(async () => {
    try {
      const res = await config.fetch();
      setItems(res.items);
      // Refresh selected item if it still exists
      if (selected) {
        const updated = res.items.find((i) => i.qid === selected.qid);
        if (updated) setSelected(updated);
      }
    } catch (e) {
      console.error(`Failed to load ${config.label} data`, e);
    }
  // config is derived from subMode which is already a dependency via the effect below
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, subMode]);

  // Load on mount, when reloadKey changes, or when sub-mode switches
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadKey, subMode]);

  // Reset selection/editing state when sub-mode changes
  const handleSubModeChange = (mode: FieldsSubMode) => {
    setSubMode(mode);
    setSelected(null);
    setEditing(false);
    setAdding(false);
    setIsEditing(false);
  };

  const handleSelect = (item: DemographicItem) => {
    setSelected(item);
    setEditing(false);
    setAdding(false);
    setIsEditing(false);
  };

  const handleEdit = () => {
    setEditing(true);
    setAdding(false);
    setIsEditing(true);
  };

  const handleCancel = () => {
    setEditing(false);
    setAdding(false);
    setIsEditing(false);
  };

  const handleSave = async (obj: Record<string, unknown>) => {
    if (!selected) return;
    showOverlay("Saving and running tests...");
    try {
      const res = await config.update(selected.qid, obj);
      if (!res.ok) {
        const detail = (res.stdout || "") + (res.stderr || "");
        alert("Save failed. Tests failed or validation error.\n" + detail);
        return;
      }
      setEditing(false);
      setIsEditing(false);
      await load();
      await triggerValidation();
    } finally {
      hideOverlay();
    }
  };

  // --- Add new item ---
  const handleAdd = () => {
    setSelected(null);
    setEditing(false);
    setAdding(true);
    setIsEditing(true);
  };

  const handleAddSave = async (obj: Record<string, unknown>) => {
    showOverlay("Adding and running tests...");
    try {
      const res = await config.add(obj);
      if (!res.ok) {
        const detail = (res.error || "") + (res.stdout || "") + (res.stderr || "");
        alert("Add failed. Tests failed or validation error.\n" + detail);
        return;
      }
      setAdding(false);
      setIsEditing(false);
      await load();
      await triggerValidation();
    } finally {
      hideOverlay();
    }
  };

  // --- Delete item ---
  const handleDelete = async () => {
    if (!selected) return;
    if (!confirm(`Delete ${config.label.toLowerCase()} field "${selected.qid}"?\n\nThis will remove it from the YAML file and run tests to validate.`)) {
      return;
    }
    showOverlay("Deleting and running tests...");
    try {
      const res = await config.remove(selected.qid);
      if (!res.ok) {
        const detail = (res.error || "") + (res.stdout || "") + (res.stderr || "");
        alert("Delete failed. Tests failed or validation error.\n" + detail);
        return;
      }
      setSelected(null);
      setEditing(false);
      setIsEditing(false);
      await load();
      await triggerValidation();
    } finally {
      hideOverlay();
    }
  };

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Sub-tab bar */}
      <div className="flex gap-0 border-b border-gray-200 mb-2">
        {SUB_TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => handleSubModeChange(tab.id)}
            className={`px-3 py-1.5 text-xs font-medium transition-colors -mb-[1px] border-b-2 ${
              subMode === tab.id
                ? "text-blue-700 border-b-blue-500 font-semibold"
                : "text-gray-500 border-b-transparent hover:text-gray-700"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex-1 grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_320px] lg:grid-cols-[minmax(0,1fr)_380px] xl:grid-cols-[minmax(0,1fr)_420px] 2xl:grid-cols-[minmax(0,1fr)_480px] gap-3 min-h-0">
        <DemographicTable items={items} selectedQid={selected?.qid ?? null} onSelect={handleSelect} onAdd={handleAdd} />

        <DetailsPanel>
          <h4 className="text-base font-semibold m-0 mb-2">Details</h4>
          {adding ? (
            <DemographicEditor
              item={null}
              isNew
              label={config.label}
              qidPrefix={config.qidPrefix}
              onSave={handleAddSave}
              onCancel={handleCancel}
            />
          ) : !selected ? (
            <div className="text-gray-400 text-sm">Click a row to inspect its details.</div>
          ) : editing ? (
            <DemographicEditor
              item={selected}
              label={config.label}
              qidPrefix={config.qidPrefix}
              onSave={handleSave}
              onCancel={handleCancel}
            />
          ) : (
            <DemographicDetails item={selected} onEdit={handleEdit} onDelete={handleDelete} />
          )}
        </DetailsPanel>
      </div>
    </div>
  );
}

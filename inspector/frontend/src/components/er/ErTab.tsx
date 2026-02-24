"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useApp } from "@/lib/context/AppContext";
import type { ErChecklistItem, ErSymptomsResponse } from "@/lib/types";
import { fetchErSymptoms, fetchErChecklist, updateErQuestion, addErQuestion, deleteErQuestion } from "@/lib/api/er";
import DetailsPanel from "../shared/DetailsPanel";
import ErToolbar from "./ErToolbar";
import ErTable from "./ErTable";
import ErDetails from "./ErDetails";
import ErEditor from "./ErEditor";

export default function ErTab() {
  const { reloadKey, showOverlay, hideOverlay, triggerValidation, setIsEditing } = useApp();

  const [mode, setMode] = useState("er_symptom");
  const [symptom, setSymptom] = useState("");
  const [symptoms, setSymptoms] = useState<string[]>([]);
  const [erSymptomCache, setErSymptomCache] = useState<ErSymptomsResponse | null>(null);
  const [items, setItems] = useState<ErChecklistItem[]>([]);
  const [selected, setSelected] = useState<ErChecklistItem | null>(null);
  const [editing, setEditing] = useState(false);
  /** When true the editor is in "add new" mode instead of editing an existing item. */
  const [adding, setAdding] = useState(false);

  const modeRef = useRef(mode);
  modeRef.current = mode;
  const symptomRef = useRef(symptom);
  symptomRef.current = symptom;

  // Load the ER symptom lists (cached)
  const loadErSymptoms = useCallback(async () => {
    if (erSymptomCache) return erSymptomCache;
    const data = await fetchErSymptoms();
    setErSymptomCache(data);
    return data;
  }, [erSymptomCache]);

  // Update the symptom dropdown when mode changes
  const updateSymptomDropdown = useCallback(
    async (m: string) => {
      if (m === "er_symptom") {
        setSymptoms([]);
        setSymptom("");
        return;
      }
      const cache = await loadErSymptoms();
      const list = m === "er_adult" ? cache.adult : cache.pediatric;
      setSymptoms(list);
      setSymptom(list[0] ?? "");
    },
    [loadErSymptoms],
  );

  // Load checklist for current mode + symptom
  const loadChecklist = useCallback(async () => {
    const m = modeRef.current;
    const s = symptomRef.current;
    if (m !== "er_symptom" && !s) return;
    try {
      const data = await fetchErChecklist(m, m !== "er_symptom" ? s : undefined);
      setItems(data.items);
      if (selected) {
        const updated = data.items.find((i) => i.qid === selected.qid);
        if (updated) setSelected(updated);
      }
    } catch (e) {
      console.error("Failed to load ER checklist", e);
      setItems([]);
    }
  }, [selected]);

  // Initial load
  useEffect(() => {
    updateSymptomDropdown(mode).then(() => loadChecklist());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reload when version changes
  useEffect(() => {
    if (reloadKey > 0) loadChecklist();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadKey]);

  const handleModeChange = async (m: string) => {
    setMode(m);
    modeRef.current = m;
    setSelected(null);
    setEditing(false);
    setAdding(false);
    setIsEditing(false);
    await updateSymptomDropdown(m);
    // Need to wait a tick for symptomRef to update
    setTimeout(() => loadChecklist(), 0);
  };

  const handleSymptomChange = (s: string) => {
    setSymptom(s);
    symptomRef.current = s;
    loadChecklist();
  };

  const handleSelect = (item: ErChecklistItem) => {
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

  const handleSave = async (data: Record<string, unknown>) => {
    if (!selected) return;
    showOverlay("Saving and running tests...");
    try {
      const res = await updateErQuestion({
        mode,
        symptom: symptom || null,
        qid: selected.qid,
        data,
      });
      if (!res.ok) {
        const detail = (res.stdout || "") + (res.stderr || "");
        alert("Save failed. Tests failed or validation error.\n" + detail);
        return;
      }
      setEditing(false);
      setIsEditing(false);
      await loadChecklist();
      await triggerValidation();
    } finally {
      hideOverlay();
    }
  };

  // --- Add new item ---
  const handleAdd = () => {
    // For adult/pediatric modes, a symptom must be selected before adding
    if (mode !== "er_symptom" && !symptom) {
      alert("Please select a symptom first.");
      return;
    }
    setSelected(null);
    setEditing(false);
    setAdding(true);
    setIsEditing(true);
  };

  const handleAddSave = async (data: Record<string, unknown>) => {
    showOverlay("Adding and running tests...");
    try {
      const res = await addErQuestion({
        mode,
        symptom: symptom || null,
        data,
      });
      if (!res.ok) {
        const detail = (res.error || "") + (res.stdout || "") + (res.stderr || "");
        alert("Add failed. Tests failed or validation error.\n" + detail);
        return;
      }
      setAdding(false);
      setIsEditing(false);
      await loadChecklist();
      await triggerValidation();
    } finally {
      hideOverlay();
    }
  };

  // --- Delete item ---
  const handleDelete = async () => {
    if (!selected) return;
    if (!confirm(`Delete ER checklist item "${selected.qid}"?\n\nThis will remove it from the YAML file and run tests to validate.`)) {
      return;
    }
    showOverlay("Deleting and running tests...");
    try {
      const res = await deleteErQuestion({
        mode,
        symptom: symptom || null,
        qid: selected.qid,
      });
      if (!res.ok) {
        const detail = (res.error || "") + (res.stdout || "") + (res.stderr || "");
        alert("Delete failed. Tests failed or validation error.\n" + detail);
        return;
      }
      setSelected(null);
      setEditing(false);
      setIsEditing(false);
      await loadChecklist();
      await triggerValidation();
    } finally {
      hideOverlay();
    }
  };

  const handleLoad = async () => {
    await loadChecklist();
    await triggerValidation();
  };

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <ErToolbar
        mode={mode}
        onModeChange={handleModeChange}
        symptoms={symptoms}
        symptom={symptom}
        onSymptomChange={handleSymptomChange}
        symptomDisabled={mode === "er_symptom"}
        onLoad={handleLoad}
      />

      <div className="flex-1 grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_320px] lg:grid-cols-[minmax(0,1fr)_380px] xl:grid-cols-[minmax(0,1fr)_420px] 2xl:grid-cols-[minmax(0,1fr)_480px] gap-3 min-h-0">
        <ErTable items={items} selectedQid={selected?.qid ?? null} onSelect={handleSelect} onAdd={handleAdd} />

        <DetailsPanel>
          <h4 className="text-base font-semibold m-0 mb-2">Details</h4>
          {adding ? (
            <ErEditor item={null} isNew mode={mode} onSave={handleAddSave} onCancel={handleCancel} />
          ) : !selected ? (
            <div className="text-gray-400 text-sm">Click a row to inspect its details.</div>
          ) : editing ? (
            <ErEditor item={selected} mode={mode} onSave={handleSave} onCancel={handleCancel} />
          ) : (
            <ErDetails item={selected} onEdit={handleEdit} onDelete={handleDelete} />
          )}
        </DetailsPanel>
      </div>
    </div>
  );
}

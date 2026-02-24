"use client";

import { useState, useEffect, useCallback } from "react";
import { useApp } from "@/lib/context/AppContext";
import type { DemographicItem } from "@/lib/types";
import { fetchDemographic, updateDemographic, addDemographic, deleteDemographic } from "@/lib/api/demographic";
import DetailsPanel from "../shared/DetailsPanel";
import DemographicTable from "./DemographicTable";
import DemographicDetails from "./DemographicDetails";
import DemographicEditor from "./DemographicEditor";

export default function DemographicTab() {
  const { reloadKey, showOverlay, hideOverlay, triggerValidation, setIsEditing } = useApp();

  const [items, setItems] = useState<DemographicItem[]>([]);
  const [selected, setSelected] = useState<DemographicItem | null>(null);
  const [editing, setEditing] = useState(false);
  /** When true the editor is in "add new" mode instead of editing an existing item. */
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await fetchDemographic();
      setItems(res.items);
      // Refresh selected item if it still exists
      if (selected) {
        const updated = res.items.find((i) => i.qid === selected.qid);
        if (updated) setSelected(updated);
      }
    } catch (e) {
      console.error("Failed to load demographic data", e);
    }
  }, [selected]);

  // Load on mount and when reloadKey changes (version poll detected changes)
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadKey]);

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
      const res = await updateDemographic(selected.qid, obj);
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
      const res = await addDemographic(obj);
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
    if (!confirm(`Delete demographic field "${selected.qid}"?\n\nThis will remove it from demographic.yaml and run tests to validate.`)) {
      return;
    }
    showOverlay("Deleting and running tests...");
    try {
      const res = await deleteDemographic(selected.qid);
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
      <div className="flex-1 grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_320px] lg:grid-cols-[minmax(0,1fr)_380px] xl:grid-cols-[minmax(0,1fr)_420px] 2xl:grid-cols-[minmax(0,1fr)_480px] gap-3 min-h-0">
        <DemographicTable items={items} selectedQid={selected?.qid ?? null} onSelect={handleSelect} onAdd={handleAdd} />

        <DetailsPanel>
          <h4 className="text-base font-semibold m-0 mb-2">Details</h4>
          {adding ? (
            <DemographicEditor
              item={null}
              isNew
              onSave={handleAddSave}
              onCancel={handleCancel}
            />
          ) : !selected ? (
            <div className="text-gray-400 text-sm">Click a row to inspect its details.</div>
          ) : editing ? (
            <DemographicEditor
              item={selected}
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

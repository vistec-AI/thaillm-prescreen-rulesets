"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useApp } from "@/lib/context/AppContext";
import type { GraphResponse, GraphNodeData } from "@/lib/types";
import { fetchSymptoms, fetchGraph, updateQuestion, addQuestion, deleteQuestion } from "@/lib/api/graph";
import DetailsPanel from "../shared/DetailsPanel";
import GraphToolbar from "./GraphToolbar";
import GraphEditor from "./GraphEditor";
import CytoscapeCanvas, { type CytoscapeCanvasRef } from "./CytoscapeCanvas";
import GraphDetails from "./GraphDetails";

export default function GraphTab() {
  const { activeTab, reloadKey, showOverlay, hideOverlay, triggerValidation, setIsEditing } = useApp();

  const [symptoms, setSymptoms] = useState<string[]>([]);
  const [symptom, setSymptom] = useState("");
  const [mode, setMode] = useState("combined");
  const [graphData, setGraphData] = useState<GraphResponse | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNodeData | null>(null);
  const [editing, setEditing] = useState(false);
  /** When true the editor is in "add new" mode instead of editing an existing node. */
  const [adding, setAdding] = useState(false);

  const cyRef = useRef<CytoscapeCanvasRef>(null);

  const symptomRef = useRef(symptom);
  symptomRef.current = symptom;
  const modeRef = useRef(mode);
  modeRef.current = mode;

  // Load symptoms list on mount
  useEffect(() => {
    fetchSymptoms().then((res) => {
      setSymptoms(res.symptoms);
      if (res.symptoms.length > 0) {
        setSymptom(res.symptoms[0]);
        symptomRef.current = res.symptoms[0];
      }
    });
  }, []);

  // Load graph when symptom is set
  const loadGraph = useCallback(async () => {
    const s = symptomRef.current;
    const m = modeRef.current;
    if (!s) return;
    try {
      const data = await fetchGraph(s, m);
      setGraphData(data);
      // Refresh selected node if it still exists
      if (selectedNode) {
        const nd = data.nodes.find((n) => n.data.id === selectedNode.id);
        if (nd) setSelectedNode(nd.data);
      }
    } catch (e) {
      console.error("Failed to load graph", e);
    }
  }, [selectedNode]);

  // Load graph once symptom is available
  useEffect(() => {
    if (symptom) loadGraph();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symptom]);

  // Reload when version changes
  useEffect(() => {
    if (reloadKey > 0 && symptom) loadGraph();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadKey]);

  // Resize Cytoscape when tab becomes active
  useEffect(() => {
    if (activeTab === "graph") {
      requestAnimationFrame(() => cyRef.current?.resize());
    }
  }, [activeTab]);

  const handleSymptomChange = (s: string) => {
    setSymptom(s);
    symptomRef.current = s;
    loadGraph();
  };

  const handleModeChange = (m: string) => {
    setMode(m);
    modeRef.current = m;
    loadGraph();
  };

  const handleNodeTap = useCallback((nodeData: GraphNodeData) => {
    setSelectedNode(nodeData);
    setEditing(false);
    setAdding(false);
    setIsEditing(false);
  }, [setIsEditing]);

  const handleBackgroundTap = useCallback(() => {
    setSelectedNode(null);
    setEditing(false);
    setAdding(false);
    setIsEditing(false);
  }, [setIsEditing]);

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
    if (!selectedNode) return;
    showOverlay("Saving and running tests...");
    try {
      const res = await updateQuestion({
        source: selectedNode.source || null,
        symptom: symptomRef.current,
        qid: selectedNode.id,
        data: obj,
      });
      if (!res.ok) {
        const detail = (res.stdout || "") + (res.stderr || "");
        alert("Save failed. Tests failed or validation error.\n" + detail);
        return;
      }
      setEditing(false);
      setIsEditing(false);
      await loadGraph();
      await triggerValidation();
    } finally {
      hideOverlay();
    }
  };

  // --- Add new question ---
  const handleAdd = () => {
    if (!symptom) {
      alert("Please select a symptom first.");
      return;
    }
    setSelectedNode(null);
    setEditing(false);
    setAdding(true);
    setIsEditing(true);
  };

  const handleAddSave = async (obj: Record<string, unknown>) => {
    // Extract the __source flag set by GraphEditor in add mode
    const chosenSource = (obj.__source as string) || "oldcarts";
    // Remove the transient flag before sending to the API
    const { __source, ...data } = obj;
    void __source; // suppress unused variable lint

    showOverlay("Adding and running tests...");
    try {
      const res = await addQuestion({
        source: chosenSource,
        symptom: symptomRef.current,
        data,
      });
      if (!res.ok) {
        const detail = (res.error || "") + (res.stdout || "") + (res.stderr || "");
        alert("Add failed. Tests failed or validation error.\n" + detail);
        return;
      }
      setAdding(false);
      setIsEditing(false);
      await loadGraph();
      await triggerValidation();
    } finally {
      hideOverlay();
    }
  };

  // --- Delete question ---
  const handleDelete = async () => {
    if (!selectedNode) return;
    const src = selectedNode.source;
    if (!src) {
      alert("Cannot determine source (oldcarts/opd) for this node. Try selecting a specific mode (not combined).");
      return;
    }
    if (!confirm(`Delete question "${selectedNode.id}" from ${src}.yaml?\n\nThis will remove it and run tests to validate.`)) {
      return;
    }
    showOverlay("Deleting and running tests...");
    try {
      const res = await deleteQuestion({
        source: src,
        symptom: symptomRef.current,
        qid: selectedNode.id,
      });
      if (!res.ok) {
        const detail = (res.error || "") + (res.stdout || "") + (res.stderr || "");
        alert("Delete failed. Tests failed or validation error.\n" + detail);
        return;
      }
      setSelectedNode(null);
      setEditing(false);
      setIsEditing(false);
      await loadGraph();
      await triggerValidation();
    } finally {
      hideOverlay();
    }
  };

  const handleLoad = async () => {
    await loadGraph();
    await triggerValidation();
  };

  // Derive available QIDs from graph nodes for the searchable QID picker.
  // Filters out virtual terminate nodes (IDs containing "_TERM_").
  const availableQids = useMemo(() => {
    if (!graphData) return [];
    return graphData.nodes
      .filter((n) => !n.data.id.includes("_TERM_"))
      .map((n) => ({
        id: n.data.id,
        label: n.data.label,
        type: n.data.type,
        // Carry option labels so PredicateEditor can offer dropdowns/checkboxes
        options: n.data.options?.map((o) => ({ id: o.id, label: o.label })),
        min_value: n.data.min_value,
        max_value: n.data.max_value,
        step: n.data.step,
      }));
  }, [graphData]);

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <GraphToolbar
        symptoms={symptoms}
        symptom={symptom}
        onSymptomChange={handleSymptomChange}
        mode={mode}
        onModeChange={handleModeChange}
        onLoad={handleLoad}
        onReset={() => cyRef.current?.resetView()}
        onAdd={handleAdd}
      />

      <div className="flex-1 grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_320px] lg:grid-cols-[minmax(0,1fr)_380px] xl:grid-cols-[minmax(0,1fr)_420px] 2xl:grid-cols-[minmax(0,1fr)_480px] gap-3 min-h-0">
        <CytoscapeCanvas
          ref={cyRef}
          data={graphData}
          onNodeTap={handleNodeTap}
          onBackgroundTap={handleBackgroundTap}
        />

        <DetailsPanel>
          <h4 className="text-base font-semibold m-0 mb-2">Details</h4>
          {adding ? (
            <GraphEditor
              data={null}
              isNew
              onSave={handleAddSave}
              onCancel={handleCancel}
              availableQids={availableQids}
            />
          ) : !selectedNode ? (
            <div className="text-gray-400 text-sm">Click a node to inspect its details.</div>
          ) : editing ? (
            <GraphEditor
              data={selectedNode}
              onSave={handleSave}
              onCancel={handleCancel}
              availableQids={availableQids}
            />
          ) : (
            <GraphDetails data={selectedNode} onEdit={handleEdit} onDelete={handleDelete} />
          )}
        </DetailsPanel>
      </div>
    </div>
  );
}

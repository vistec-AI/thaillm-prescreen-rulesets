"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useApp } from "@/lib/context/AppContext";
import type { GraphResponse, GraphNodeData } from "@/lib/types";
import { fetchSymptoms, fetchGraph, updateQuestion } from "@/lib/api/graph";
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
    setIsEditing(false);
  }, [setIsEditing]);

  const handleBackgroundTap = useCallback(() => {
    setSelectedNode(null);
    setEditing(false);
    setIsEditing(false);
  }, [setIsEditing]);

  const handleEdit = () => {
    setEditing(true);
    setIsEditing(true);
  };

  const handleCancel = () => {
    setEditing(false);
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

  const handleLoad = async () => {
    await loadGraph();
    await triggerValidation();
  };

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
          {!selectedNode ? (
            <div className="text-gray-400 text-sm">Click a node to inspect its details.</div>
          ) : editing ? (
            <GraphEditor
              data={selectedNode}
              onSave={handleSave}
              onCancel={handleCancel}
            />
          ) : (
            <GraphDetails data={selectedNode} onEdit={handleEdit} />
          )}
        </DetailsPanel>
      </div>
    </div>
  );
}

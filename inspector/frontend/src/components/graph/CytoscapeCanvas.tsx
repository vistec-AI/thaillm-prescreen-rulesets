"use client";

import { useEffect, useRef, useImperativeHandle, forwardRef } from "react";
import type { Core } from "cytoscape";
import type { GraphResponse, GraphNodeData } from "@/lib/types";

export interface CytoscapeCanvasRef {
  resetView: () => void;
  resize: () => void;
}

interface Props {
  data: GraphResponse | null;
  onNodeTap: (nodeData: GraphNodeData) => void;
  onBackgroundTap: () => void;
}

/**
 * Wraps Cytoscape.js in a React component.  Dynamically imports the
 * library (no SSR) and re-renders when `data` changes.
 */
const CytoscapeCanvas = forwardRef<CytoscapeCanvasRef, Props>(
  ({ data, onNodeTap, onBackgroundTap }, ref) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const cyRef = useRef<Core | null>(null);

    useImperativeHandle(ref, () => ({
      resetView: () => {
        if (cyRef.current) cyRef.current.fit(cyRef.current.elements(), 40);
      },
      resize: () => {
        if (cyRef.current) {
          cyRef.current.resize();
          cyRef.current.fit(cyRef.current.elements(), 40);
        }
      },
    }));

    useEffect(() => {
      if (!data || !containerRef.current) return;

      const elements = [
        ...data.nodes.map((n) => ({ data: n.data, group: "nodes" as const })),
        ...data.edges.map((e) => ({ data: e.data, group: "edges" as const })),
      ];

      // Dynamic import to avoid SSR
      import("cytoscape").then((mod) => {
        const cytoscape = mod.default;

        if (cyRef.current) {
          // Update existing instance
          cyRef.current.elements().remove();
          cyRef.current.add(elements);
        } else {
          // Create new instance
          cyRef.current = cytoscape({
            container: containerRef.current,
            elements,
          });

          // Style
          cyRef.current.style([
            {
              selector: "node",
              style: {
                label: "data(label)",
                "text-valign": "center",
                "background-color": "#888",
                color: "#222",
                "font-size": 10,
              },
            },
            {
              selector: 'node[type = "terminate"]',
              style: { "background-color": "#e57373", shape: "round-rectangle" },
            },
            {
              selector: 'node[type = "opd"]',
              style: { "background-color": "#64b5f6", shape: "diamond" },
            },
            {
              selector: "edge",
              style: {
                "curve-style": "bezier",
                "target-arrow-shape": "triangle",
                width: 2,
                label: "data(label)",
                "font-size": 9,
              },
            },
          ] as unknown as cytoscape.StylesheetCSS[]);

          // Events
          cyRef.current.on("tap", "node", (evt) => {
            onNodeTap(evt.target.data() as GraphNodeData);
          });
          cyRef.current.on("tap", (evt) => {
            if (evt.target === cyRef.current) onBackgroundTap();
          });
        }

        // Layout
        cyRef.current.layout({ name: "breadthfirst", directed: true, padding: 20, spacingFactor: 1.2 }).run();
        cyRef.current.resize();
        cyRef.current.fit(cyRef.current.elements(), 40);
      });

      return () => {
        // Don't destroy on data change — we reuse the instance
      };
    }, [data, onNodeTap, onBackgroundTap]);

    // Cleanup on unmount
    useEffect(() => {
      return () => {
        cyRef.current?.destroy();
        cyRef.current = null;
      };
    }, []);

    return <div ref={containerRef} className="w-full h-full border border-gray-200 min-w-0 min-h-[300px] md:min-h-0" />;
  },
);

CytoscapeCanvas.displayName = "CytoscapeCanvas";
export default CytoscapeCanvas;

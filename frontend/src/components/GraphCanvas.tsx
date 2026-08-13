import cytoscape, { type Core, type EdgeSingular, type NodeSingular } from "cytoscape";
import { useEffect, useRef, useState } from "react";

import {
  type CanvasNode,
  DEFAULT_EDGE_STYLE,
  DEFAULT_NODE_STYLE,
  EDGE_STYLE_BY_TYPE,
  NODE_STYLE_BY_LABEL,
  toElements,
} from "@/lib/graphElements";
import { litgraphApi } from "@/services/api";
import type { SubgraphEdge } from "@/types";

export type { CanvasNode } from "@/lib/graphElements";

// GRAPH-002. Shared component — FE-004 (mini panel) and GRAPH-003 (full
// explorer) both mount this with their own nodes/edges; double-click-to-
// expand calls GET /graph/subgraph itself (GRAPH-001) so every consumer
// gets the same behavior for free instead of re-implementing it. Node/edge
// styling and the Cytoscape-element mapping live in lib/graphElements.ts,
// split out so that pure logic is testable without a real DOM/Cytoscape
// instance — see graphElements.check.ts.

const DOUBLE_TAP_MS = 300;

export function GraphCanvas({
  nodes,
  edges,
  onNodeSelect,
  className,
}: {
  nodes: CanvasNode[];
  edges: SubgraphEdge[];
  onNodeSelect?: (node: CanvasNode) => void;
  className?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const hasLaidOutRef = useRef(false);
  const lastTapRef = useRef<{ id: string; time: number } | null>(null);
  const [display, setDisplay] = useState<{ nodes: CanvasNode[]; edges: SubgraphEdge[] }>({
    nodes,
    edges,
  });
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null);

  // New props reset any nodes pulled in by a prior expand-on-double-click —
  // the caller gave us a fresh base graph (new answer, new search), don't
  // carry over exploration state from the last one.
  useEffect(() => {
    hasLaidOutRef.current = false;
    setDisplay({ nodes, edges });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges]);

  // Mount cytoscape once; event handlers read live state via refs/callbacks
  // rather than being re-bound on every render.
  useEffect(() => {
    if (!containerRef.current) return;
    const cy = cytoscape({
      container: containerRef.current,
      style: [
        {
          selector: "node",
          style: {
            "background-color": (ele: NodeSingular) =>
              (NODE_STYLE_BY_LABEL[ele.data("type")] ?? DEFAULT_NODE_STYLE).color,
            shape: (ele: NodeSingular) =>
              (NODE_STYLE_BY_LABEL[ele.data("type")] ?? DEFAULT_NODE_STYLE).shape,
            width: "data(size)",
            height: "data(size)",
            label: "data(displayLabel)",
            "font-size": 9,
            color: "#1f2937",
            "text-valign": "bottom",
            "text-margin-y": 4,
            "text-wrap": "ellipsis",
            "text-max-width": "80px",
            "border-width": 2,
            "border-color": "#ffffff",
          },
        },
        {
          selector: "node:selected",
          style: { "border-width": 3, "border-color": "#111827" },
        },
        {
          selector: "edge",
          style: {
            width: (ele: EdgeSingular) =>
              (EDGE_STYLE_BY_TYPE[ele.data("relType")] ?? DEFAULT_EDGE_STYLE).width,
            "line-color": (ele: EdgeSingular) =>
              (EDGE_STYLE_BY_TYPE[ele.data("relType")] ?? DEFAULT_EDGE_STYLE).color,
            "line-style": (ele: EdgeSingular) =>
              (EDGE_STYLE_BY_TYPE[ele.data("relType")] ?? DEFAULT_EDGE_STYLE).lineStyle,
            "target-arrow-shape": "triangle",
            "target-arrow-color": (ele: EdgeSingular) =>
              (EDGE_STYLE_BY_TYPE[ele.data("relType")] ?? DEFAULT_EDGE_STYLE).color,
            "arrow-scale": 0.7,
            "curve-style": "bezier",
            label: "data(edgeLabel)",
            "font-size": 8,
            "text-rotation": "autorotate",
            color: "#64748b",
          },
        },
        {
          selector: ".highlighted",
          style: { "line-color": "#111827", "target-arrow-color": "#111827", width: 3 },
        },
      ],
      layout: { name: "preset" }, // real layout run explicitly below, once elements exist
      wheelSensitivity: 0.2,
    });
    cyRef.current = cy;

    cy.on("tap", "node", (evt) => {
      const node = evt.target as NodeSingular;
      const now = Date.now();
      const last = lastTapRef.current;
      lastTapRef.current = { id: node.id(), time: now };

      if (last && last.id === node.id() && now - last.time < DOUBLE_TAP_MS) {
        lastTapRef.current = null;
        void expandNode(node.id());
        return;
      }

      cy.edges().removeClass("highlighted");
      node.connectedEdges().addClass("highlighted");
      onNodeSelect?.({
        id: node.id(),
        labels: [node.data("type")],
        properties: { canonical_name: node.data("displayLabel") },
      });
    });

    cy.on("tap", (evt) => {
      if (evt.target === cy) {
        cy.elements().unselect();
        cy.edges().removeClass("highlighted");
        setTooltip(null);
      }
    });

    // "pan"/"zoom" are core-level events, not per-element — they never fire
    // through a delegated `cy.on(events, "node", ...)` selector, so the
    // hovered node's id is tracked separately and re-read on those core
    // events instead of relying on delegation for them.
    const hoveredIdRef = { current: null as string | null };
    const positionTooltip = (node: NodeSingular) => {
      const pos = node.renderedPosition();
      setTooltip({ x: pos.x, y: pos.y - 18, text: `${node.data("displayLabel")} · ${node.data("type")}` });
    };
    cy.on("mouseover", "node", (evt) => {
      hoveredIdRef.current = evt.target.id();
      positionTooltip(evt.target as NodeSingular);
    });
    cy.on("mouseout", "node", () => {
      hoveredIdRef.current = null;
      setTooltip(null);
    });
    cy.on("position", "node", (evt) => {
      if (evt.target.id() === hoveredIdRef.current) positionTooltip(evt.target as NodeSingular);
    });
    cy.on("pan zoom", () => {
      if (hoveredIdRef.current) positionTooltip(cy.getElementById(hoveredIdRef.current));
    });

    const expandNode = async (nodeId: string) => {
      try {
        const { data } = await litgraphApi.getSubgraph(nodeId, 1);
        setDisplay((prev) => {
          const existingIds = new Set(prev.nodes.map((n) => n.id));
          const newNodes = data.nodes.filter((n) => !existingIds.has(n.id));
          if (newNodes.length === 0) return prev;
          const existingEdgeKeys = new Set(prev.edges.map((e) => `${e.source}->${e.target}:${e.rel_type}`));
          const newEdges = data.edges.filter(
            (e) => !existingEdgeKeys.has(`${e.source}->${e.target}:${e.rel_type}`)
          );
          return { nodes: [...prev.nodes, ...newNodes], edges: [...prev.edges, ...newEdges] };
        });
      } catch {
        // ponytail: expand failures are silent (canvas just doesn't grow) —
        // no toast/error-state plumbing for a secondary, exploratory action.
      }
    };

    const resizeObserver = new ResizeObserver(() => cy.resize());
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      cy.destroy();
      cyRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync cytoscape's elements whenever the display set changes (initial
  // load or an expand). randomize:false on repeat layouts keeps already-
  // placed nodes roughly put instead of re-scrambling the whole graph
  // every time one node's neighborhood is expanded.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.json({ elements: toElements(display.nodes, display.edges) });
    cy.layout({
      name: "cose",
      animate: true,
      animationDuration: 400,
      randomize: !hasLaidOutRef.current,
      fit: !hasLaidOutRef.current,
    }).run();
    hasLaidOutRef.current = true;
  }, [display]);

  return (
    <div className={className ?? "relative h-full w-full"}>
      {/* Cytoscape owns this div's DOM directly (injects its own canvas
          layers) — the tooltip has to be a sibling, not a child, or
          cytoscape's own rendering could clobber it. */}
      <div ref={containerRef} className="h-full w-full" />
      {tooltip && (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-md border border-border bg-card px-2 py-1 text-xs text-card-foreground shadow-md"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          {tooltip.text}
        </div>
      )}
    </div>
  );
}

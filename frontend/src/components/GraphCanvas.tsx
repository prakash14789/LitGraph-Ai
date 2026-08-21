import cytoscape, { type Core, type EdgeSingular, type NodeSingular } from "cytoscape";
import fcose from "cytoscape-fcose";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

import {
  type CanvasNode,
  DEFAULT_EDGE_STYLE,
  DEFAULT_NODE_STYLE,
  EDGE_STYLE_BY_TYPE,
  fcoseLayoutOptions,
  NODE_STYLE_BY_LABEL,
  toElements,
} from "@/lib/graphElements";
import { isDarkMode, onThemeChange } from "@/lib/theme";
import { litgraphApi } from "@/services/api";
import type { SubgraphEdge } from "@/types";

// POLISH-003: entity/relationship fill colors (NODE_STYLE_BY_LABEL etc.)
// are saturated brand colors that already read fine on both backgrounds —
// only this "chrome" (label text, selection/highlight lines) was originally
// picked assuming a light canvas and goes near-invisible on a dark one.
// Cytoscape draws to <canvas>, so these can't be CSS tokens — isDarkMode()
// is re-read on every call, and cy.style().update() (below) forces
// Cytoscape to re-invoke these once the toggle fires.
function chromeColors() {
  return isDarkMode()
    ? { label: "#cbd5e1", selection: "#f8fafc", edgeLabel: "#94a3b8" }
    : { label: "#1f2937", selection: "#111827", edgeLabel: "#64748b" };
}

export type { CanvasNode } from "@/lib/graphElements";

// Registered once at module load, not inside the component — cytoscape.use
// is a global registration, re-running it on every mount would be redundant.
cytoscape.use(fcose);

// GRAPH-002. Shared component — FE-004 (mini panel) and GRAPH-003 (full
// explorer) both mount this with their own nodes/edges; double-click-to-
// expand calls GET /graph/subgraph itself (GRAPH-001) so every consumer
// gets the same behavior for free instead of re-implementing it. Node/edge
// styling and the Cytoscape-element mapping live in lib/graphElements.ts,
// split out so that pure logic is testable without a real DOM/Cytoscape
// instance — see graphElements.check.ts.

const DOUBLE_TAP_MS = 300;
const PULSE_INTERVAL_MS = 450;

// GRAPH-003's layout switcher. "hierarchy" maps to breadthfirst (cytoscape
// has no layout literally named "hierarchy"). "fcose" (cytoscape-fcose
// plugin) replaced the built-in "cose" as the force-directed option — cose's
// naive force simulation degenerates into a dense, heavily-crossed clump
// past ~150 nodes; fcose's constraint-based layout stays readable at the
// 200+ node graphs this page actually loads.
export type GraphLayoutName = "fcose" | "breadthfirst" | "grid";

export interface GraphCanvasHandle {
  zoomIn: () => void;
  zoomOut: () => void;
  fit: () => void;
}

export const GraphCanvas = forwardRef<
  GraphCanvasHandle,
  {
    nodes: CanvasNode[];
    edges: SubgraphEdge[];
    onNodeSelect?: (node: CanvasNode) => void;
    onDeselect?: () => void;
    className?: string;
    compact?: boolean; // GRAPH-004's mini panel: smaller nodes, no edge labels
    highlightIds?: string[]; // GRAPH-004's "View full graph" hand-off: pre-highlight these on load
    layout?: GraphLayoutName; // GRAPH-003's layout switcher, default "cose" (force-directed)
    pulseIds?: string[]; // GRAPH-003's text search: these nodes visually pulse until cleared
  }
>(function GraphCanvas(
  {
    nodes,
    edges,
    onNodeSelect,
    onDeselect,
    className,
    compact = false,
    highlightIds,
    layout = "fcose",
    pulseIds,
  },
  ref
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const hasLaidOutRef = useRef(false);
  const hasMountedLayoutPropRef = useRef(false);
  const lastTapRef = useRef<{ id: string; time: number } | null>(null);
  // Read fresh in the layout effect without being a reactive dependency —
  // only applied once, on the very first layout, not on every re-render.
  const highlightIdsRef = useRef(highlightIds);
  highlightIdsRef.current = highlightIds;
  const [display, setDisplay] = useState<{ nodes: CanvasNode[]; edges: SubgraphEdge[] }>({
    nodes,
    edges,
  });
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null);

  useImperativeHandle(ref, () => ({
    zoomIn: () => cyRef.current?.zoom(cyRef.current.zoom() * 1.25),
    zoomOut: () => cyRef.current?.zoom(cyRef.current.zoom() / 1.25),
    fit: () => cyRef.current?.fit(undefined, 30),
  }));

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
            color: () => chromeColors().label,
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
          style: { "border-width": 3, "border-color": () => chromeColors().selection },
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
            color: () => chromeColors().edgeLabel,
          },
        },
        {
          selector: ".highlighted",
          style: {
            "line-color": () => chromeColors().selection,
            "target-arrow-color": () => chromeColors().selection,
            width: 3,
          },
        },
        {
          // GRAPH-004 hand-off's URL/refresh fallback path: a thicker
          // selection border alone didn't read as "these are the relevant
          // ones" against 40+ other nodes at full opacity (live finding
          // 2026-08-20) — fading everything else out is what actually makes
          // the highlighted set pop.
          selector: ".dimmed",
          style: { opacity: 0.25 },
        },
        {
          // GRAPH-003 text search — a static "pulse-on" look toggled by JS
          // (see the pulseIds effect below), not a CSS @keyframes animation:
          // cytoscape renders to <canvas>, not DOM, so there's no element to
          // attach a CSS animation to.
          selector: ".pulse-on",
          style: { "border-width": 4, "border-color": "#F59E0B", "border-opacity": 1 },
        },
        {
          selector: ".pulse-off",
          style: { "border-width": 4, "border-color": "#F59E0B", "border-opacity": 0.25 },
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
        onDeselect?.();
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

    // POLISH-003: chromeColors() reads the live theme on every call, but
    // Cytoscape only re-invokes style functions on its own triggers — force
    // one so an already-mounted canvas repaints the moment the toggle fires,
    // instead of only picking up the new colors on the next data change.
    const unsubscribeTheme = onThemeChange(() => cy.style().update());

    return () => {
      unsubscribeTheme();
      resizeObserver.disconnect();
      cy.destroy();
      cyRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync cytoscape's elements whenever the display set changes (initial
  // load or an expand). randomize/fit only on the very first layout, so an
  // expand grows the existing layout instead of re-scrambling it.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const isFirstLayout = !hasLaidOutRef.current;
    cy.json({ elements: toElements(display.nodes, display.edges, compact) });
    cy.layout({
      name: layout,
      animate: true,
      animationDuration: 400,
      randomize: isFirstLayout,
      fit: isFirstLayout,
      // Cytoscape's collision avoidance ignores label text by default, so
      // dense graphs pack nodes close enough that neighboring labels
      // overlap — this makes layout treat the label as part of the node's
      // bounding box instead.
      nodeDimensionsIncludeLabels: true,
      ...(layout === "fcose" ? fcoseLayoutOptions(compact) : {}),
      // A non-literal `name` (it's the GraphLayoutName variable, not a
      // string constant) stops TS from picking the right per-layout options
      // overload — same cast needed below for the layout-switcher effect.
    } as cytoscape.LayoutOptions).run();
    hasLaidOutRef.current = true;
    hasMountedLayoutPropRef.current = true;

    // GRAPH-004: a subgraph handed off via "View full graph" arrives
    // highlighted, not just present — only on the very first layout, so
    // panning/expanding afterward doesn't keep re-selecting it.
    if (isFirstLayout && highlightIdsRef.current?.length) {
      const ids = new Set(highlightIdsRef.current);
      const highlighted = cy.nodes().filter((n) => ids.has(n.id()));
      highlighted.select();
      cy.nodes().filter((n) => !ids.has(n.id())).addClass("dimmed");
      const highlightedEdges = highlighted
        .connectedEdges()
        .filter((e) => ids.has(e.source().id()) && ids.has(e.target().id()));
      highlightedEdges.addClass("highlighted");
      cy.edges().not(highlightedEdges).addClass("dimmed");
    }
    // `layout` deliberately excluded — a pure layout-name change is handled
    // by the effect below, without re-fetching/re-fitting elements.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [display, compact]);

  // GRAPH-003's layout switcher: re-run layout in place when only the name
  // changes (elements already loaded) — skips its own first run, since the
  // elements-sync effect above already laid out with whatever `layout` was
  // at mount time.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !hasMountedLayoutPropRef.current) return;
    cy.layout({
      name: layout,
      animate: true,
      animationDuration: 400,
      fit: true,
      nodeDimensionsIncludeLabels: true,
      ...(layout === "fcose" ? fcoseLayoutOptions(compact) : {}),
    } as cytoscape.LayoutOptions).run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout]);

  // GRAPH-003's search pulse — a JS-driven class toggle (canvas has no CSS
  // animations to hook), cleared whenever the match set changes or empties.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.nodes().removeClass("pulse-on pulse-off");
    if (!pulseIds?.length) return;

    const ids = new Set(pulseIds);
    const targets = cy.nodes().filter((n) => ids.has(n.id()));
    let on = false;
    const tick = () => {
      on = !on;
      targets.removeClass(on ? "pulse-off" : "pulse-on").addClass(on ? "pulse-on" : "pulse-off");
    };
    tick();
    const interval = setInterval(tick, PULSE_INTERVAL_MS);
    return () => {
      clearInterval(interval);
      targets.removeClass("pulse-on pulse-off");
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pulseIds]);

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
});

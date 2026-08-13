import type { Css } from "cytoscape";

// Relative import with an explicit extension (allowImportingTsExtensions,
// tsconfig.app.json) — not the "@/" alias, and not extension-less: plain
// `node` (graphElements.check.ts runs directly under it, no bundler)
// needs both to resolve this at runtime.
import { displayName } from "./entityColors.ts";
import type { SubgraphEdge } from "../types";

// GRAPH-002's pure node/edge -> Cytoscape-element mapping, split out of
// GraphCanvas.tsx so it's testable without mounting a real Cytoscape/DOM
// instance — ponytail's "non-trivial branching logic leaves one runnable
// check" rule, see graphElements.check.ts.

// A minimal duck-typed node shape rather than reusing RetrievedSubgraph's
// SubgraphNode or GraphNode directly — both of those already-typed arrays
// satisfy this structurally (extra fields are just ignored), so either
// caller can pass its own response data straight through with no adapter.
export interface CanvasNode {
  id: string;
  labels: string[];
  properties: Record<string, unknown>;
  usage_count?: number | null;
}

// 04_FRONTEND_SPECIFICATION.md §4.3's node styling table.
export const NODE_STYLE_BY_LABEL: Record<string, { shape: Css.NodeShape; color: string }> = {
  Paper: { shape: "round-rectangle", color: "#3B82F6" },
  Method: { shape: "ellipse", color: "#10B981" },
  Dataset: { shape: "diamond", color: "#F59E0B" },
  Claim: { shape: "triangle", color: "#EF4444" },
  Author: { shape: "hexagon", color: "#8B5CF6" },
  Metric: { shape: "ellipse", color: "#06B6D4" }, // not in the spec table — entity.metric token
};
export const DEFAULT_NODE_STYLE = { shape: "ellipse" as Css.NodeShape, color: "#94A3B8" };

// §4.3's edge styling table. AUTHORED_BY/REPORTS_RESULT aren't in that
// table (the spec predates graph_writer.py's actual relationship set) —
// given a plain default rather than invented styling. CITES/CONTRADICTS
// are kept even though nothing ever writes them (relation_extractor.py
// extracts them as candidates, pipeline.py never persists them) — cheap to
// support, and future-proof if that ever changes.
export const EDGE_STYLE_BY_TYPE: Record<
  string,
  { lineStyle: "solid" | "dashed" | "dotted"; width: number; color: string; label?: string }
> = {
  CITES: { lineStyle: "solid", width: 1, color: "#94A3B8" },
  EXTENDS: { lineStyle: "solid", width: 2, color: "#10B981", label: "extends" },
  CONTRADICTS: { lineStyle: "dashed", width: 2, color: "#EF4444", label: "contradicts" },
  USES_METHOD: { lineStyle: "dotted", width: 1, color: "#3B82F6" },
  EVALUATES_ON: { lineStyle: "dotted", width: 1, color: "#F59E0B" },
  OUTPERFORMS: { lineStyle: "solid", width: 3, color: "#10B981", label: "outperforms" },
  INTRODUCES: { lineStyle: "solid", width: 2, color: "#8B5CF6", label: "introduces" },
};
export const DEFAULT_EDGE_STYLE = { lineStyle: "solid" as const, width: 1, color: "#CBD5E1" };

export function nodeSize(labels: string[], usageCount: number | null | undefined): number {
  if (labels[0] === "Claim") return 30; // spec: fixed size
  return Math.round(Math.min(70, 24 + Math.sqrt(usageCount ?? 0) * 10));
}

export function edgeLabel(relType: string, properties: Record<string, unknown>): string {
  const style = EDGE_STYLE_BY_TYPE[relType];
  if (relType === "EVALUATES_ON") {
    return [properties.metric, properties.value].filter(Boolean).join(" ");
  }
  if (relType === "OUTPERFORMS" && properties.margin) {
    return `outperforms ${properties.margin}`;
  }
  return style?.label ?? "";
}

export function toElements(nodes: CanvasNode[], edges: SubgraphEdge[]) {
  const nodeIds = new Set(nodes.map((n) => n.id));
  return [
    ...nodes.map((n) => ({
      data: {
        id: n.id,
        type: n.labels[0] ?? "",
        displayLabel: displayName(n.properties, n.id),
        size: nodeSize(n.labels, n.usage_count),
      },
    })),
    // Cytoscape errors if an edge references a node not in the element set
    // — happens when an expansion's edge points at a node just outside the
    // hop budget, so it's silently dropped rather than crashing the canvas.
    ...edges
      .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
      .map((e, i) => ({
        data: {
          id: `${e.source}->${e.target}:${e.rel_type}:${i}`,
          source: e.source,
          target: e.target,
          relType: e.rel_type,
          edgeLabel: edgeLabel(e.rel_type, e.properties),
        },
      })),
  ];
}

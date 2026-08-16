import { useQuery } from "@tanstack/react-query";
import { Maximize2, Search, X, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { GraphCanvas, type GraphCanvasHandle, type GraphLayoutName } from "@/components/GraphCanvas";
import { Button } from "@/components/ui/button";
import { DEFAULT_ENTITY_BORDER_CLASS, displayName, ENTITY_BORDER_CLASS } from "@/lib/entityColors";
import {
  DEFAULT_EDGE_STYLE,
  EDGE_STYLE_BY_TYPE,
  neighborIds,
  NODE_STYLE_BY_LABEL,
} from "@/lib/graphElements";
import { cn } from "@/lib/utils";
import { litgraphApi } from "@/services/api";
import type { CanvasNode } from "@/components/GraphCanvas";
import type { EntityDetailResponse, GraphNode, SubgraphEdge } from "@/types";

// Progressive disclosure: a fresh load of 200+ nodes across every type at
// once is the "messy grid of everything" complaint this page used to get —
// Claim/Dataset start hidden, revealed per-node (see revealedIds below)
// instead of all at once. Paper/Method stay visible by default since
// they're what a first-glance "what papers/methods exist" view needs.
const HIDDEN_BY_DEFAULT = ["Claim", "Dataset"];
// Node types whose neighbors get progressively revealed on click — the
// inverse of HIDDEN_BY_DEFAULT's own "everything else stays hidden until
// asked for" intent.
const EXPANDABLE_TYPES = new Set(["Paper", "Method"]);

// GRAPH-003. Full graph loads on visit (GET /graph/subgraph with no
// entity_id — the whole-graph snapshot GRAPH-003 itself added to that
// endpoint). Arriving via GRAPH-004's "View full graph" hand-off
// (?entity_id=&highlight=) loads that specific subgraph, highlighted,
// instead. Entity/relationship type filters and text-search pulse are all
// client-side over the already-loaded set — no re-fetch, this reads as
// "hide/show what's on screen", not "query a different graph".
//
// Collection selector (POLISH-005b): re-fetches the subgraph scoped to the
// chosen collection — a real backend filter now, not the client-side
// hide/show the type/relationship chips above do.
const LAYOUT_OPTIONS: { value: GraphLayoutName; label: string }[] = [
  { value: "fcose", label: "Force" },
  { value: "breadthfirst", label: "Hierarchy" },
  { value: "grid", label: "Grid" },
];

// Legend restricted to the relationship types graph_writer.py actually
// writes (graph_retriever.py's own _KNOWN_REL_TYPES) — EDGE_STYLE_BY_TYPE
// also defines CITES/CONTRADICTS for future-proofing, but they never occur
// in real data, so listing them in a legend would be misleading clutter.
const LEGEND_REL_TYPES = [
  "USES_METHOD",
  "EVALUATES_ON",
  "INTRODUCES",
  "EXTENDS",
  "OUTPERFORMS",
  "REPORTS_RESULT",
  "AUTHORED_BY",
];

export function GraphPage() {
  const [searchParams] = useSearchParams();
  const canvasRef = useRef<GraphCanvasHandle>(null);

  const [allNodes, setAllNodes] = useState<GraphNode[]>([]);
  const [allEdges, setAllEdges] = useState<SubgraphEdge[]>([]);
  const [highlightIds, setHighlightIds] = useState<string[] | undefined>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set(HIDDEN_BY_DEFAULT));
  const [hiddenRelTypes, setHiddenRelTypes] = useState<Set<string>>(new Set());
  const [layout, setLayout] = useState<GraphLayoutName>("fcose");
  // Progressive disclosure: ids revealed by clicking a Paper/Method node
  // whose neighbors include a hidden-by-default type — additive to
  // hiddenTypes's blanket hide, not a replacement (see visibleNodes below).
  const [revealedIds, setRevealedIds] = useState<Set<string>>(new Set());

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [entityDetail, setEntityDetail] = useState<EntityDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [collectionId, setCollectionId] = useState<string | null>(null);
  const collectionsQuery = useQuery({
    queryKey: ["collections"],
    queryFn: () => litgraphApi.getCollections().then((r) => r.data),
  });
  const collections = collectionsQuery.data ?? [];

  useEffect(() => {
    const entityId = searchParams.get("entity_id");
    const highlight = searchParams.get("highlight");
    setLoading(true);
    setError(null);
    const load = entityId
      ? litgraphApi.getSubgraph(entityId, 2, collectionId)
      : litgraphApi.getSubgraph(undefined, 2, collectionId);
    if (entityId && highlight) setHighlightIds(highlight.split(","));
    load
      .then(({ data }) => {
        setAllNodes(data.nodes);
        setAllEdges(data.edges);
        setRevealedIds(new Set()); // fresh graph, no per-node reveals carried over
      })
      .catch(() => setError("Failed to load graph."))
      .finally(() => setLoading(false));
    // Only reacts to the URL params this page was navigated to with, plus
    // the collection toolbar selector — not searchParams itself (that
    // would re-run on every navigation, not just the initial one).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collectionId]);

  useEffect(() => {
    if (!selectedId) {
      setEntityDetail(null);
      return;
    }
    setDetailLoading(true);
    litgraphApi
      .getEntity(selectedId)
      .then(({ data }) => setEntityDetail(data))
      .catch(() => setEntityDetail(null))
      .finally(() => setDetailLoading(false));
  }, [selectedId]);

  const entityTypes = useMemo(
    () => Array.from(new Set(allNodes.map((n) => n.labels[0]))).sort(),
    [allNodes]
  );
  const relTypes = useMemo(
    () => Array.from(new Set(allEdges.map((e) => e.rel_type))).sort(),
    [allEdges]
  );

  const visibleNodes = useMemo(
    () => allNodes.filter((n) => !hiddenTypes.has(n.labels[0]) || revealedIds.has(n.id)),
    [allNodes, hiddenTypes, revealedIds]
  );

  // Progressive disclosure: clicking a Paper/Method node reveals its own
  // hidden-type (Claim/Dataset) neighbors — already in allNodes/allEdges
  // from the initial load, just filtered out by hiddenTypes, so this is a
  // pure client-side reveal, no second fetch needed.
  const revealNeighbors = (node: CanvasNode) => {
    const nodeType = node.labels[0];
    if (!EXPANDABLE_TYPES.has(nodeType)) return;
    const hidden = neighborIds(node.id, allEdges).filter((id) => {
      const neighbor = allNodes.find((n) => n.id === id);
      return neighbor && hiddenTypes.has(neighbor.labels[0]);
    });
    if (hidden.length === 0) return;
    setRevealedIds((prev) => new Set([...prev, ...hidden]));
  };
  const visibleEdges = useMemo(() => {
    const visibleIds = new Set(visibleNodes.map((n) => n.id));
    return allEdges.filter(
      (e) => !hiddenRelTypes.has(e.rel_type) && visibleIds.has(e.source) && visibleIds.has(e.target)
    );
  }, [allEdges, hiddenRelTypes, visibleNodes]);

  const pulseIds = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return undefined;
    return visibleNodes
      .filter((n) => displayName(n.properties, n.id).toLowerCase().includes(q))
      .map((n) => n.id);
  }, [search, visibleNodes]);

  const toggleType = (set: React.Dispatch<React.SetStateAction<Set<string>>>, value: string) => {
    set((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-3 border-b border-border bg-card/40 p-3 shadow-sm">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search loaded nodes..."
            className="w-48 rounded-md border border-input bg-background py-1.5 pl-8 pr-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>

        <FilterChips label="Type" values={entityTypes} hidden={hiddenTypes} onToggle={(v) => toggleType(setHiddenTypes, v)} />
        <FilterChips
          label="Relationship"
          values={relTypes}
          hidden={hiddenRelTypes}
          onToggle={(v) => toggleType(setHiddenRelTypes, v)}
        />

        <select
          value={layout}
          onChange={(e) => setLayout(e.target.value as GraphLayoutName)}
          className="rounded-md border border-input bg-background px-2 py-1.5 text-sm"
        >
          {LAYOUT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>

        <select
          value={collectionId ?? ""}
          onChange={(e) => setCollectionId(e.target.value || null)}
          className="rounded-md border border-input bg-background px-2 py-1.5 text-sm"
          aria-label="Scope graph to a collection"
        >
          <option value="">All papers</option>
          {collections.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>

        <div className="ml-auto flex items-center gap-0.5 rounded-lg border border-border bg-background p-1 shadow-sm">
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => canvasRef.current?.zoomOut()} aria-label="Zoom out">
            <ZoomOut className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => canvasRef.current?.zoomIn()} aria-label="Zoom in">
            <ZoomIn className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => canvasRef.current?.fit()} aria-label="Fit to view">
            <Maximize2 className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {error && <p className="px-3 pt-2 text-sm text-destructive">{error}</p>}

      <div className="relative flex-1 overflow-hidden">
        {loading ? (
          <div className="flex h-full items-center justify-center text-muted-foreground">Loading graph…</div>
        ) : allNodes.length === 0 ? (
          <div className="flex h-full items-center justify-center text-muted-foreground">No graph data yet.</div>
        ) : (
          <div className="flex h-full">
            <div className="relative flex-1">
              <GraphCanvas
                ref={canvasRef}
                nodes={visibleNodes}
                edges={visibleEdges}
                layout={layout}
                pulseIds={pulseIds}
                highlightIds={highlightIds}
                onNodeSelect={(n) => {
                  setSelectedId(n.id);
                  revealNeighbors(n);
                }}
                onDeselect={() => setSelectedId(null)}
              />
              <Legend />
            </div>

            {selectedId && (
              <EntitySidebar
                detail={entityDetail}
                loading={detailLoading}
                onSelect={setSelectedId}
                onClose={() => setSelectedId(null)}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function FilterChips({
  label,
  values,
  hidden,
  onToggle,
}: {
  label: string;
  values: string[];
  hidden: Set<string>;
  onToggle: (value: string) => void;
}) {
  if (values.length === 0) return null;
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-xs font-medium text-muted-foreground">{label}:</span>
      {values.map((v) => (
        <button
          key={v}
          onClick={() => onToggle(v)}
          className={cn(
            "rounded-full border px-2 py-0.5 text-xs transition-colors",
            hidden.has(v)
              ? "border-border text-muted-foreground opacity-50"
              : (ENTITY_BORDER_CLASS[v] ?? DEFAULT_ENTITY_BORDER_CLASS)
          )}
        >
          {v}
        </button>
      ))}
    </div>
  );
}

function Legend() {
  return (
    <div className="absolute bottom-3 left-3 rounded-lg border border-border bg-card/95 p-2.5 text-xs shadow-md backdrop-blur-sm">
      <div className="mb-1.5 grid grid-cols-2 gap-x-3 gap-y-1">
        {Object.entries(NODE_STYLE_BY_LABEL).map(([label, style]) => (
          <div key={label} className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 shrink-0"
              style={{
                backgroundColor: style.color,
                borderRadius: style.shape === "ellipse" || style.shape === "hexagon" ? "50%" : 2,
              }}
            />
            <span className="text-card-foreground">{label}</span>
          </div>
        ))}
      </div>
      <div className="mt-1.5 space-y-0.5 border-t border-border pt-1.5">
        {LEGEND_REL_TYPES.map((relType) => {
          const style = EDGE_STYLE_BY_TYPE[relType] ?? DEFAULT_EDGE_STYLE;
          return (
            <div key={relType} className="flex items-center gap-1.5">
              <span className="inline-block h-0.5 w-4" style={{ backgroundColor: style.color }} />
              <span className="text-muted-foreground">{relType}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function EntitySidebar({
  detail,
  loading,
  onSelect,
  onClose,
}: {
  detail: EntityDetailResponse | null;
  loading: boolean;
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  return (
    <div className="w-72 shrink-0 overflow-y-auto border-l border-border bg-card p-4 shadow-lg">
      <button onClick={onClose} className="mb-3 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <X className="h-3.5 w-3.5" />
        Close
      </button>

      {loading && <p className="text-sm text-muted-foreground">Loading…</p>}

      {!loading && detail && (
        <>
          <span
            className={cn(
              "inline-block rounded-full border px-2 py-0.5 text-xs",
              ENTITY_BORDER_CLASS[detail.labels[0]] ?? DEFAULT_ENTITY_BORDER_CLASS
            )}
          >
            {detail.labels[0]}
          </span>
          <h2 className="mt-1.5 text-base font-semibold">{displayName(detail.properties, detail.id)}</h2>
          {detail.usage_count !== null && (
            <p className="mt-1 text-xs text-muted-foreground">Usage count: {detail.usage_count}</p>
          )}
          {typeof detail.properties.description === "string" && detail.properties.description && (
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
              {detail.properties.description}
            </p>
          )}

          <h3 className="mb-2 mt-4 text-xs font-semibold uppercase text-muted-foreground">
            Relationships ({detail.relationships.length})
          </h3>
          {detail.relationships.length === 0 ? (
            <p className="text-sm text-muted-foreground">None.</p>
          ) : (
            <ul className="space-y-1">
              {detail.relationships.map((r, i) => (
                <li key={i}>
                  <button
                    onClick={() => onSelect(r.id)}
                    className="text-left text-sm text-primary hover:underline"
                  >
                    {r.direction === "outgoing" ? r.rel_type : `← ${r.rel_type}`} {r.name ?? r.id}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

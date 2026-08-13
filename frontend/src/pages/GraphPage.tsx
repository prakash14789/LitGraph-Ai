import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { GraphCanvas } from "@/components/GraphCanvas";
import { Button } from "@/components/ui/button";
import { litgraphApi } from "@/services/api";
import type { GraphNode, SubgraphEdge } from "@/types";

// Minimal consumer proving GraphCanvas (GRAPH-002) actually renders/
// interacts with real data. The real toolbar (collection/type filters,
// layout switcher, legend, entity detail sidebar) is GRAPH-003's separate
// scope — this is a search box standing in for it, not a first draft of it.
//
// GRAPH-004: ContextPanel's "View full graph" button links here with
// ?entity_id=<seed>&highlight=<comma-separated ids> — read once on mount to
// auto-load without the user re-typing the search that got them there.
export function GraphPage() {
  const [searchParams] = useSearchParams();
  const [query, setQuery] = useState("");
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<SubgraphEdge[]>([]);
  const [highlightIds, setHighlightIds] = useState<string[] | undefined>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadFromEntity = async (entityId: string) => {
    setLoading(true);
    setError(null);
    try {
      const { data: subgraph } = await litgraphApi.getSubgraph(entityId, 2);
      setNodes(subgraph.nodes);
      setEdges(subgraph.edges);
    } catch {
      setError("Failed to load graph.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const entityId = searchParams.get("entity_id");
    if (!entityId) return;
    const highlight = searchParams.get("highlight");
    setHighlightIds(highlight ? highlight.split(",") : undefined);
    void loadFromEntity(entityId);
    // Only ever consumes the params this page was navigated to with.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const search = async () => {
    const q = query.trim();
    if (!q) return;
    setHighlightIds(undefined);
    setLoading(true);
    setError(null);
    try {
      const { data: results } = await litgraphApi.searchEntities(q);
      if (results.results.length === 0) {
        setNodes([]);
        setEdges([]);
        setError("No matching entities found.");
        setLoading(false);
        return;
      }
      await loadFromEntity(results.results[0].id);
    } catch {
      setError("Failed to load graph.");
      setLoading(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border p-3">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void search()}
          placeholder="Search an entity to explore (full toolbar lands GRAPH-003)..."
          className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <Button size="sm" onClick={() => void search()} disabled={loading || !query.trim()}>
          {loading ? "Loading…" : "Load"}
        </Button>
      </div>

      {error && <p className="px-3 pt-2 text-sm text-destructive">{error}</p>}

      <div className="relative flex-1">
        {nodes.length === 0 ? (
          <div className="flex h-full items-center justify-center text-center text-muted-foreground">
            Search for an entity above to explore its graph.
          </div>
        ) : (
          <GraphCanvas nodes={nodes} edges={edges} highlightIds={highlightIds} />
        )}
      </div>
    </div>
  );
}

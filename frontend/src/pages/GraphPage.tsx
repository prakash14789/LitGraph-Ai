import { useState } from "react";

import { GraphCanvas } from "@/components/GraphCanvas";
import { Button } from "@/components/ui/button";
import { litgraphApi } from "@/services/api";
import type { GraphNode, SubgraphEdge } from "@/types";

// Minimal consumer proving GraphCanvas (GRAPH-002) actually renders/
// interacts with real data. The real toolbar (collection/type filters,
// layout switcher, legend, entity detail sidebar) is GRAPH-003's separate
// scope — this is a search box standing in for it, not a first draft of it.
export function GraphPage() {
  const [query, setQuery] = useState("");
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<SubgraphEdge[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    const q = query.trim();
    if (!q) return;
    setLoading(true);
    setError(null);
    try {
      const { data: search } = await litgraphApi.searchEntities(q);
      if (search.results.length === 0) {
        setNodes([]);
        setEdges([]);
        setError("No matching entities found.");
        return;
      }
      const { data: subgraph } = await litgraphApi.getSubgraph(search.results[0].id, 2);
      setNodes(subgraph.nodes);
      setEdges(subgraph.edges);
    } catch {
      setError("Failed to load graph.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border p-3">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void load()}
          placeholder="Search an entity to explore (full toolbar lands GRAPH-003)..."
          className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <Button size="sm" onClick={() => void load()} disabled={loading || !query.trim()}>
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
          <GraphCanvas nodes={nodes} edges={edges} />
        )}
      </div>
    </div>
  );
}

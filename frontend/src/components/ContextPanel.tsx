import { ChevronDown, ChevronUp, Maximize2, Network } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { GraphCanvas } from "@/components/GraphCanvas";
import { DEFAULT_ENTITY_BORDER_CLASS, displayName, ENTITY_BORDER_CLASS } from "@/lib/entityColors";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/store/chatStore";

// FE-004. One collapse boolean drives both layouts: mobile (<lg) renders
// as a fixed bottom sheet that slides down to a pull-tab when collapsed;
// lg+ renders as a static sidebar that narrows to an icon strip. No JS
// media-query listener — the two behaviors are just different Tailwind
// classes gated by the same state, CSS doing the layout switch.
export function ContextPanel({
  message,
  onSelectEntity,
}: {
  message: ChatMessage | undefined;
  onSelectEntity: (id: string) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const nodes = message?.retrievedSubgraph?.nodes ?? [];
  const edges = message?.retrievedSubgraph?.edges ?? [];
  const sources = message?.citations ?? [];

  // Live finding 2026-08-20: retrievedSubgraph is the graph-traversal's own
  // ranked candidate set (broader on purpose — see below), not "what the
  // answer actually discussed". A candidate paper's entity (e.g. ALBERT,
  // pulled in as a strong entity-seed match) can rank into that set and
  // never be mentioned in the answer at all — confirmed live, an ELECTRA-
  // vs-RoBERTa query's Entities panel showed zero ELECTRA entities and
  // several ALBERT ones. `citations` (now itself tightened — see query.py's
  // _build_citations) IS answer-aligned, but paper-level only; there's no
  // entity-level "was this actually cited" signal to filter on directly.
  // Closest correct proxy: keep only entities with an edge to a Paper
  // that's actually in citations - a real Paper->Claim/Method/Dataset
  // edge, not just co-membership in the same broad traversal.
  //
  // `nodes`/`edges` themselves stay the RAW, unfiltered retrievedSubgraph —
  // the mini preview below and "View full graph" both intentionally show
  // the broader graph-exploration set, not just what got cited.
  const citedPaperIds = new Set(sources.map((c) => c.paper_id));
  const citedPaperNodeIds = new Set(
    nodes
      .filter((n) => n.labels[0] === "Paper" && citedPaperIds.has(n.properties.paper_id as string))
      .map((n) => n.id)
  );
  const entityNodes = nodes.filter(
    (n) =>
      n.labels[0] !== "Paper" &&
      edges.some(
        (e) =>
          (e.source === n.id && citedPaperNodeIds.has(e.target)) ||
          (e.target === n.id && citedPaperNodeIds.has(e.source))
      )
  );

  // GRAPH-004: hand off to the Graph page with the *exact* subgraph this
  // answer used, via router state — not just an entity_id for GraphPage to
  // re-derive. Live finding 2026-08-20: a fresh entity_id+hops=2 re-fetch
  // is a genuinely different (usually bigger) set than what actually
  // produced the answer — for one real query this was 46 nodes back vs the
  // 20 actually used, and worse for any hub entity — which read as "why is
  // it showing me unrelated stuff" even though highlighting was technically
  // correct. Passing nodes/edges directly means GraphPage renders exactly
  // this set, no re-traversal, no mismatch possible.
  // entity_id/highlight stay in the URL too, purely as a refresh/deep-link
  // fallback (router state doesn't survive a hard reload) — GraphPage
  // prefers state when present, falls back to the URL params otherwise.
  const viewFullGraph = () => {
    if (nodes.length === 0) return;
    const params = new URLSearchParams({
      entity_id: nodes[0].id,
      highlight: nodes.map((n) => n.id).join(","),
    });
    navigate(`/graph?${params.toString()}`, { state: { nodes, edges } });
  };

  return (
    <div
      className={cn(
        "z-20 flex flex-col border-border bg-card transition-transform",
        "fixed inset-x-0 bottom-0 max-h-[50vh] rounded-t-lg border-t shadow-lg",
        collapsed ? "translate-y-[calc(100%-2.75rem)]" : "translate-y-0",
        "lg:static lg:inset-auto lg:h-full lg:max-h-none lg:translate-y-0 lg:rounded-none lg:border-l lg:border-t-0 lg:shadow-none",
        collapsed ? "lg:w-11" : "lg:w-72"
      )}
    >
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="flex shrink-0 items-center justify-between gap-2 px-4 py-3 text-sm font-medium lg:justify-center"
        aria-label={collapsed ? "Expand context panel" : "Collapse context panel"}
      >
        <span className={cn(collapsed && "lg:hidden")}>Context</span>
        {collapsed ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
      </button>

      {!collapsed && (
        <div className="flex-1 space-y-4 overflow-y-auto px-4 pb-4">
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
              Sources ({sources.length})
            </h3>
            {sources.length === 0 ? (
              <p className="text-sm text-muted-foreground">Ask a question to see sources.</p>
            ) : (
              <ul className="space-y-1 text-sm text-muted-foreground">
                {sources.map((s) => (
                  <li key={s.paper_id} className="truncate">
                    {s.title ?? "Untitled paper"}
                    {s.year ? ` (${s.year})` : ""}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
              Entities ({entityNodes.length})
            </h3>
            {entityNodes.length === 0 ? (
              <p className="text-sm text-muted-foreground">No entities for this answer yet.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {entityNodes.map((n) => (
                  <button
                    key={n.id}
                    onClick={() => onSelectEntity(n.id)}
                    className={cn(
                      "rounded-full border px-2 py-0.5 text-xs transition-colors hover:opacity-80",
                      ENTITY_BORDER_CLASS[n.labels[0]] ?? DEFAULT_ENTITY_BORDER_CLASS
                    )}
                  >
                    {displayName(n.properties, n.id)}{" "}
                    <span className="opacity-60">· {n.labels[0]}</span>
                  </button>
                ))}
              </div>
            )}
          </section>

          <section>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase text-muted-foreground">Subgraph</h3>
              {nodes.length > 0 && (
                <button
                  onClick={viewFullGraph}
                  className="flex items-center gap-1 text-xs text-primary hover:underline"
                >
                  <Maximize2 className="h-3 w-3" />
                  View full graph
                </button>
              )}
            </div>
            {nodes.length === 0 ? (
              <div className="flex h-48 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border text-muted-foreground">
                <Network className="h-6 w-6" />
                <p className="text-xs">Ask a question to see its subgraph.</p>
              </div>
            ) : (
              <div className="h-48 overflow-hidden rounded-lg border border-border">
                <GraphCanvas
                  nodes={nodes}
                  edges={edges}
                  compact
                  onNodeSelect={(node) => onSelectEntity(node.id)}
                />
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

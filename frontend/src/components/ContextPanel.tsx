import { ChevronDown, ChevronUp, Network } from "lucide-react";
import { useState } from "react";

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
  const nodes = message?.retrievedSubgraph?.nodes ?? [];
  const entityNodes = nodes.filter((n) => n.labels[0] !== "Paper");
  const sources = message?.citations ?? [];

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

          {/* Placeholder container for GRAPH-004's Cytoscape mini-graph —
              deliberately no Cytoscape code here (ticket's own scope note).
              Sized/styled now so GRAPH-004 only has to drop the canvas in. */}
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">Subgraph</h3>
            <div className="flex h-48 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border text-muted-foreground">
              <Network className="h-6 w-6" />
              <p className="text-xs">Graph view coming (GRAPH-004)</p>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

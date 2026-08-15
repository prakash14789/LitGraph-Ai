import { useEffect, useRef } from "react";

import { DEFAULT_ENTITY_BORDER_CLASS, displayName, ENTITY_BORDER_CLASS } from "@/lib/entityColors";
import { cn } from "@/lib/utils";
import type { RetrievedSubgraph } from "@/types";

// FE-005. Same native <dialog> pattern as PaperDetailModal.tsx (X/Escape/
// outside-click close for free, no dialog primitive installed).
//
// Scoped to the *current answer's* retrieved subgraph — the only entity
// data the frontend has today. Full-graph entity lookup (any paper that
// ever mentioned this entity, not just the ones in this answer's context)
// needs GRAPH-001, which isn't built yet. "Related entities"/"source
// papers" here means "within this answer's context", disclosed via the
// panel copy below rather than presented as the global picture.

export function EntityDetailModal({
  subgraph,
  nodeId,
  onSelect,
  onClose,
}: {
  subgraph: RetrievedSubgraph | undefined;
  nodeId: string | null;
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const node = subgraph?.nodes.find((n) => n.id === nodeId) ?? null;

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (node) dialog.showModal();
    else dialog.close();
  }, [node]);

  const connections = subgraph
    ? subgraph.edges
        .filter((e) => e.source === nodeId || e.target === nodeId)
        .map((e) => {
          const otherId = e.source === nodeId ? e.target : e.source;
          const otherNode = subgraph.nodes.find((n) => n.id === otherId);
          return { edge: e, otherNode };
        })
        .filter((c) => c.otherNode)
    : [];

  const sourcePapers = connections.filter((c) => c.otherNode!.labels[0] === "Paper");
  const relatedEntities = connections.filter((c) => c.otherNode!.labels[0] !== "Paper");

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      className="w-full max-w-lg rounded-xl border border-border bg-card p-0 text-card-foreground shadow-2xl backdrop:bg-black/50 backdrop:backdrop-blur-sm"
    >
      {node && (
        <div className="max-h-[80vh] overflow-y-auto p-5">
          <div className="mb-1 flex items-start justify-between gap-4">
            <div>
              <span
                className={cn(
                  "inline-block rounded-full border px-2 py-0.5 text-xs",
                  ENTITY_BORDER_CLASS[node.labels[0]] ?? DEFAULT_ENTITY_BORDER_CLASS
                )}
              >
                {node.labels[0]}
              </span>
              <h2 className="mt-1.5 text-lg font-semibold">
                {displayName(node.properties, node.id)}
              </h2>
            </div>
            <button
              onClick={onClose}
              className="shrink-0 text-muted-foreground hover:text-foreground"
              aria-label="Close"
            >
              ✕
            </button>
          </div>

          {typeof node.properties.description === "string" && node.properties.description && (
            <p className="mb-3 text-sm leading-relaxed text-muted-foreground">
              {node.properties.description}
            </p>
          )}

          {Array.isArray(node.properties.aliases) && node.properties.aliases.length > 0 && (
            <div className="mb-4 flex flex-wrap gap-1.5">
              {(node.properties.aliases as string[]).map((a) => (
                <span
                  key={a}
                  className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground"
                >
                  {a}
                </span>
              ))}
            </div>
          )}

          <div className="mb-4">
            <h3 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
              Source papers in this answer ({sourcePapers.length})
            </h3>
            {sourcePapers.length === 0 ? (
              <p className="text-sm text-muted-foreground">None in this answer's context.</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {sourcePapers.map(({ otherNode }) => (
                  <li key={otherNode!.id} className="text-muted-foreground">
                    {displayName(otherNode!.properties, otherNode!.id)}
                    {typeof otherNode!.properties.year === "number"
                      ? ` (${otherNode!.properties.year})`
                      : ""}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
              Related entities ({relatedEntities.length})
            </h3>
            {relatedEntities.length === 0 ? (
              <p className="text-sm text-muted-foreground">None in this answer's context.</p>
            ) : (
              <ul className="space-y-1">
                {relatedEntities.map(({ edge, otherNode }) => (
                  <li key={otherNode!.id}>
                    <button
                      onClick={() => onSelect(otherNode!.id)}
                      className="text-left text-sm text-primary hover:underline"
                    >
                      {edge.rel_type} → {displayName(otherNode!.properties, otherNode!.id)}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </dialog>
  );
}

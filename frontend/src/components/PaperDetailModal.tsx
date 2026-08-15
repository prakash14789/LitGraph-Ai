import { useEffect, useRef } from "react";

import { DEFAULT_ENTITY_BORDER_CLASS, ENTITY_BORDER_CLASS } from "@/lib/entityColors";
import { cn } from "@/lib/utils";
import type { PaperDetail } from "@/types";

// Native <dialog> instead of a Radix/shadcn Dialog — no dialog primitive is
// installed yet, and <dialog> gives focus-trap, Escape-to-close, and a
// ::backdrop for free (FE-002's "closeable via X, Escape, or outside click"
// AC needs no extra code for the last two).

export function PaperDetailModal({
  paper,
  onClose,
}: {
  paper: PaperDetail | null;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (paper) dialog.showModal();
    else dialog.close();
  }, [paper]);

  const entityName = (id: string) =>
    paper && id === paper.id ? paper.title : paper?.entities.find((e) => e.id === id)?.name ?? id;

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => {
        // A click that lands on the <dialog> element itself (not a child)
        // hit the ::backdrop — standing in for a click-outside handler.
        if (e.target === ref.current) onClose();
      }}
      className="w-full max-w-lg rounded-xl border border-border bg-card p-0 text-card-foreground shadow-2xl backdrop:bg-black/50 backdrop:backdrop-blur-sm"
    >
      {paper && (
        <div className="max-h-[80vh] overflow-y-auto p-5">
          <div className="mb-1 flex items-start justify-between gap-4">
            <h2 className="text-lg font-semibold">{paper.title}</h2>
            <button
              onClick={onClose}
              className="shrink-0 text-muted-foreground hover:text-foreground"
              aria-label="Close"
            >
              ✕
            </button>
          </div>
          <p className="mb-3 text-sm text-muted-foreground">
            {paper.authors.join(", ") || "Unknown authors"}
            {paper.year ? ` · ${paper.year}` : ""}
            {paper.venue ? ` · ${paper.venue}` : ""}
          </p>

          {paper.abstract && <p className="mb-4 text-sm leading-relaxed">{paper.abstract}</p>}

          <div className="mb-4">
            <h3 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
              Entities ({paper.entities.length})
            </h3>
            {paper.entities.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                None extracted yet — check back once ingestion finishes.
              </p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {paper.entities.map((e) => (
                  <span
                    key={e.id}
                    className={cn(
                      "rounded-full border px-2 py-0.5 text-xs",
                      ENTITY_BORDER_CLASS[e.type] ?? DEFAULT_ENTITY_BORDER_CLASS
                    )}
                  >
                    {e.name} <span className="opacity-60">· {e.type}</span>
                  </span>
                ))}
              </div>
            )}
          </div>

          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
              Relationships ({paper.relationships.length})
            </h3>
            {paper.relationships.length === 0 ? (
              <p className="text-sm text-muted-foreground">None extracted yet.</p>
            ) : (
              <ul className="space-y-1 text-sm text-muted-foreground">
                {paper.relationships.map((r, i) => (
                  <li key={i}>
                    {entityName(r.source)} <span className="font-medium text-foreground">{r.type}</span>{" "}
                    {entityName(r.target)}
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

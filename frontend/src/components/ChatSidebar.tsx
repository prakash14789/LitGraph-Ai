import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderPlus, Info, Layers, MessageSquarePlus, Sparkles } from "lucide-react";

import { folderColor } from "@/lib/folderColor";
import { cn } from "@/lib/utils";
import { litgraphApi } from "@/services/api";
import { useChatStore } from "@/store/chatStore";

// "Folder-wise chat": a folder here IS a Collection (POLISH-005's existing
// backend concept — organizational grouping + POLISH-005b's retrieval
// scoping). Nothing new on the backend; this is purely the chat-page UI for
// switching/creating them, previously a plain <select> in ChatPage.tsx.
// Full rename/delete stays on the Papers page (FE already owns that CRUD) —
// duplicating it here would just be two places to keep in sync.
export function ChatSidebar() {
  const queryClient = useQueryClient();
  const { collectionId, setCollectionId, newChat } = useChatStore();

  const collectionsQuery = useQuery({
    queryKey: ["collections"],
    queryFn: () => litgraphApi.getCollections().then((r) => r.data),
  });
  const collections = collectionsQuery.data ?? [];

  const createCollectionMutation = useMutation({
    mutationFn: (name: string) => litgraphApi.createCollection(name).then((r) => r.data),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: ["collections"] });
      setCollectionId(created.id);
    },
  });

  const handleNewFolder = () => {
    const name = window.prompt("New folder name:");
    if (name?.trim()) createCollectionMutation.mutate(name.trim());
  };

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-border bg-gradient-to-b from-card/60 to-card/20">
      <div className="flex items-center gap-2 px-4 pb-1 pt-4 text-sm font-semibold text-foreground">
        <Sparkles className="h-4 w-4 text-primary" />
        LitGraph
      </div>

      <div className="p-3">
        <button
          onClick={newChat}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-br from-primary to-primary/85 px-3 py-2 text-sm font-medium text-primary-foreground shadow-sm shadow-primary/25 transition-all hover:shadow-md hover:shadow-primary/30 active:scale-[0.98]"
        >
          <MessageSquarePlus className="h-4 w-4" />
          New chat
        </button>
      </div>

      <div className="flex items-center justify-between px-3 pb-1.5 pt-2">
        <span className="flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Folders
          {/* Native title attr, not a custom tooltip component — one info
              icon doesn't justify adding a dependency for it. See README's
              "Collections are organizational, not a retrieval boundary"
              key-decision bullet for the full explanation. */}
          <Info
            className="h-3 w-3 cursor-help opacity-60"
            title="Folders organize papers, but don't fully isolate them — an entity shared between papers in different folders (e.g. both mention the same method) can still surface across folders. Chunk-level text search is folder-scoped either way."
          />
        </span>
        <button
          onClick={handleNewFolder}
          aria-label="New folder"
          className="rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <FolderPlus className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
        <FolderRow
          label="All papers"
          active={collectionId === null}
          onClick={() => setCollectionId(null)}
        />
        {collections.map((c) => (
          <FolderRow
            key={c.id}
            id={c.id}
            label={c.name}
            count={c.paper_count}
            active={collectionId === c.id}
            onClick={() => setCollectionId(c.id)}
          />
        ))}
        {collections.length === 0 && (
          <p className="px-2 py-3 text-xs text-muted-foreground">
            No folders yet — create one to scope chat/graph to just those papers.
          </p>
        )}
      </div>
    </aside>
  );
}

function FolderRow({
  id,
  label,
  count,
  active,
  onClick,
}: {
  id?: string;
  label: string;
  count?: number;
  active: boolean;
  onClick: () => void;
}) {
  const color = id ? folderColor(id) : null;
  return (
    <button
      onClick={onClick}
      className={cn(
        "group flex w-full items-center gap-2 rounded-md border-l-2 px-2.5 py-1.5 text-left text-sm transition-colors",
        active
          ? cn("border-l-2 font-medium text-foreground", color?.tint ?? "bg-primary/10", color?.border ?? "border-primary")
          : "border-transparent text-foreground/80 hover:bg-accent"
      )}
    >
      {color ? (
        <span className={cn("h-2 w-2 shrink-0 rounded-full", color.bg)} />
      ) : (
        <Layers className="h-3.5 w-3.5 shrink-0 opacity-70" />
      )}
      <span className="flex-1 truncate">{label}</span>
      {typeof count === "number" && (
        <span
          className={cn(
            "shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium",
            active ? cn(color?.tint, color?.text) : "bg-muted text-muted-foreground"
          )}
        >
          {count}
        </span>
      )}
    </button>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  Clock,
  Eye,
  FileText,
  FolderPlus,
  Loader2,
  Pencil,
  Trash2,
  UploadCloud,
  XCircle,
} from "lucide-react";
import { useRef, useState } from "react";

import { PaperDetailModal } from "@/components/PaperDetailModal";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { litgraphApi } from "@/services/api";
import type { Collection, IngestionStatus, Paper } from "@/types";

const STATUS_META: Record<
  IngestionStatus,
  { label: string; icon: typeof Clock; className: string }
> = {
  pending: { label: "Queued", icon: Clock, className: "text-muted-foreground" },
  processing: { label: "Processing", icon: Loader2, className: "text-primary" },
  completed: { label: "Done", icon: CheckCircle2, className: "text-emerald-600" },
  failed: { label: "Failed", icon: XCircle, className: "text-destructive" },
};

export function PapersPage() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [uploadErrors, setUploadErrors] = useState<string[]>([]);
  const [selectedPaperId, setSelectedPaperId] = useState<string | null>(null);
  // "" = All papers (unfiltered, matches GET /papers with no collection_id
  // — see api.ts). Also the collection new uploads get assigned to below.
  const [activeCollectionId, setActiveCollectionId] = useState<string>("");

  const collectionsQuery = useQuery({
    queryKey: ["collections"],
    queryFn: () => litgraphApi.getCollections().then((r) => r.data),
  });
  const collections = collectionsQuery.data ?? [];

  const papersQuery = useQuery({
    queryKey: ["papers", activeCollectionId],
    queryFn: () => litgraphApi.getPapers(activeCollectionId || undefined).then((r) => r.data),
    // Re-lists (rather than polling GET /ingest/status/{job_id}) while
    // anything is still ingesting — satisfies the "poll status, auto-update"
    // AC without tracking job_id client-side, which a page refresh loses
    // anyway since GET /papers doesn't return it.
    refetchInterval: (query) =>
      query.state.data?.some(
        (p) => p.ingestion_status === "pending" || p.ingestion_status === "processing"
      )
        ? 3000
        : false,
  });

  const paperDetailQuery = useQuery({
    queryKey: ["paper", selectedPaperId],
    queryFn: () => litgraphApi.getPaper(selectedPaperId as string).then((r) => r.data),
    enabled: selectedPaperId !== null,
  });

  const uploadMutation = useMutation({
    mutationFn: (files: File[]) =>
      litgraphApi.uploadPapers(files, activeCollectionId || null).then((r) => r.data),
    onSuccess: (results) => {
      void queryClient.invalidateQueries({ queryKey: ["papers"] });
      void queryClient.invalidateQueries({ queryKey: ["collections"] });
      const rejected = results.filter((r) => r.status === "rejected");
      setUploadErrors(rejected.map((r) => `${r.filename}: ${r.error ?? "rejected"}`));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => litgraphApi.deletePaper(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["papers"] });
      void queryClient.invalidateQueries({ queryKey: ["collections"] });
    },
  });

  const assignMutation = useMutation({
    mutationFn: ({ id, collectionId }: { id: string; collectionId: string | null }) =>
      litgraphApi.assignPaperCollection(id, collectionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["papers"] });
      void queryClient.invalidateQueries({ queryKey: ["collections"] });
    },
  });

  const createCollectionMutation = useMutation({
    mutationFn: (name: string) => litgraphApi.createCollection(name).then((r) => r.data),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: ["collections"] });
      setActiveCollectionId(created.id);
    },
  });

  const renameCollectionMutation = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      litgraphApi.renameCollection(id, name),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["collections"] }),
  });

  const deleteCollectionMutation = useMutation({
    mutationFn: (id: string) => litgraphApi.deleteCollection(id),
    onSuccess: () => {
      setActiveCollectionId("");
      void queryClient.invalidateQueries({ queryKey: ["collections"] });
      void queryClient.invalidateQueries({ queryKey: ["papers"] });
    },
  });

  const handleFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    uploadMutation.mutate(Array.from(files));
  };

  const handleNewCollection = () => {
    const name = window.prompt("New collection name:");
    if (name?.trim()) createCollectionMutation.mutate(name.trim());
  };

  const handleRenameCollection = () => {
    const current = collections.find((c) => c.id === activeCollectionId);
    if (!current) return;
    const name = window.prompt("Rename collection:", current.name);
    if (name?.trim() && name.trim() !== current.name) {
      renameCollectionMutation.mutate({ id: current.id, name: name.trim() });
    }
  };

  const handleDeleteCollection = () => {
    const current = collections.find((c) => c.id === activeCollectionId);
    if (!current) return;
    if (
      window.confirm(
        `Delete collection "${current.name}"? Papers in it are kept, just unassigned.`
      )
    ) {
      deleteCollectionMutation.mutate(current.id);
    }
  };

  const papers = papersQuery.data ?? [];
  const stats = {
    total: papers.length,
    completed: papers.filter((p) => p.ingestion_status === "completed").length,
    processing: papers.filter(
      (p) => p.ingestion_status === "pending" || p.ingestion_status === "processing"
    ).length,
    failed: papers.filter((p) => p.ingestion_status === "failed").length,
  };

  return (
    <div className="mx-auto h-full max-w-4xl overflow-y-auto px-4 py-6">
      <div className="mb-5">
        <h1 className="text-lg font-semibold tracking-tight">Papers</h1>
        <p className="text-sm text-muted-foreground">Upload sources to grow the knowledge graph.</p>
      </div>

      {/* Collection filter/organize toolbar (POLISH-005 — organizational
          only: filters this page's list and scopes new uploads, does NOT
          filter Chat or Graph answers). */}
      <div className="mb-4 flex items-center gap-2">
        <select
          value={activeCollectionId}
          onChange={(e) => setActiveCollectionId(e.target.value)}
          className="rounded-md border border-input bg-card px-2.5 py-1.5 text-sm"
          aria-label="Filter by collection"
        >
          <option value="">All papers</option>
          {collections.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({c.paper_count})
            </option>
          ))}
        </select>
        <Button variant="outline" size="sm" onClick={handleNewCollection}>
          <FolderPlus className="mr-1.5 h-3.5 w-3.5" />
          New collection
        </Button>
        {activeCollectionId && (
          <>
            <Button variant="ghost" size="icon" onClick={handleRenameCollection} aria-label="Rename collection">
              <Pencil className="h-3.5 w-3.5" />
            </Button>
            <Button variant="ghost" size="icon" onClick={handleDeleteCollection} aria-label="Delete collection">
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </>
        )}
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragActive(false);
          handleFiles(e.dataTransfer.files);
        }}
        onClick={() => fileInputRef.current?.click()}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-10 text-center transition-all",
          dragActive
            ? "border-primary bg-primary/5 shadow-inner"
            : "border-border bg-card/50 hover:border-primary/50 hover:bg-primary/[0.03]"
        )}
      >
        <div
          className={cn(
            "flex h-12 w-12 items-center justify-center rounded-full transition-colors",
            dragActive ? "bg-primary/15" : "bg-muted"
          )}
        >
          <UploadCloud className={cn("h-6 w-6", dragActive ? "text-primary" : "text-muted-foreground")} />
        </div>
        <div>
          <p className="text-sm font-medium">Drag PDFs here, or click to browse</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Papers are parsed, chunked, and added to the graph automatically
            {activeCollectionId &&
              ` — into "${collections.find((c) => c.id === activeCollectionId)?.name}"`}
          </p>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/pdf"
          multiple
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>

      {uploadMutation.isPending && <p className="mt-2 text-sm text-muted-foreground">Uploading…</p>}
      {uploadErrors.length > 0 && (
        <div className="mt-2 space-y-1">
          {uploadErrors.map((e) => (
            <p key={e} className="text-sm text-destructive">
              {e}
            </p>
          ))}
        </div>
      )}

      {/* ArXiv import — POST /ingest/arxiv is POLISH-004's scope, not built
          yet. Input shown-but-disabled (same pattern as Header's dark-mode
          button) so it doesn't look like a live control that silently
          does nothing. */}
      <div className="mt-4 flex items-center gap-2">
        <input
          disabled
          placeholder="ArXiv URL import — coming soon (POLISH-004)"
          className="flex-1 rounded-md border border-input bg-muted px-3 py-2 text-sm text-muted-foreground"
        />
        <Button disabled size="sm" variant="outline">
          Import
        </Button>
      </div>

      <div className="mt-6 grid grid-cols-4 gap-3">
        <StatCard label="Papers" value={stats.total} icon={FileText} tone="text-foreground bg-muted" />
        <StatCard label="Done" value={stats.completed} icon={CheckCircle2} tone="text-emerald-600 bg-emerald-600/10" />
        <StatCard label="Processing" value={stats.processing} icon={Loader2} tone="text-primary bg-primary/10" />
        <StatCard label="Failed" value={stats.failed} icon={XCircle} tone="text-destructive bg-destructive/10" />
      </div>

      <div className="mt-6 space-y-2">
        {papersQuery.isLoading && <p className="text-sm text-muted-foreground">Loading papers…</p>}
        {!papersQuery.isLoading && papers.length === 0 && (
          <p className="text-sm text-muted-foreground">No papers yet — upload one above.</p>
        )}
        {papers.map((paper) => (
          <PaperCard
            key={paper.id}
            paper={paper}
            collections={collections}
            onView={() => setSelectedPaperId(paper.id)}
            onDelete={() => {
              if (window.confirm(`Delete "${paper.title}"? This can't be undone.`)) {
                deleteMutation.mutate(paper.id);
              }
            }}
            onAssign={(collectionId) => assignMutation.mutate({ id: paper.id, collectionId })}
          />
        ))}
      </div>

      <PaperDetailModal
        paper={paperDetailQuery.data ?? null}
        onClose={() => setSelectedPaperId(null)}
      />
    </div>
  );
}

function StatCard({
  label,
  value,
  icon: Icon,
  tone,
}: {
  label: string;
  value: number;
  icon: typeof FileText;
  tone: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border bg-card p-3 shadow-sm transition-shadow hover:shadow-md">
      <div className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", tone)}>
        <Icon className="h-4.5 w-4.5" />
      </div>
      <div className="min-w-0">
        <div className="text-xl font-semibold leading-none">{value}</div>
        <div className="mt-1 truncate text-xs text-muted-foreground">{label}</div>
      </div>
    </div>
  );
}

function PaperCard({
  paper,
  collections,
  onView,
  onDelete,
  onAssign,
}: {
  paper: Paper;
  collections: Collection[];
  onView: () => void;
  onDelete: () => void;
  onAssign: (collectionId: string | null) => void;
}) {
  const meta = STATUS_META[paper.ingestion_status];
  const StatusIcon = meta.icon;
  return (
    <div className="group flex items-center justify-between gap-4 rounded-xl border border-border bg-card p-3 shadow-sm transition-all hover:border-primary/30 hover:shadow-md">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{paper.title}</p>
        <p className="truncate text-xs text-muted-foreground">
          {paper.authors.join(", ") || "Unknown authors"}
          {paper.year ? ` · ${paper.year}` : ""}
        </p>
        {paper.ingestion_status === "processing" && (
          <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-muted">
            {/* No real percentage from the backend at list granularity —
                honest indeterminate pulse instead of a fake progress %. */}
            <div className="h-full w-1/3 animate-pulse rounded-full bg-primary" />
          </div>
        )}
      </div>

      <div className={cn("flex shrink-0 items-center gap-1 text-xs", meta.className)}>
        <StatusIcon
          className={cn("h-3.5 w-3.5", paper.ingestion_status === "processing" && "animate-spin")}
        />
        {meta.label}
      </div>

      {/* Per-paper collection assignment (POLISH-005) — native select over
          a custom dropdown, no component library installed for this yet
          and one isn't worth adding for a single control. */}
      <select
        value={paper.collection_id ?? ""}
        onChange={(e) => onAssign(e.target.value || null)}
        onClick={(e) => e.stopPropagation()}
        className="shrink-0 rounded-md border border-input bg-transparent px-1.5 py-1 text-xs text-muted-foreground"
        aria-label="Assign to collection"
      >
        <option value="">No collection</option>
        {collections.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>

      {/* Two direct action buttons instead of a kebab menu — a hidden menu
          for exactly 2 actions is indirection with no payoff, and no
          dropdown-menu primitive is installed yet. */}
      <div className="flex shrink-0 items-center gap-1">
        <Button variant="ghost" size="icon" onClick={onView} aria-label="View details">
          <Eye className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" onClick={onDelete} aria-label="Delete">
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

// Deterministic per-folder color identity — same collection id always maps
// to the same color, no state to persist for it. A tasteful, distinct-at-a-
// glance palette (not the entity-type colors — those already mean something
// specific, Paper=blue/Method=green/etc.; folders get their own separate
// set so the two systems don't visually collide).
const PALETTE = [
  { text: "text-sky-500", bg: "bg-sky-500", tint: "bg-sky-500/10", border: "border-sky-500/40" },
  { text: "text-violet-500", bg: "bg-violet-500", tint: "bg-violet-500/10", border: "border-violet-500/40" },
  { text: "text-emerald-500", bg: "bg-emerald-500", tint: "bg-emerald-500/10", border: "border-emerald-500/40" },
  { text: "text-amber-500", bg: "bg-amber-500", tint: "bg-amber-500/10", border: "border-amber-500/40" },
  { text: "text-rose-500", bg: "bg-rose-500", tint: "bg-rose-500/10", border: "border-rose-500/40" },
  { text: "text-cyan-500", bg: "bg-cyan-500", tint: "bg-cyan-500/10", border: "border-cyan-500/40" },
  { text: "text-indigo-500", bg: "bg-indigo-500", tint: "bg-indigo-500/10", border: "border-indigo-500/40" },
  { text: "text-pink-500", bg: "bg-pink-500", tint: "bg-pink-500/10", border: "border-pink-500/40" },
] as const;

export type FolderColor = (typeof PALETTE)[number];

// Simple string hash (djb2) — doesn't need to be cryptographic, just stable
// and reasonably well-distributed across UUIDs.
function hash(id: string): number {
  let h = 5381;
  for (let i = 0; i < id.length; i++) {
    h = (h * 33) ^ id.charCodeAt(i);
  }
  return Math.abs(h);
}

export function folderColor(id: string): FolderColor {
  return PALETTE[hash(id) % PALETTE.length];
}

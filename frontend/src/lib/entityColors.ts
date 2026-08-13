// Entity-type -> Tailwind border/text classes, keyed by Neo4j label.
// Colors come from tailwind.config.js's `entity.*` tokens (04_FRONTEND_
// SPECIFICATION.md §3.1). Shared by PaperDetailModal, EntityDetailModal,
// and ContextPanel — centralized once a third consumer needed it (FE-004).
export const ENTITY_BORDER_CLASS: Record<string, string> = {
  Paper: "border-entity-paper text-entity-paper",
  Method: "border-entity-method text-entity-method",
  Dataset: "border-entity-dataset text-entity-dataset",
  Claim: "border-entity-claim text-entity-claim",
  Author: "border-entity-author text-entity-author",
  Metric: "border-entity-metric text-entity-metric",
};

export const DEFAULT_ENTITY_BORDER_CLASS = "border-border text-muted-foreground";

export function displayName(properties: Record<string, unknown>, fallback: string): string {
  return (
    (properties.canonical_name as string | undefined) ??
    (properties.name as string | undefined) ??
    (properties.title as string | undefined) ??
    (properties.text as string | undefined) ??
    fallback
  );
}

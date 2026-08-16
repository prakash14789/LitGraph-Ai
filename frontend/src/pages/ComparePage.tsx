import { GitCompare, Network, Send } from "lucide-react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";

import { GraphCanvas } from "@/components/GraphCanvas";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { litgraphApi } from "@/services/api";
import type { CompareQueryResponse, CompareVerdict } from "@/types";

const VERDICT_OPTIONS: { verdict: CompareVerdict; label: string }[] = [
  { verdict: "vanilla", label: "Vanilla was better" },
  { verdict: "graphrag", label: "GraphRAG was better" },
  { verdict: "tie_good", label: "Both equally good" },
  { verdict: "tie_bad", label: "Both bad" },
];

// COMPARE-001. Single-shot comparison, not a chat history — one query in,
// both systems' answers out, side by side. Reuses litgraphApi.compareQuery
// (RETRIEVAL-006's POST /query/compare), which already runs both pipelines
// concurrently server-side, so this page's own job is display only.
export function ComparePage() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CompareQueryResponse | null>(null);
  const [mobileTab, setMobileTab] = useState<"vanilla" | "graphrag">("graphrag");
  const [verdict, setVerdict] = useState<CompareVerdict | null>(null);

  const submit = async () => {
    const q = query.trim();
    if (!q || loading) return;
    setLoading(true);
    setError(null);
    setVerdict(null);
    try {
      const { data } = await litgraphApi.compareQuery(q);
      setResult(data);
    } catch {
      setError("Comparison failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  // COMPARE-002 — optional, changeable within session: each click just
  // re-POSTs and overwrites the previous verdict server-side.
  const vote = async (v: CompareVerdict) => {
    if (!result) return;
    setVerdict(v);
    try {
      await litgraphApi.voteCompare(result.query_log_id, v);
    } catch {
      // ponytail: a failed vote isn't worth its own error UI — it's an
      // optional, low-stakes self-improvement signal, not core functionality.
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border bg-card/40 p-4">
        <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-xl border border-border bg-card p-1.5 shadow-sm transition-shadow focus-within:shadow-md focus-within:ring-1 focus-within:ring-ring">
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void submit();
              }
            }}
            rows={1}
            placeholder="Ask a question to compare GraphRAG vs. vanilla RAG..."
            className="max-h-40 flex-1 resize-none bg-transparent px-2.5 py-1.5 text-sm focus-visible:outline-none"
          />
          <Button size="icon" onClick={() => void submit()} disabled={!query.trim() || loading} aria-label="Compare">
            <Send className="h-4 w-4" />
          </Button>
        </div>
        {error && <p className="mx-auto mt-2 max-w-3xl text-sm text-destructive">{error}</p>}
      </div>

      {/* Mobile tab switcher — desktop shows both panels side by side always. */}
      <div className="flex border-b border-border lg:hidden">
        {(["graphrag", "vanilla"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setMobileTab(tab)}
            className={cn(
              "flex-1 px-4 py-2 text-sm font-medium",
              mobileTab === tab
                ? "border-b-2 border-primary text-primary"
                : "text-muted-foreground"
            )}
          >
            {tab === "graphrag" ? "GraphRAG" : "Vanilla RAG"}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto lg:overflow-hidden">
        {!result && !loading && (
          <div className="flex h-full items-center justify-center text-center text-muted-foreground">
            Ask a question to compare both systems side by side.
          </div>
        )}

        <div className="grid h-full lg:grid-cols-2 lg:divide-x lg:divide-border">
          <div className={cn("lg:block", mobileTab === "graphrag" ? "block" : "hidden")}>
            <Panel
              title="GraphRAG"
              icon={Network}
              accentClass="border-t-primary"
              loading={loading}
              answer={result?.graphrag.answer}
            >
              {result && (
                <>
                  {/* POLISH-006 — same warning banner as ChatPage's MessageBubble */}
                  {result.graphrag.warning && (
                    <div className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
                      {result.graphrag.warning}
                    </div>
                  )}
                  <StatsRow
                    latencyMs={result.graphrag.retrieval_stats.latency_ms}
                    tokens={result.graphrag.retrieval_stats.context_tokens}
                    sourceCount={result.graphrag.citations.length}
                  />
                  {result.graphrag.retrieved_subgraph.nodes.length > 0 && (
                    <div className="mb-3 h-40 overflow-hidden rounded-lg border border-border">
                      <GraphCanvas
                        nodes={result.graphrag.retrieved_subgraph.nodes}
                        edges={result.graphrag.retrieved_subgraph.edges}
                        compact
                      />
                    </div>
                  )}
                </>
              )}
            </Panel>
          </div>

          <div className={cn("lg:block", mobileTab === "vanilla" ? "block" : "hidden")}>
            <Panel
              title="Vanilla RAG"
              icon={GitCompare}
              accentClass="border-t-muted-foreground"
              loading={loading}
              answer={result?.vanilla.answer}
            >
              {result && (
                <>
                  <StatsRow
                    latencyMs={result.vanilla.latency_ms}
                    tokens={result.vanilla.context_tokens}
                    sourceCount={result.vanilla.sources.length}
                  />
                  {result.vanilla.sources.length > 0 && (
                    <div className="mb-3 space-y-1.5">
                      {result.vanilla.sources.map((s, i) => (
                        <div key={i} className="rounded-lg border border-border bg-card p-2 text-xs shadow-sm">
                          <p className="truncate font-medium">{s.paper_title ?? "Untitled paper"}</p>
                          <p className="truncate text-muted-foreground">
                            {s.section_name} · score {s.score.toFixed(2)}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </Panel>
          </div>
        </div>

        {result && !loading && (
          <div className="flex flex-wrap items-center justify-center gap-2 border-t border-border p-4">
            <span className="mr-1 text-sm text-muted-foreground">Which answer was better?</span>
            {VERDICT_OPTIONS.map((opt) => (
              <Button
                key={opt.verdict}
                size="sm"
                variant={verdict === opt.verdict ? "default" : "outline"}
                onClick={() => void vote(opt.verdict)}
              >
                {opt.label}
              </Button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Panel({
  title,
  icon: Icon,
  accentClass,
  loading,
  answer,
  children,
}: {
  title: string;
  icon: typeof Network;
  accentClass: string;
  loading: boolean;
  answer: string | undefined;
  children?: React.ReactNode;
}) {
  return (
    <div className={cn("h-full overflow-y-auto border-t-4 bg-card/40 p-4", accentClass)}>
      <h2 className="mb-3 flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        <Icon className="h-4 w-4" />
        {title}
      </h2>

      {loading && (
        <div className="flex items-center gap-1 rounded-xl border border-border bg-card px-4 py-3 shadow-sm">
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.3s]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.15s]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground" />
        </div>
      )}

      {!loading && answer && (
        <>
          {children}
          <div className="markdown rounded-xl border border-border bg-card px-4 py-3 text-sm shadow-sm">
            <ReactMarkdown>{answer}</ReactMarkdown>
          </div>
        </>
      )}
    </div>
  );
}

function StatsRow({
  latencyMs,
  tokens,
  sourceCount,
}: {
  latencyMs: number;
  tokens: number;
  sourceCount: number;
}) {
  return (
    <div className="mb-3 flex gap-3 text-xs text-muted-foreground">
      <span>{latencyMs}ms</span>
      <span>{tokens} tokens</span>
      <span>{sourceCount} sources</span>
    </div>
  );
}

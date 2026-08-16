import { useQuery } from "@tanstack/react-query";
import { Send, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Link } from "react-router-dom";

import { ChatSidebar } from "@/components/ChatSidebar";
import { ContextPanel } from "@/components/ContextPanel";
import { EntityDetailModal } from "@/components/EntityDetailModal";
import { Button } from "@/components/ui/button";
import { folderColor } from "@/lib/folderColor";
import { cn } from "@/lib/utils";
import { litgraphApi } from "@/services/api";
import { type ChatMessage, useActiveMessages, useChatStore } from "@/store/chatStore";

// Purely a UX affordance for the empty state — fills the input, doesn't
// auto-send, so the user can still edit before asking. No backend change.
const EXAMPLE_PROMPTS = [
  "What methods outperform BERT on GLUE?",
  "How does RoBERTa's training differ from BERT's?",
  "Which papers introduce a new pretraining objective?",
];

export function ChatPage() {
  const { isLoading, error, send, retry, collectionId } = useChatStore();
  const messages = useActiveMessages();
  const [input, setInput] = useState("");
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Shares react-query's cache with ChatSidebar's own collections query
  // (same queryKey) — just for the active folder's display name here, not
  // a second network round-trip.
  const collectionsQuery = useQuery({
    queryKey: ["collections"],
    queryFn: () => litgraphApi.getCollections().then((r) => r.data),
  });
  const activeFolderName = collectionId
    ? (collectionsQuery.data?.find((c) => c.id === collectionId)?.name ?? "Folder")
    : "All papers";
  const activeFolderColor = collectionId ? folderColor(collectionId) : null;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  const submit = () => {
    if (!input.trim() || isLoading) return;
    send(input);
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  // FE-004's context panel always reflects the *latest* answer, not the
  // whole history.
  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");

  return (
    <div className="flex h-full">
      <ChatSidebar />

      <div className="mx-auto flex h-full w-full max-w-3xl flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-border px-4 py-2">
          <span className="text-xs text-muted-foreground">Chatting in</span>
          <span
            className={cn(
              "flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium",
              activeFolderColor ? cn(activeFolderColor.tint, activeFolderColor.text) : "text-foreground"
            )}
          >
            {activeFolderColor && <span className={cn("h-1.5 w-1.5 rounded-full", activeFolderColor.bg)} />}
            {activeFolderName}
          </span>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-6">
          {messages.length === 0 && !isLoading ? (
            <div className="flex h-full flex-col items-center justify-center gap-5 text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/20 via-primary/10 to-transparent shadow-inner">
                <Sparkles className="h-7 w-7 text-primary" />
              </div>
              <div>
                <p className="text-lg font-semibold text-foreground">Ask about {activeFolderName}</p>
                <p className="mt-1.5 text-sm text-muted-foreground">
                  Answers are grounded only in this folder's papers and their knowledge graph.
                </p>
              </div>
              <div className="flex flex-wrap justify-center gap-2">
                {EXAMPLE_PROMPTS.map((p) => (
                  <button
                    key={p}
                    onClick={() => setInput(p)}
                    className="rounded-full border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:text-foreground hover:shadow-md"
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              {messages.map((m) => (
                <MessageBubble key={m.id} message={m} />
              ))}
              {isLoading && <TypingIndicator />}
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {error && (
          <div className="mx-4 mb-2 flex items-center justify-between rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            <span>{error}</span>
            <Button size="sm" variant="outline" onClick={retry}>
              Retry
            </Button>
          </div>
        )}

        <div className="p-4">
          <div className="flex items-end gap-2 rounded-xl border border-border bg-card p-1.5 shadow-sm transition-shadow focus-within:shadow-md focus-within:ring-1 focus-within:ring-ring">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                e.target.style.height = "auto";
                e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit();
                }
              }}
              rows={1}
              placeholder="Ask a question about your papers..."
              className="max-h-40 flex-1 resize-none bg-transparent px-2.5 py-1.5 text-sm focus-visible:outline-none"
            />
            <Button size="icon" onClick={submit} disabled={!input.trim() || isLoading} aria-label="Send">
              <Send className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>

      <ContextPanel message={lastAssistant} onSelectEntity={setSelectedEntityId} />
      <EntityDetailModal
        subgraph={lastAssistant?.retrievedSubgraph}
        nodeId={selectedEntityId}
        onSelect={setSelectedEntityId}
        onClose={() => setSelectedEntityId(null)}
      />
    </div>
  );
}

function AssistantAvatar() {
  return (
    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-primary to-primary/70 shadow-sm shadow-primary/30">
      <Sparkles className="h-3.5 w-3.5 text-primary-foreground" />
    </div>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex gap-2.5", isUser ? "flex-row-reverse" : "flex-row")}>
      {!isUser && <AssistantAvatar />}
      <div className={cn("flex min-w-0 flex-col gap-2", isUser ? "items-end" : "items-start")}>
        <div
          className={cn(
            "max-w-[85%] rounded-2xl px-4 py-2.5 text-sm shadow-sm",
            isUser
              ? "rounded-br-sm bg-gradient-to-br from-primary to-primary/90 text-primary-foreground"
              : "rounded-bl-sm border border-border bg-card text-foreground"
          )}
        >
          {isUser ? (
            message.content
          ) : (
            <div className="markdown">
              <ReactMarkdown>{message.content}</ReactMarkdown>
            </div>
          )}
        </div>

        {message.citations && message.citations.length > 0 && (
          <div className="flex max-w-[85%] flex-wrap gap-2">
            {message.citations.map((c) => (
              // Links to the Papers list — that page's own detail modal
              // (FE-002) is the per-paper view; deep-linking straight to it
              // from here would need cross-page state, not worth it yet.
              <Link
                key={c.paper_id}
                to="/papers"
                className="rounded-md border border-border bg-card px-2.5 py-1.5 text-xs text-card-foreground shadow-sm transition-colors hover:border-entity-paper hover:text-entity-paper"
              >
                {c.title ?? "Untitled paper"}
                {c.year ? ` · ${c.year}` : ""}
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-start gap-2.5">
      <AssistantAvatar />
      <div className="flex items-center gap-1 rounded-2xl rounded-bl-sm border border-border bg-card px-4 py-3 shadow-sm">
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary/60 [animation-delay:-0.3s]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary/60 [animation-delay:-0.15s]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary/60" />
      </div>
    </div>
  );
}

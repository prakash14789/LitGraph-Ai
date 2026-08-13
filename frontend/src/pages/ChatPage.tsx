import { Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Link } from "react-router-dom";

import { ContextPanel } from "@/components/ContextPanel";
import { EntityDetailModal } from "@/components/EntityDetailModal";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { type ChatMessage, useChatStore } from "@/store/chatStore";

// Collection selector deliberately omitted (FE-003 ticket note): retrieval
// is global, not collection-scoped, so a selector here would either do
// nothing or misleadingly imply filtering. Add once POLISH-005b lands
// per-collection retrieval.
export function ChatPage() {
  const { messages, isLoading, error, send, retry } = useChatStore();
  const [input, setInput] = useState("");
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

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
      <div className="mx-auto flex h-full w-full max-w-3xl flex-1 flex-col">
        <div className="flex-1 overflow-y-auto px-4 py-6">
          {messages.length === 0 && !isLoading ? (
            <div className="flex h-full items-center justify-center text-center text-muted-foreground">
              Ask a question about your papers
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

        <div className="border-t border-border p-4">
          <div className="flex items-end gap-2">
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
              className="max-h-40 flex-1 resize-none rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex flex-col gap-2", isUser ? "items-end" : "items-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-lg px-4 py-2 text-sm",
          isUser ? "bg-primary text-primary-foreground" : "bg-muted text-foreground"
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
              className="rounded-md border border-border bg-card px-2.5 py-1.5 text-xs text-card-foreground transition-colors hover:border-entity-paper hover:text-entity-paper"
            >
              {c.title ?? "Untitled paper"}
              {c.year ? ` · ${c.year}` : ""}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-start">
      <div className="flex items-center gap-1 rounded-lg bg-muted px-4 py-3">
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.3s]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.15s]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground" />
      </div>
    </div>
  );
}

import { create } from "zustand";
import { persist } from "zustand/middleware";

import { litgraphApi } from "@/services/api";
import type { Citation, RetrievalStats, RetrievedSubgraph } from "@/types";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  retrievalStats?: RetrievalStats;
  retrievedSubgraph?: RetrievedSubgraph; // FE-004/FE-005: context panel + entity modal
}

// "Folder-wise chat": each collection (folder) keeps its own conversation
// thread, keyed by collection id — switching folders switches which thread
// is on screen, it doesn't wipe either one. "__all__" is the thread for no
// folder selected (the original global-corpus behavior's own history).
const ALL_PAPERS_KEY = "__all__";
const threadKey = (collectionId: string | null) => collectionId ?? ALL_PAPERS_KEY;

interface ChatState {
  messagesByCollection: Record<string, ChatMessage[]>;
  isLoading: boolean;
  error: string | null;
  lastQuery: string | null;
  collectionId: string | null; // POLISH-005b — null = global, unscoped
  send: (query: string) => void;
  retry: () => void;
  setCollectionId: (id: string | null) => void;
  newChat: () => void; // clears only the active folder's thread, not every folder's
}

let idCounter = 0;
const nextId = () => `msg-${Date.now()}-${++idCounter}`;

// Persisted (not session-only, unlike the pre-folder-chat version): a
// folder's whole point is picking up where you left off, so localStorage
// backs messagesByCollection via zustand's persist middleware. Everything
// else (isLoading/error/lastQuery) stays transient — a stale "loading"
// flag surviving a refresh would just wedge the UI.
export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => {
      const runQuery = async (query: string, pushUserBubble: boolean) => {
        const key = threadKey(get().collectionId);
        set((s) => ({
          messagesByCollection: pushUserBubble
            ? {
                ...s.messagesByCollection,
                [key]: [...(s.messagesByCollection[key] ?? []), { id: nextId(), role: "user", content: query }],
              }
            : s.messagesByCollection,
          isLoading: true,
          error: null,
          lastQuery: query,
        }));

        try {
          const { data } = await litgraphApi.query(query, get().collectionId);
          set((s) => ({
            messagesByCollection: {
              ...s.messagesByCollection,
              [key]: [
                ...(s.messagesByCollection[key] ?? []),
                {
                  id: nextId(),
                  role: "assistant",
                  content: data.answer,
                  citations: data.citations,
                  retrievalStats: data.retrieval_stats,
                  retrievedSubgraph: data.retrieved_subgraph,
                },
              ],
            },
            isLoading: false,
          }));
        } catch {
          set({ isLoading: false, error: "Something went wrong answering that question." });
        }
      };

      return {
        messagesByCollection: {},
        isLoading: false,
        error: null,
        lastQuery: null,
        collectionId: null,

        send: (query: string) => {
          const trimmed = query.trim();
          if (!trimmed || get().isLoading) return;
          void runQuery(trimmed, true);
        },

        retry: () => {
          const q = get().lastQuery;
          if (q && !get().isLoading) void runQuery(q, false);
        },

        // No longer clears history on switch — that's the whole point of a
        // folder having its own thread now. Just changes which thread (and
        // which retrieval scope) is active.
        setCollectionId: (id: string | null) => set({ collectionId: id, error: null }),

        newChat: () => {
          const key = threadKey(get().collectionId);
          set((s) => ({
            messagesByCollection: { ...s.messagesByCollection, [key]: [] },
            error: null,
          }));
        },
      };
    },
    { name: "litgraph-chat-threads" }
  )
);

// ChatPage reads this instead of reaching into messagesByCollection itself.
export function useActiveMessages(): ChatMessage[] {
  const collectionId = useChatStore((s) => s.collectionId);
  const messagesByCollection = useChatStore((s) => s.messagesByCollection);
  return messagesByCollection[threadKey(collectionId)] ?? [];
}

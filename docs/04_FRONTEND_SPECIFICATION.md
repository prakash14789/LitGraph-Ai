# LitGraph — Frontend Specification Document

> **Version:** 1.0  
> **Last Updated:** August 11, 2026  
> **Author:** Prakash  
> **Status:** Draft  

---

## 1. Overview

LitGraph frontend is a React + TypeScript SPA with four primary views: Chat (Q&A), Graph Explorer (visualization), Papers (management), and Compare (GraphRAG vs vanilla RAG side-by-side). The frontend communicates exclusively via REST API with the FastAPI backend.

---

## 2. Tech Stack

| Technology | Purpose |
|-----------|---------|
| **React 18+** | UI framework |
| **TypeScript** | Type safety |
| **Tailwind CSS** | Utility-first styling |
| **shadcn/ui** | Component library (built on Radix UI primitives) |
| **Cytoscape.js** | Graph/network visualization |
| **React Router v6** | Client-side routing |
| **Zustand** | State management (lighter than Redux) |
| **Axios** | HTTP client |
| **React Query (TanStack Query)** | Server state management, caching, polling |
| **react-dropzone** | File upload drag-and-drop |
| **react-markdown** | Render markdown in chat answers |
| **Lucide React** | Icon set |
| **Vite** | Build tool + dev server |

---

## 3. Design System

### 3.1 Color Palette

```
┌──────────────────────────────────────────────────────────┐
│  LITGRAPH COLOR SYSTEM                                    │
│                                                           │
│  Primary (Brand)                                          │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐            │
│  │ #1E3A5F│ │ #2563EB│ │ #3B82F6│ │ #93C5FD│            │
│  │ Navy   │ │ Blue   │ │ Light  │ │ Pale   │            │
│  │ (dark  │ │ (main  │ │ Blue   │ │ Blue   │            │
│  │  bg)   │ │  CTA)  │ │ (hover)│ │ (tags) │            │
│  └────────┘ └────────┘ └────────┘ └────────┘            │
│                                                           │
│  Neutrals                                                 │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐│
│  │ #0F172A│ │ #1E293B│ │ #334155│ │ #94A3B8│ │ #F8FAFC││
│  │ Slate  │ │ Slate  │ │ Slate  │ │ Slate  │ │ Slate  ││
│  │ 900    │ │ 800    │ │ 700    │ │ 400    │ │ 50     ││
│  │ (text) │ │ (cards)│ │(border)│ │(muted) │ │  (bg)  ││
│  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘│
│                                                           │
│  Entity Type Colors (Graph Nodes)                        │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐│
│  │ #3B82F6│ │ #10B981│ │ #F59E0B│ │ #EF4444│ │ #8B5CF6││
│  │ Blue   │ │ Green  │ │ Amber  │ │ Red    │ │ Purple ││
│  │ PAPER  │ │ METHOD │ │ DATASET│ │ CLAIM  │ │ AUTHOR ││
│  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘│
│                                                           │
│  Semantic                                                 │
│  ┌────────┐ ┌────────┐ ┌────────┐                       │
│  │ #10B981│ │ #F59E0B│ │ #EF4444│                       │
│  │ Success│ │ Warning│ │ Error  │                       │
│  └────────┘ └────────┘ └────────┘                       │
│                                                           │
│  Dark Mode: Invert neutrals. Brand colors stay.          │
│  Default: Light mode. Toggle in header.                   │
└──────────────────────────────────────────────────────────┘
```

### 3.2 Typography

| Element | Font | Size | Weight |
|---------|------|------|--------|
| H1 (page title) | Inter | 28px (1.75rem) | 700 (Bold) |
| H2 (section title) | Inter | 22px (1.375rem) | 600 (Semibold) |
| H3 (card title) | Inter | 18px (1.125rem) | 600 |
| Body | Inter | 15px (0.9375rem) | 400 (Regular) |
| Body small | Inter | 13px (0.8125rem) | 400 |
| Code / Monospace | JetBrains Mono | 14px (0.875rem) | 400 |
| Chat answer text | Inter | 15px | 400 |
| Citation tag | Inter | 12px (0.75rem) | 500 (Medium) |
| Button label | Inter | 14px (0.875rem) | 500 |

### 3.3 Spacing & Layout

```
Base unit: 4px

Spacing scale:
  xs:   4px   (0.25rem)
  sm:   8px   (0.5rem)
  md:  16px   (1rem)
  lg:  24px   (1.5rem)
  xl:  32px   (2rem)
  2xl: 48px   (3rem)
  3xl: 64px   (4rem)

Card border-radius: 12px (0.75rem)
Button border-radius: 8px (0.5rem)
Input border-radius: 8px
Tag border-radius: 9999px (full round)

Shadows:
  Card: 0 1px 3px rgba(0,0,0,0.1), 0 1px 2px rgba(0,0,0,0.06)
  Modal: 0 20px 25px rgba(0,0,0,0.1), 0 10px 10px rgba(0,0,0,0.04)
  Dropdown: 0 4px 6px rgba(0,0,0,0.1)
```

### 3.4 Component Library (shadcn/ui components used)

| Component | Where Used |
|-----------|-----------|
| `Button` | All CTAs, form submits, actions |
| `Input` | Search, chat input |
| `Card` | Paper cards, entity detail cards |
| `Dialog` | Entity detail modal, paper detail modal |
| `Badge` | Entity type tags, relationship type tags |
| `Tabs` | Chat/Graph/Papers/Compare navigation |
| `Toast` | Success/error notifications |
| `Progress` | Ingestion progress bar |
| `Tooltip` | Graph node hover info |
| `Select` | Collection picker, filter dropdowns |
| `ScrollArea` | Chat message history, paper list |
| `Skeleton` | Loading placeholders |
| `Separator` | Section dividers |
| `DropdownMenu` | Paper actions (delete, move) |
| `Sheet` | Mobile sidebar |
| `Switch` | Dark mode toggle |
| `Textarea` | Extended chat input |

---

## 4. Page Layouts & Wireframes

### 4.1 Global Layout

```
┌─────────────────────────────────────────────────────────────┐
│  HEADER (h: 56px, sticky top)                               │
│  ┌──────┐  ┌─────────────────────────────────┐  ┌────────┐ │
│  │ Logo │  │ Chat │ Graph │ Papers │ Compare  │  │ 🌓 User│ │
│  │ Lit  │  │  ▂▂▂                             │  │ menu   │ │
│  │ Graph│  │ (active tab underlined)           │  │        │ │
│  └──────┘  └─────────────────────────────────┘  └────────┘ │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  MAIN CONTENT AREA                                          │
│  (fills remaining viewport height, no outer scroll)         │
│  (each page manages its own scroll internally)              │
│                                                             │
│                                                             │
│                                                             │
│                                                             │
└─────────────────────────────────────────────────────────────┘

Responsive breakpoints:
  Mobile:  < 768px   (single column, hamburger menu)
  Tablet:  768-1024px (condensed layout)
  Desktop: > 1024px  (full layout)
```

### 4.2 Chat Page

```
┌─────────────────────────────────────────────────────────────┐
│  HEADER                                                      │
├────────────────────────────────────┬────────────────────────┤
│                                    │                         │
│  CHAT PANEL (flex: 1)              │  CONTEXT PANEL          │
│  (max-width: 720px, centered)      │  (width: 360px,         │
│                                    │   collapsible)          │
│  ┌──────────────────────────────┐  │                         │
│  │ 🧑 What methods improved on  │  │  Shows for current      │
│  │    BERT for QA tasks?        │  │  answer:                │
│  └──────────────────────────────┘  │                         │
│                                    │  ┌─────────────────────┐│
│  ┌──────────────────────────────┐  │  │ RETRIEVED SUBGRAPH  ││
│  │ 🤖 Several methods extended  │  │  │ (mini Cytoscape)    ││
│  │    BERT for QA:              │  │  │                     ││
│  │                              │  │  │  ●BERT              ││
│  │    **SpanBERT** [Wang, 2019] │  │  │  ├──●SpanBERT       ││
│  │    extended BERT by using    │  │  │  ├──●ALBERT          ││
│  │    span-level pre-training...│  │  │  └──●RoBERTa         ││
│  │                              │  │  │                     ││
│  │    **ALBERT** [Lan, 2019]    │  │  └─────────────────────┘│
│  │    reduced parameters while  │  │                         │
│  │    maintaining performance...│  │  ┌─────────────────────┐│
│  │                              │  │  │ SOURCES USED        ││
│  │    ┌──────────────────────┐  │  │  │ 📄 SpanBERT (2019) ││
│  │    │ 📄 Wang 2019  │ 📄 Lan│  │  │ 📄 ALBERT (2019)    ││
│  │    │ 📄 Liu 2019          │  │  │ 📄 RoBERTa (2019)    ││
│  │    │ (citation cards)     │  │  │  └─────────────────────┘│
│  │    └──────────────────────┘  │  │                         │
│  └──────────────────────────────┘  │  ┌─────────────────────┐│
│                                    │  │ ENTITY TAGS         ││
│                                    │  │ 🟢METHOD SpanBERT   ││
│  ┌──────────────────────────────┐  │  │ 🟢METHOD ALBERT     ││
│  │ (No collection selector —    │  │  │ 🟡DATASET SQuAD    ││
│  │  MVP retrieval is global,    │  │  │ 🔵PAPER Wang 2019  ││
│  │  see FE-003 note. Don't add  │  │  │ (clickable → modal) ││
│  │  one here until POLISH-005b  │  │  └─────────────────────┘│
│  │  ships real filtering.)      │  │                         │
│  │  ┌─────────────────────┐     │  │  ┌─────────────────────┐│
│  │  │ Ask a question...   │ [→] │  │  │ [◀ Hide Panel]      ││
│  │  └─────────────────────┘     │  │  └─────────────────────┘│
│  └──────────────────────────────┘  │                         │
├────────────────────────────────────┴────────────────────────┤
│  On mobile: Context panel hidden. Tap "View sources" button  │
│  below answer to slide panel up from bottom (Sheet).         │
└─────────────────────────────────────────────────────────────┘
```

**Chat Message Component Detail:**

```
┌──────────────────────────────────────────────────┐
│  USER MESSAGE                                     │
│  ┌──────────────────────────────────────────────┐│
│  │ bg: slate-100 (light) / slate-800 (dark)     ││
│  │ border-radius: 12px                          ││
│  │ padding: 16px                                ││
│  │ max-width: 85%                               ││
│  │ float: right                                 ││
│  │                                              ││
│  │ "What methods improved on BERT for QA?"      ││
│  └──────────────────────────────────────────────┘│
│                                                   │
│  ASSISTANT MESSAGE                                │
│  ┌──────────────────────────────────────────────┐│
│  │ bg: white (light) / slate-900 (dark)         ││
│  │ border-left: 3px solid #2563EB               ││
│  │ padding: 16px                                ││
│  │ max-width: 85%                               ││
│  │ float: left                                  ││
│  │                                              ││
│  │ [Rendered Markdown content]                  ││
│  │                                              ││
│  │ ┌──────────────────────────────────────────┐ ││
│  │ │ CITATIONS (horizontal scroll on mobile)  │ ││
│  │ │ ┌─────────────┐ ┌─────────────┐         │ ││
│  │ │ │📄 Wang 2019 │ │📄 Lan 2019  │ ...     │ ││
│  │ │ │ SpanBERT... │ │ ALBERT...   │         │ ││
│  │ │ └─────────────┘ └─────────────┘         │ ││
│  │ └──────────────────────────────────────────┘ ││
│  │                                              ││
│  │ [👍] [👎] [View Graph ↗] [Copy]             ││
│  └──────────────────────────────────────────────┘│
└──────────────────────────────────────────────────┘
```

### 4.3 Graph Explorer Page

```
┌─────────────────────────────────────────────────────────────┐
│  HEADER                                                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  TOOLBAR (h: 48px)                                          │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ [Collection: ▼]  [Filter: ▼ Entity Type]             │    │
│  │ [Search entities...        ] [Zoom+] [Zoom-] [Reset] │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────────────────────────────┬───────────────┐    │
│  │                                      │               │    │
│  │  GRAPH CANVAS (Cytoscape.js)         │ ENTITY DETAIL │    │
│  │  (fills available space)             │ PANEL         │    │
│  │                                      │ (w: 320px)    │    │
│  │      ●─────●──────●                  │               │    │
│  │     / \    |      / \                │ ┌───────────┐ │    │
│  │    ●   ●   ●     ●   ●              │ │ BERT      │ │    │
│  │    |       |         |               │ │ Type:     │ │    │
│  │    ●       ●─────────●              │ │  METHOD   │ │    │
│  │                                      │ │           │ │    │
│  │  LEGEND:                             │ │ Category: │ │    │
│  │  ● Paper  ● Method  ● Dataset       │ │  Language │ │    │
│  │  ● Claim  ● Author                  │ │  Model    │ │    │
│  │  ── CITES  ── EXTENDS               │ │           │ │    │
│  │  ── CONTRADICTS  ── USES            │ │ Introduced│ │    │
│  │                                      │ │ by:       │ │    │
│  │  (nodes draggable, zoomable,         │ │ Devlin    │ │    │
│  │   pannable)                          │ │ et al,    │ │    │
│  │                                      │ │ 2018      │ │    │
│  │  Layout: Force-directed (default)    │ │           │ │    │
│  │  Options: [Force] [Hierarchy] [Grid] │ │ Used by:  │ │    │
│  │                                      │ │ 12 papers │ │    │
│  │                                      │ │           │ │    │
│  │                                      │ │ Extended  │ │    │
│  │                                      │ │ by:       │ │    │
│  │                                      │ │ SpanBERT, │ │    │
│  │                                      │ │ ALBERT,   │ │    │
│  │                                      │ │ RoBERTa   │ │    │
│  │                                      │ └───────────┘ │    │
│  └──────────────────────────────────────┴───────────────┘    │
│                                                              │
│  On mobile: Full-screen graph. Detail panel = bottom sheet.  │
└─────────────────────────────────────────────────────────────┘
```

**Graph Node Styling:**

| Entity Type | Shape | Color | Size |
|------------|-------|-------|------|
| Paper | Rectangle (rounded) | #3B82F6 (Blue) | Based on citation count |
| Method | Circle | #10B981 (Green) | Based on number of papers using it |
| Dataset | Diamond | #F59E0B (Amber) | Based on number of evaluations |
| Claim | Triangle | #EF4444 (Red) | Fixed size |
| Author | Hexagon | #8B5CF6 (Purple) | Based on paper count |

**Implementation note:** these size metrics (citation count, papers-using-it count, evaluation count) are **computed counts, not stored properties** — they don't exist on the Neo4j node schema (architecture doc §4.2) and aren't listed in `GRAPH-001`'s acceptance criteria today. Whoever builds `GRAPH-001` needs to add a `COUNT()` aggregation (e.g. `MATCH (m:Method)<-[:USES_METHOD]-(p:Paper) RETURN m, count(p) AS usage_count`) to the subgraph/overview queries and include it in the API response — it's a small addition, just not currently spelled out as a requirement anywhere.

**Edge Styling:**

| Relationship | Line Style | Color | Label |
|-------------|-----------|-------|-------|
| CITES | Solid, thin | #94A3B8 (gray) | None |
| EXTENDS | Solid, medium | #10B981 (green) | "extends" |
| CONTRADICTS | Dashed, medium | #EF4444 (red) | "contradicts" |
| USES_METHOD | Dotted, thin | #3B82F6 (blue) | None |
| EVALUATES_ON | Dotted, thin | #F59E0B (amber) | Metric + value |
| OUTPERFORMS | Solid, thick | #10B981 (green) | "outperforms" + margin |
| INTRODUCES | Solid, medium | #8B5CF6 (purple) | "introduces" |

### 4.4 Papers Management Page

```
┌─────────────────────────────────────────────────────────────┐
│  HEADER                                                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ [Collection: ▼ All Papers]  [Search papers...]          ││
│  │                                                          ││
│  │ ┌────────────────────────────────────────────────────┐   ││
│  │ │         📄                                         │   ││
│  │ │    Drop PDFs here                                  │   ││
│  │ │    or click to upload                              │   ││
│  │ │                                                    │   ││
│  │ │    Also: [Paste ArXiv URL]                         │   ││
│  │ │    (dashed border, bg: slate-50)                   │   ││
│  │ └────────────────────────────────────────────────────┘   ││
│  │                                                          ││
│  │  PAPER LIST                                             ││
│  │  ┌──────────────────────────────────────────────────┐   ││
│  │  │ 📄 Attention Is All You Need                     │   ││
│  │  │    Vaswani et al., 2017 · NeurIPS                │   ││
│  │  │    ┌──────┐ ┌──────┐ ┌──────┐                    │   ││
│  │  │    │✅Done│ │7 ents│ │12 rel│  [⋮ menu]          │   ││
│  │  │    └──────┘ └──────┘ └──────┘                    │   ││
│  │  ├──────────────────────────────────────────────────┤   ││
│  │  │ 📄 BERT: Pre-training of Deep Bidirectional...   │   ││
│  │  │    Devlin et al., 2018 · NAACL                   │   ││
│  │  │    ┌───────────────────────────────────┐          │   ││
│  │  │    │ ████████████░░░░ 73% Extracting   │ [cancel] │   ││
│  │  │    └───────────────────────────────────┘          │   ││
│  │  ├──────────────────────────────────────────────────┤   ││
│  │  │ 📄 SpanBERT: Improving Pre-training...           │   ││
│  │  │    Wang et al., 2019 · TACL                      │   ││
│  │  │    ┌──────┐ ┌──────┐ ┌──────┐                    │   ││
│  │  │    │✅Done│ │5 ents│ │8 rels│  [⋮ menu]          │   ││
│  │  │    └──────┘ └──────┘ └──────┘                    │   ││
│  │  └──────────────────────────────────────────────────┘   ││
│  │                                                          ││
│  │  GRAPH STATS (bottom card)                              ││
│  │  ┌──────────────────────────────────────────────────┐   ││
│  │  │  Papers: 24  │  Methods: 47  │  Datasets: 18    │   ││
│  │  │  Claims: 89  │  Relations: 203  │  Authors: 61   │   ││
│  │  └──────────────────────────────────────────────────┘   ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘

Paper [⋮ menu] options:
  - View details (opens modal with full extraction)
  - View in graph (switches to Graph page, highlights this paper)
  - Move to collection
  - Re-process (re-run extraction)
  - Delete paper
```

### 4.5 Compare Page (GraphRAG vs Vanilla RAG)

```
┌─────────────────────────────────────────────────────────────┐
│  HEADER                                                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  [Ask a question to compare both systems...]       [→]  ││
│  │  (No collection selector — MVP retrieval is global,     ││
│  │   both systems query the full corpus. See RETRIEVAL-001 ││
│  │   scoping note / POLISH-005b.)                          ││
│  └─────────────────────────────────────────────────────────┘│
│                                                              │
│  ┌──────────────────────────┬──────────────────────────┐    │
│  │ VANILLA RAG              │ GRAPHRAG (LitGraph)      │    │
│  │ (left panel)             │ (right panel)            │    │
│  │                          │                          │    │
│  │ RETRIEVED:               │ RETRIEVED:               │    │
│  │ ┌──────────────────────┐ │ ┌──────────────────────┐ │    │
│  │ │ 10 text chunks       │ │ │ Subgraph:            │ │    │
│  │ │ (list with scores)   │ │ │ 8 nodes, 12 edges    │ │    │
│  │ │                      │ │ │ (mini graph viz)     │ │    │
│  │ │ Chunk 1 (0.89): "..." │ │ │                      │ │    │
│  │ │ Chunk 2 (0.85): "..." │ │ │ ●BERT → ●SpanBERT   │ │    │
│  │ │ Chunk 3 (0.82): "..." │ │ │  ↓                   │ │    │
│  │ │ ...                   │ │ │ ●SQuAD               │ │    │
│  │ └──────────────────────┘ │ └──────────────────────┘ │    │
│  │                          │                          │    │
│  │ ANSWER:                  │ ANSWER:                  │    │
│  │ ┌──────────────────────┐ │ ┌──────────────────────┐ │    │
│  │ │ "Based on the        │ │ │ "Several methods     │ │    │
│  │ │  retrieved passages, │ │ │  extended BERT for   │ │    │
│  │ │  BERT was improved..."│ │ │  QA: SpanBERT       │ │    │
│  │ │                      │ │ │  (extends BERT,      │ │    │
│  │ │ (often incomplete    │ │ │  +2.3 F1 on SQuAD), │ │    │
│  │ │  or misses multi-hop │ │ │  ALBERT (reduces    │ │    │
│  │ │  connections)        │ │ │  params 18x)..."    │ │    │
│  │ └──────────────────────┘ │ └──────────────────────┘ │    │
│  │                          │                          │    │
│  │ Latency: 2.1s            │ Latency: 5.8s            │    │
│  │ Tokens: 1,200            │ Tokens: 1,850            │    │
│  │ Sources: 3 chunks        │ Sources: 5 papers,       │    │
│  │                          │   3 methods, 1 dataset   │    │
│  └──────────────────────────┴──────────────────────────┘    │
│                                                              │
│  On mobile: Stacked vertically (Vanilla on top, Graph below) │
│  with toggle tabs instead of side-by-side.                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Component Hierarchy

```
App
├── Header
│   ├── Logo
│   ├── Navigation (Tabs: Chat | Graph | Papers | Compare)
│   ├── CollectionSelector (dropdown — scopes Papers page filtering and Graph page
│   │     data per GRAPH-001/INGEST-007. Does NOT scope Chat or Compare answers;
│   │     MVP retrieval is global, see RETRIEVAL-001. Component may still render on
│   │     every page for layout consistency, but on Chat/Compare it should be either
│   │     hidden or visibly non-functional for filtering — see FE-003 note.)
│   └── UserMenu (dark mode toggle, settings, logout)
│
├── ChatPage
│   ├── ChatHistory (ScrollArea)
│   │   ├── UserMessage
│   │   └── AssistantMessage
│   │       ├── MarkdownRenderer
│   │       ├── CitationCardList
│   │       │   └── CitationCard (paper title, year, link)
│   │       └── MessageActions (thumbs up/down, copy, view graph — ⚠️ no ticket
│   │             currently builds the thumbs up/down backend. `COMPARE-002` only
│   │             wires voting into `query_log.user_feedback` for the Compare page.
│   │             If per-chat-answer feedback is wanted for MVP, it needs its own
│   │             ticket — e.g. extend `RETRIEVAL-005`'s query endpoint response
│   │             with a `query_log_id` and add a small `POST /query/{id}/feedback`
│   │             endpoint. Not currently scoped; treat as P2 until ticketed.)
│   ├── ChatInput
│   │   ├── Textarea (auto-resize)
│   │   └── SendButton
│   └── ContextPanel (collapsible sidebar)
│       ├── SubgraphMiniView (small Cytoscape)
│       ├── SourcesList
│       └── EntityTagList
│           └── EntityTag (clickable → EntityDetailModal)
│
├── GraphPage
│   ├── GraphToolbar
│   │   ├── EntitySearch (Input)
│   │   ├── FilterDropdowns (entity type, relationship type)
│   │   ├── LayoutSelector (force, hierarchy, grid)
│   │   └── ZoomControls
│   ├── GraphCanvas (Cytoscape.js wrapper)
│   │   ├── Nodes (styled by entity type)
│   │   ├── Edges (styled by relationship type)
│   │   └── Legend
│   └── EntityDetailPanel (sidebar)
│       ├── EntityHeader (name, type badge)
│       ├── EntityProperties
│       ├── RelatedEntities (linked list)
│       └── SourcePapers (list of papers mentioning entity)
│
├── PapersPage
│   ├── UploadZone (react-dropzone)
│   │   └── ArxivUrlInput
│   ├── PaperList
│   │   └── PaperCard
│   │       ├── PaperMeta (title, authors, year, venue)
│   │       ├── IngestionStatus (progress bar or badges)
│   │       └── PaperActions (dropdown: view, graph, delete)
│   ├── GraphStats (summary card)
│   └── PaperDetailModal
│       ├── PaperMeta
│       ├── ExtractedEntities (grouped by type)
│       ├── ExtractedRelationships (list with evidence)
│       └── RawSections (collapsible text)
│
├── ComparePage
│   ├── CompareInput (shared query input)
│   ├── CompareResults
│   │   ├── VanillaPanel
│   │   │   ├── RetrievedChunks (scored list)
│   │   │   ├── Answer (markdown)
│   │   │   └── Stats (latency, tokens, sources)
│   │   └── GraphRAGPanel
│   │       ├── RetrievedSubgraph (mini Cytoscape)
│   │       ├── Answer (markdown with citations)
│   │       └── Stats (latency, tokens, sources)
│   └── VerdictBanner (which system answered better — optional user vote)
│
└── Shared Components
    ├── EntityDetailModal
    ├── LoadingSkeleton
    ├── ErrorBoundary
    ├── ToastNotification
    └── EmptyState (illustrations for no papers, no results, etc.)
```

---

## 6. State Management

### 6.1 Zustand Stores

```typescript
// stores/chatStore.ts
interface ChatStore {
  messages: Message[];
  isLoading: boolean;
  currentContext: RetrievedContext | null;

  sendQuery: (query: string) => Promise<void>;
  clearHistory: () => void;
}

// stores/graphStore.ts
interface GraphStore {
  graphData: { nodes: GraphNode[]; edges: GraphEdge[] } | null;
  selectedEntity: GraphNode | null;
  filters: { entityTypes: string[]; relationTypes: string[] };
  layout: "force" | "hierarchy" | "grid";

  loadSubgraph: (entityId: string, hops: number) => Promise<void>;
  loadFullGraph: (collectionId: string) => Promise<void>;
  selectEntity: (node: GraphNode | null) => void;
  setFilters: (filters: Partial<GraphStore["filters"]>) => void;
  setLayout: (layout: GraphStore["layout"]) => void;
}

// stores/paperStore.ts
interface PaperStore {
  papers: Paper[];
  uploadProgress: Record<string, UploadStatus>;
  graphStats: GraphStats | null;

  uploadPapers: (files: File[]) => Promise<void>;
  ingestArxiv: (url: string) => Promise<void>;
  deletePaper: (id: string) => Promise<void>;
  pollIngestionStatus: (jobId: string) => void;
  refreshPapers: () => Promise<void>;
}
```

### 6.2 Server State (React Query)

```typescript
// React Query handles caching, polling, and refetching for server data

// Papers list — refetch on upload/delete
const { data: papers } = useQuery({
  queryKey: ["papers", collectionId],
  queryFn: () => api.getPapers(collectionId),
});

// Ingestion status — poll every 3 seconds while processing
const { data: jobStatus } = useQuery({
  queryKey: ["ingestion", jobId],
  queryFn: () => api.getIngestionStatus(jobId),
  refetchInterval: (data) =>
    data?.status === "completed" || data?.status === "failed" ? false : 3000,
});

// Graph data — cache aggressively
const { data: graphData } = useQuery({
  queryKey: ["graph", collectionId],
  queryFn: () => api.getGraphOverview(collectionId),
  staleTime: 5 * 60 * 1000,  // 5 min cache
});
```

---

## 7. API Integration

### 7.1 API Client

**MVP note:** LitGraph MVP has no authentication (Security §2.1) — there is no `/auth/login` or `/auth/refresh` endpoint, and no ticket builds one. The client below reflects that: no JWT interceptor, no token storage. When auth is added later (out of MVP scope), follow Security §2.1's actual pattern — refresh tokens in **HttpOnly cookies**, not `localStorage`, and the refresh call goes through the same configured `api` client (not a bare `axios.post` with a separately-set `withCredentials`, which was a bug in an earlier draft of this doc — it bypassed the base client's config and didn't match the cookie-based flow the security doc specifies). Don't copy a JWT interceptor into this file until an actual `/auth/*` API exists to call.

```typescript
// services/api.ts
import axios from "axios";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1",
  timeout: 60000,  // 60s (queries can be slow)
});

// No auth interceptors in MVP — there is no auth. Add JWT/cookie handling here
// only once an actual /auth/login + /auth/refresh API exists (see note above).

export const litgraphApi = {
  // Ingest
  uploadPapers: (files: File[], collectionId: string) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    form.append("collection_id", collectionId);
    return api.post("/ingest/upload", form);
  },
  ingestArxiv: (url: string, collectionId: string) =>
    api.post("/ingest/arxiv", { url, collection_id: collectionId }),
  getIngestionStatus: (jobId: string) =>
    api.get(`/ingest/status/${jobId}`),

  // Query — NOTE: no collection_id param. Per RETRIEVAL-001's MVP scoping decision,
  // retrieval is global across all ingested papers, not filtered by collection.
  // Do not add a collectionId argument here until POLISH-005b (deferred, P2) actually
  // implements collection-filtered retrieval on the backend — sending a collection_id
  // the API ignores is worse than not sending one, since it implies filtering happens.
  query: (query: string) =>
    api.post("/query", { query }),
  compareQuery: (query: string) =>
    api.post("/query/compare", { query }),

  // Graph
  getGraphOverview: (collectionId: string) =>
    api.get(`/graph/overview?collection_id=${collectionId}`),
  getSubgraph: (entityId: string, hops: number) =>
    api.get(`/graph/subgraph?entity_id=${entityId}&hops=${hops}`),
  getEntityDetail: (entityId: string) =>
    api.get(`/graph/entity/${entityId}`),
  searchEntities: (query: string, type?: string) =>
    api.get(`/graph/search?q=${query}${type ? `&type=${type}` : ""}`),

  // Papers
  getPapers: (collectionId?: string) =>
    api.get(`/papers${collectionId ? `?collection_id=${collectionId}` : ""}`),
  getPaper: (id: string) => api.get(`/papers/${id}`),
  deletePaper: (id: string) => api.delete(`/papers/${id}`),

  // Collections
  getCollections: () => api.get("/collections"),
  createCollection: (name: string) => api.post("/collections", { name }),
  deleteCollection: (id: string) => api.delete(`/collections/${id}`),
};
```

---

## 8. Key Interactions & Behaviors

### 8.1 Paper Upload Flow

```
User drags PDFs into upload zone
  → Immediate: files appear in paper list with "Uploading..." status
  → POST /ingest/upload (multipart form data)
  → Backend returns: { job_ids: ["job_1", "job_2", ...] }
  → Each paper card shows progress bar
  → Frontend polls GET /ingest/status/{job_id} every 3 seconds
  → Progress bar updates: "Parsing..." → "Extracting entities..." →
    "Extracting relationships..." → "Resolving entities..." → "Writing graph..."
  → On completion: progress bar → green "✅ Done" badge + entity/relation counts
  → Graph stats card auto-refreshes
  → Toast notification: "3 papers processed. 24 entities, 38 relationships extracted."
```

### 8.2 Chat Query Flow

```
User types question → hits Enter or clicks Send
  → Input disabled, loading indicator in chat
  → POST /query { query }   (no collection_id — MVP retrieval is global, see RETRIEVAL-001)
  → Backend processes (5-10 seconds)
  → Response arrives:
    {
      answer: "markdown text with [Author, Year] citations...",
      citations: [{ paper_id, title, authors, year }],
      retrieved_subgraph: { nodes: [...], edges: [...] },
      retrieval_stats: { vector_results: 10, graph_nodes: 47, final_nodes: 20 }
    }
  → Chat adds assistant message (markdown rendered)
  → Citation cards appear below answer
  → Context panel updates: mini subgraph + sources + entity tags
  → Input re-enabled
```

### 8.3 Graph Exploration Flow

```
User navigates to Graph page
  → Full graph loads for current collection (may be large)
  → Force-directed layout animates into position
  → User clicks a node (e.g., "BERT" Method node)
    → Node highlights (border glow + slightly enlarged)
    → Connected edges highlight
    → Entity Detail Panel slides in from right
    → Panel shows: name, type, description, related entities, source papers
  → User clicks "SpanBERT" in related entities list
    → Graph pans/zooms to center on SpanBERT
    → SpanBERT node highlights, detail panel updates
  → User double-clicks a node
    → Triggers 2-hop subgraph expansion from that node
    → New nodes/edges animate into the graph
  → User types in Entity Search bar: "transformer"
    → Matching nodes pulse/highlight in the graph
    → Graph pans to center on the cluster of matching nodes
```

### 8.4 Loading States

| State | Visual |
|-------|--------|
| Initial page load | Full-page skeleton (shadcn Skeleton) |
| Chat query processing | Typing indicator (3 dots animation) in chat + disabled input |
| Paper ingestion | Progress bar with step label inside paper card |
| Graph loading | Canvas shows loading spinner + "Loading graph..." |
| Entity search | Input shows spinner icon in right side |
| No papers uploaded | Illustration + "Upload your first papers to get started" CTA |
| No results for query | "I couldn't find relevant information in your papers for this query." |

### 8.5 Error States

| Error | UI Treatment |
|-------|-------------|
| Upload failed (file too large / wrong type) | Toast: red, with specific message. File card shows error state. |
| Ingestion failed (extraction error) | Paper card: red "❌ Failed" badge. Tooltip: error message. Option to retry. |
| Query failed (LLM timeout) | Chat: error message bubble: "Couldn't process your question right now. Please try again." + retry button. |
| Network error | Toast: "Connection lost. Retrying..." + auto-retry with backoff. |
| Graph empty (no papers) | Full empty state with illustration + upload CTA. |

---

## 9. Responsive Design

| Component | Desktop (>1024px) | Tablet (768-1024px) | Mobile (<768px) |
|-----------|-------------------|--------------------|-----------------| 
| Navigation | Horizontal tabs in header | Same | Hamburger → side drawer |
| Chat + Context | Side-by-side panels | Context panel collapses to icon | Context as bottom sheet on tap |
| Graph + Detail | Side-by-side | Detail panel overlays graph | Full-screen graph, detail as bottom sheet |
| Compare | Side-by-side panels | Side-by-side (narrower) | Stacked with toggle tabs |
| Paper list | Multi-column grid | 2-column | Single column |
| Upload zone | Full width, tall | Full width, medium | Compact, button-style |

---

## 10. Accessibility

| Requirement | Implementation |
|------------|---------------|
| Keyboard navigation | All interactive elements focusable + keyboard-operable. Tab order logical. |
| Screen reader | ARIA labels on graph nodes, buttons, modals. Role attributes on custom components. |
| Color contrast | All text meets WCAG AA (4.5:1 for normal, 3:1 for large text). Entity colors tested for contrast. |
| Focus indicators | Visible focus ring on all interactive elements (Tailwind `ring-2 ring-blue-500`). |
| Motion | Respect `prefers-reduced-motion`: disable graph layout animation, loading animations. |
| Alt text | Citation cards include paper title as alt text. Graph nodes have tooltip descriptions. |
import { Moon, Network } from "lucide-react";
import { NavLink } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// 04_FRONTEND_SPECIFICATION.md §4.1 — sticky header, 4 nav tabs. UserMenu
// (dark mode toggle, per §5) lands with POLISH-003, not this ticket —
// FE-001's own acceptance criteria only needs the 4 tabs navigating.
const TABS = [
  { to: "/chat", label: "Chat" },
  { to: "/graph", label: "Graph" },
  { to: "/papers", label: "Papers" },
  { to: "/compare", label: "Compare" },
] as const;

export function Header() {
  return (
    <header className="sticky top-0 z-10 flex h-14 items-center justify-between border-b border-border bg-background/80 px-4 shadow-sm backdrop-blur supports-[backdrop-filter]:bg-background/70">
      <div className="flex items-center gap-2.5 font-semibold tracking-tight text-foreground">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-primary/70 shadow-md shadow-primary/40 ring-1 ring-primary/20">
          <Network className="h-4 w-4 text-primary-foreground" />
        </div>
        <span className="bg-gradient-to-r from-foreground to-foreground/70 bg-clip-text">LitGraph</span>
      </div>

      <nav className="flex items-center gap-1 rounded-lg border border-border/60 bg-muted/40 p-1">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            className={({ isActive }) =>
              cn(
                "relative rounded-md px-3 py-1.5 text-sm font-medium transition-all",
                isActive
                  ? "bg-card text-primary shadow-sm after:absolute after:inset-x-2.5 after:-bottom-1 after:h-0.5 after:rounded-full after:bg-primary"
                  : "text-muted-foreground hover:text-foreground"
              )
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>

      {/* UserMenu placeholder — real dark mode toggle (persisted, Cytoscape-
          aware) lands with POLISH-003. Disabled for now so it's not a
          non-functional-looking live control. */}
      <Button variant="ghost" size="icon" disabled aria-label="Dark mode (coming soon)">
        <Moon className="h-4 w-4" />
      </Button>
    </header>
  );
}

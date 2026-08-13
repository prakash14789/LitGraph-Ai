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
    <header className="sticky top-0 z-10 flex h-14 items-center justify-between border-b border-border bg-background px-4">
      <div className="flex items-center gap-2 font-semibold text-foreground">
        <Network className="h-5 w-5 text-primary" />
        LitGraph
      </div>

      <nav className="flex items-center gap-1">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            className={({ isActive }) =>
              cn(
                "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
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

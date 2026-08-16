// POLISH-003. Cytoscape renders to <canvas> (GraphCanvas.tsx), so it can't
// react to Tailwind's `dark` class or CSS custom properties on its own —
// isDarkMode()/onThemeChange() exist so canvas-drawn colors can be kept in
// sync with the same toggle that drives every DOM-rendered page.

export type Theme = "light" | "dark";

const STORAGE_KEY = "litgraph-theme";
const THEME_CHANGE_EVENT = "litgraph:theme-change";

// Pure — no DOM/localStorage access, so it's covered by theme.check.ts
// without needing a jsdom-style test environment this project doesn't have.
export function resolveInitialTheme(stored: Theme | null, prefersDark: boolean): Theme {
  return stored ?? (prefersDark ? "dark" : "light");
}

function readStoredTheme(): Theme | null {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === "light" || stored === "dark" ? stored : null;
}

export function getInitialTheme(): Theme {
  return resolveInitialTheme(
    readStoredTheme(),
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
  localStorage.setItem(STORAGE_KEY, theme);
  window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: theme }));
}

export function isDarkMode(): boolean {
  return document.documentElement.classList.contains("dark");
}

export function onThemeChange(handler: (theme: Theme) => void): () => void {
  const listener = (e: Event) => handler((e as CustomEvent<Theme>).detail);
  window.addEventListener(THEME_CHANGE_EVENT, listener);
  return () => window.removeEventListener(THEME_CHANGE_EVENT, listener);
}

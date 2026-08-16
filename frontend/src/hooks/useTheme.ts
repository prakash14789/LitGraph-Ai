import { useCallback, useEffect, useState } from "react";

import { applyTheme, getInitialTheme, type Theme } from "@/lib/theme";

// POLISH-003. index.html's inline head script already set the `dark` class
// (and localStorage key) before React mounted, to avoid a flash of the
// wrong theme — this effect's first run just re-applies the same value,
// which is a no-op paint-wise, and is what makes every toggle afterward
// persist + notify GraphCanvas (see lib/theme.ts's onThemeChange).
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }, []);

  return { theme, toggleTheme };
}

// Manual self-check for theme.ts's pure logic — see graphElements.check.ts
// for why this project uses plain assert scripts instead of a test runner.
// Run: node src/lib/theme.check.ts
import assert from "node:assert/strict";

import { resolveInitialTheme } from "./theme.ts";

// A stored preference always wins over the system preference.
assert.equal(resolveInitialTheme("dark", false), "dark");
assert.equal(resolveInitialTheme("light", true), "light");

// No stored preference falls back to the system preference.
assert.equal(resolveInitialTheme(null, true), "dark");
assert.equal(resolveInitialTheme(null, false), "light");

console.log("theme.check.ts: all checks passed");

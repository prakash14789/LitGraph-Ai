// Manual self-check for folderColor.ts — see graphElements.check.ts for the
// convention (no test framework in this project). Run:
// node src/lib/folderColor.check.ts
import assert from "node:assert/strict";

import { folderColor } from "./folderColor.ts";

// Deterministic: same id always gets the same color.
const a1 = folderColor("collection-abc");
const a2 = folderColor("collection-abc");
assert.equal(a1.text, a2.text);

// Different ids can (and generally do) land on different colors — not a
// strict guarantee for every pair, but two very different strings should
// exercise more than one palette slot across a decent sample.
const seen = new Set(
  ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"].map((id) => folderColor(id).text)
);
assert.ok(seen.size > 1, "expected more than one distinct color across 10 different ids");

console.log("folderColor.check.ts: all checks passed");

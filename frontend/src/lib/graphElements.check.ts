// Manual self-check for graphElements.ts's pure logic (nodeSize/edgeLabel/
// toElements) — no test framework in this project yet, so this runs
// directly via Node's built-in TS support instead of adding one for 3
// functions. Run: node src/lib/graphElements.check.ts
import assert from "node:assert/strict";

import { edgeLabel, fcoseLayoutOptions, neighborIds, nodeSize, toElements } from "./graphElements.ts";

// nodeSize: Claim is always fixed size regardless of usage_count.
assert.equal(nodeSize(["Claim"], 999), 30);
assert.equal(nodeSize(["Claim"], null), 30);

// nodeSize: grows with usage_count but clamps at 70, sqrt-scaled so it
// doesn't blow up for a heavily-cited Method/Paper.
assert.equal(nodeSize(["Method"], 0), 24);
assert.equal(nodeSize(["Method"], null), 24);
assert.equal(nodeSize(["Method"], 4), 44); // 24 + sqrt(4)*10 = 44
assert.ok(nodeSize(["Method"], 10_000) <= 70);

// nodeSize: GRAPH-004's compact mode uses a tighter base/clamp, still fixed
// for Claim.
assert.equal(nodeSize(["Claim"], 999, true), 18);
assert.equal(nodeSize(["Method"], 0, true), 14);
assert.ok(nodeSize(["Method"], 10_000, true) <= 40);
assert.ok(nodeSize(["Method"], 4, true) < nodeSize(["Method"], 4, false));

// edgeLabel: static labels from the style table.
assert.equal(edgeLabel("EXTENDS", {}), "extends");
assert.equal(edgeLabel("USES_METHOD", {}), ""); // no label in the spec table
assert.equal(edgeLabel("UNKNOWN_TYPE", {}), ""); // falls through to the default, no crash

// edgeLabel: EVALUATES_ON/OUTPERFORMS build their label from edge properties.
assert.equal(edgeLabel("EVALUATES_ON", { metric: "F1", value: "92.3" }), "F1 92.3");
assert.equal(edgeLabel("EVALUATES_ON", {}), "");
assert.equal(edgeLabel("OUTPERFORMS", { margin: "+3.2pts" }), "outperforms +3.2pts");
assert.equal(edgeLabel("OUTPERFORMS", {}), "outperforms"); // falls back to the static label

// toElements: builds one Cytoscape node element per input node, keyed by id.
const elements = toElements(
  [
    { id: "n1", labels: ["Paper"], properties: { title: "Paper One" } },
    { id: "n2", labels: ["Method"], properties: { canonical_name: "TransformerX" }, usage_count: 2 },
  ],
  [{ source: "n1", target: "n2", rel_type: "USES_METHOD", properties: {} }]
);
const nodeEls = elements.filter((e) => !("source" in e.data));
const edgeEls = elements.filter((e) => "source" in e.data);
assert.equal(nodeEls.length, 2);
assert.equal(edgeEls.length, 1);
assert.equal((edgeEls[0].data as { source: string }).source, "n1");

// toElements: silently drops an edge that references a node outside the
// given set, rather than emitting an element Cytoscape would reject.
const withDanglingEdge = toElements(
  [{ id: "n1", labels: ["Paper"], properties: {} }],
  [{ source: "n1", target: "not-in-set", rel_type: "USES_METHOD", properties: {} }]
);
assert.equal(withDanglingEdge.filter((e) => "source" in e.data).length, 0);

// toElements: GRAPH-004's compact mode drops edge labels entirely.
const compactElements = toElements(
  [
    { id: "n1", labels: ["Paper"], properties: {} },
    { id: "n2", labels: ["Method"], properties: {} },
  ],
  [{ source: "n1", target: "n2", rel_type: "EXTENDS", properties: {} }],
  true
);
const compactEdge = compactElements.find((e) => "source" in e.data) as
  | { data: { edgeLabel: string } }
  | undefined;
assert.equal(compactEdge?.data.edgeLabel, "");

// fcoseLayoutOptions: compact mode uses a tighter ideal edge length, same
// as nodeSize's compact clamp.
assert.equal(fcoseLayoutOptions(false).idealEdgeLength, 90);
assert.equal(fcoseLayoutOptions(true).idealEdgeLength, 60);

// neighborIds: finds both outgoing and incoming neighbors, de-duped, and
// ignores edges that don't touch the given node.
const graph = [
  { source: "p1", target: "m1", rel_type: "USES_METHOD", properties: {} },
  { source: "p1", target: "c1", rel_type: "REPORTS_RESULT", properties: {} },
  { source: "m1", target: "p1", rel_type: "INTRODUCES", properties: {} }, // duplicate direction
  { source: "m1", target: "d1", rel_type: "EVALUATES_ON", properties: {} },
];
assert.deepEqual(new Set(neighborIds("p1", graph)), new Set(["m1", "c1"]));
assert.equal(neighborIds("not-in-graph", graph).length, 0);

console.log("graphElements.check.ts: all checks passed");

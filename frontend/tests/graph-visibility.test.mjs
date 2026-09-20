import assert from "node:assert/strict";
import test from "node:test";

import { loadTs } from "./_load-ts.mjs";

const { filterGraph, graphSignature, groupNodesByType, isHiddenByType } = loadTs(
  "features/knowledge-graph/lib/graph-visibility.ts",
);

const node = (id, type, extra = {}) => ({ id, type, label: id, degree: 0, sources: [], ...extra });
const edge = (source, target, type = "relates_to") => ({
  id: `${source}->${target}`,
  source,
  target,
  type,
});

const graph = {
  nodes: [
    node("민규", "person"),
    node("희원", "person"),
    node("맥락이", "project"),
    node("범위 결정", "decision"),
    node("킥오프", "event"),
    node("킥오프 회의록", "event", { material: true, kind: "Meeting" }),
    node("외톨이", "task"),
  ],
  edges: [
    edge("민규", "킥오프", "participates_in"),
    edge("희원", "킥오프", "participates_in"),
    edge("민규", "범위 결정", "decided"),
    edge("범위 결정", "맥락이"),
    edge("민규", "킥오프 회의록", "participates_in"),
  ],
};
const ids = (items) => items.map((item) => item.id);

test("hiding a type removes its nodes and every edge that lost an endpoint", () => {
  const result = filterGraph(graph, ["person"], false);

  assert.deepEqual(ids(result.nodes), ["맥락이", "범위 결정", "킥오프", "킥오프 회의록", "외톨이"]);
  assert.deepEqual(ids(result.edges), ["범위 결정->맥락이"]);
});

test("material nodes follow their own chip, not the event chip", () => {
  assert.equal(isHiddenByType(node("m", "event", { material: true }), ["event"]), false);
  assert.equal(isHiddenByType(node("e", "event"), ["event"]), true);

  const result = filterGraph(graph, ["event"], false);
  assert.equal(ids(result.nodes).includes("킥오프"), false);
  assert.equal(ids(result.nodes).includes("킥오프 회의록"), true);
});

test("an as-of view drops nodes that had no relation yet", () => {
  assert.equal(ids(filterGraph(graph, [], true).nodes).includes("외톨이"), false);
  assert.equal(filterGraph(graph, [], false), graph);
});

test("filtering in two stages (canvas base, then hidden types) equals filtering once", () => {
  // 캔버스는 앞 단계의 그래프를 받고 종류만 가립니다. 목록·상세 패널과 결과가 같아야 합니다.
  for (const hidden of [[], ["person"], ["event", "decision"], ["project", "task", "person"]]) {
    for (const hideIsolated of [false, true]) {
      const once = filterGraph(graph, hidden, hideIsolated);
      const staged = filterGraph(filterGraph(graph, [], hideIsolated), hidden, false);
      assert.deepEqual(ids(staged.nodes), ids(once.nodes));
      assert.deepEqual(ids(staged.edges), ids(once.edges));
    }
  }
});

test("the signature ignores order and labels, and changes when an element is added", () => {
  const reordered = {
    nodes: [...graph.nodes].reverse().map((entry) => ({ ...entry, label: `${entry.label}!` })),
    edges: [...graph.edges].reverse(),
  };
  assert.equal(graphSignature(reordered), graphSignature(graph));

  const grown = { ...graph, nodes: [...graph.nodes, node("새 노드", "task")] };
  assert.notEqual(graphSignature(grown), graphSignature(graph));
  const rewired = { ...graph, edges: [...graph.edges, edge("희원", "맥락이")] };
  assert.notEqual(graphSignature(rewired), graphSignature(graph));
});

test("the keyboard list groups nodes in legend order, skips empty groups, and sorts by name", () => {
  const groups = groupNodesByType(filterGraph(graph, ["task"], false).nodes);

  assert.deepEqual(
    groups.map((group) => [group.label, ids(group.nodes)]),
    [
      ["사람", ["민규", "희원"]],
      ["프로젝트", ["맥락이"]],
      ["결정", ["범위 결정"]],
      ["이벤트", ["킥오프"]],
      ["회의·문서 자료", ["킥오프 회의록"]],
    ],
  );
});

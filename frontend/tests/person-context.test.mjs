import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const exports = {};
vm.runInNewContext(
  ts.transpileModule(
    fs.readFileSync(
      new URL("../src/features/directory/lib/person-context.ts", import.meta.url),
      "utf8",
    ),
    {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    },
  ).outputText,
  { exports, Map, Set },
);
const { buildPersonContext } = exports;
const person = { id: "person-1", workspaceId: "w1", name: "동명이인" };
const node = (id, type, extra = {}) => ({ id, type, label: id, degree: 0, sources: [], ...extra });
const edge = (source, target, kind) => ({
  id: `${source}-${target}-${kind}`,
  source,
  target,
  kind,
  type: "relates_to",
});

test("membership survives missing graph and includes project owner without cross-workspace leakage", () => {
  const projects = [
    { id: "member", workspaceId: "w1", participantIds: [person.id] },
    { id: "owner", workspaceId: "w1", ownerPersonId: person.id },
    { id: "other", workspaceId: "w2", participantIds: [person.id] },
  ];
  const result = buildPersonContext(person, projects, null);
  assert.equal(result.projects.map((p) => p.id).join(","), "member,owner");
  assert.equal(result.tasks.length, 0);
});

test("task and attended event paths provide context without claiming decision authorship", () => {
  const graph = {
    nodes: [
      node("p", "person", { directoryId: person.id, directoryKind: "Person" }),
      node("task", "task"),
      node("meeting", "event", { kind: "Meeting" }),
      node("d1", "decision"),
      node("d2", "decision"),
      node("unrelated", "decision"),
      node("project", "project"),
    ],
    edges: [
      edge("task", "p", "ASSIGNED_TO"),
      edge("p", "task", "WORKS_ON"),
      edge("p", "meeting", "PARTICIPATED_IN"),
      edge("task", "d1", "RELATED_TO"),
      edge("d2", "meeting", "DECIDED_IN"),
      edge("p", "project", "WORKS_ON"),
      edge("project", "unrelated", "RELATED_TO"),
      edge("missing", "p", "PARTICIPATED_IN"),
    ],
  };
  const result = buildPersonContext(person, [], graph);
  assert.equal(result.tasks.length, 1);
  assert.equal(result.tasks[0].decisions[0].node.id, "d1");
  assert.equal(result.events[0].node.id, "meeting");
  assert.equal(result.decisions.map((d) => d.node.id).join(","), "d1,d2");
  assert.equal(result.decisions[1].via.id, "meeting");
  assert.match(result.decisions[1].relation, /참여한/);
});

test("same-name people, document mentions and shared source evidence never imply participation", () => {
  const graph = {
    nodes: [
      node("p", "person", { directoryId: person.id, directoryKind: "Person" }),
      node("same-name", "person", { label: person.name }),
      node("task", "task"),
      node("doc", "event", { kind: "Document" }),
      node("meeting", "event", { kind: "Meeting" }),
    ],
    edges: [
      edge("same-name", "task", "ASSIGNED_TO"),
      edge("p", "doc", "CREATED"),
      edge("p", "meeting", "MENTIONED_IN"),
    ],
  };
  const result = buildPersonContext(person, [], graph);
  assert.equal(result.tasks.length + result.events.length + result.decisions.length, 0);
});

test("stored person-decision links and attended meeting evidence preserve decision history", () => {
  const graph = {
    nodes: [
      node("p", "person", { directoryId: person.id, directoryKind: "Person" }),
      node("meeting", "event", { kind: "Meeting", material: true }),
      node("old", "decision", { supersededBy: "new" }),
      node("new", "decision"),
    ],
    edges: [
      edge("p", "old", "DECIDED_IN"),
      edge("p", "meeting", "PARTICIPATED_IN"),
      edge("old", "meeting", "MENTIONED_IN"),
      edge("new", "meeting", "MENTIONED_IN"),
    ],
  };
  const result = buildPersonContext(person, [], graph);
  assert.equal(result.decisions.length, 2);
  assert.equal(result.decisions[0].node.supersededBy, "new");
  assert.equal(result.decisions[0].via, undefined);
  assert.equal(result.decisions[1].relation, "참여한 회의 자료에 언급된 결정");
});

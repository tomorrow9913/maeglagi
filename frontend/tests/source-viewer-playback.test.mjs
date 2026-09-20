import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

import * as errorMessage from "../src/lib/api/error-message.ts";

function viewerHarness(api, { demo = true, content = { kind: "meeting", title: "Meeting", hasRecording: true, chunks: [{ id: "c1", text: "Hello", startSeconds: 12 }] } } = {}) {
  const slots = [];
  const effects = [];
  const timers = new Map();
  let cursor = 0;
  let dirty = false;
  let tree;
  let timerId = 0;
  let now = Date.now();
  class FakeDate extends Date { static now() { return now; } }
  const audio = {
    currentTime: 0,
    currentSrc: "",
    paused: true,
    readyState: 0,
    listeners: new Map(),
    play() { this.paused = false; return Promise.resolve(); },
    addEventListener(name, listener) { this.listeners.set(name, listener); },
    removeEventListener(name, listener) { if (this.listeners.get(name) === listener) this.listeners.delete(name); },
    metadata() { this.readyState = 1; this.listeners.get("loadedmetadata")?.(); },
  };
  const same = (a, b) => a && b && a.length === b.length && a.every((value, i) => Object.is(value, b[i]));
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = initial;
      return [slots[index], (next) => {
        const value = typeof next === "function" ? next(slots[index]) : next;
        if (!Object.is(value, slots[index])) { slots[index] = value; dirty = true; }
      }];
    },
    useRef(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = { current: initial };
      return slots[index];
    },
    useCallback(fn, deps) {
      const index = cursor++;
      if (!slots[index] || !same(slots[index].deps, deps)) slots[index] = { fn, deps };
      return slots[index].fn;
    },
    useEffect(fn, deps) {
      const index = cursor++;
      if (!effects[index] || !same(effects[index].deps, deps)) {
        effects[index]?.cleanup?.();
        effects[index] = { fn, deps, run: true };
      }
    },
  };
  const jsx = (type, props) => {
    if (type === "audio") {
      audio.currentSrc = props.src;
      audio.readyState = 0;
      props.ref.current = audio;
    }
    return { type, props };
  };
  const exports = {};
  const code = ts.transpileModule(fs.readFileSync(new URL("../src/features/source-ingestion/components/source-viewer.tsx", import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  vm.runInNewContext(code, {
    exports,
    require(name) {
      if (name === "react") return react;
      if (name === "react/jsx-runtime") return { jsx, jsxs: jsx };
      if (name === "@/lib/api/context") return { useApi: () => api, useDemoMode: () => demo };
      if (name === "@/hooks/use-async") return { useAsync: () => ({ data: content, isLoading: false }) };
      if (name === "@/lib/utils") return { cn: (...parts) => parts.filter(Boolean).join(" ") };
      if (name === "sonner") return { toast: { error() {}, success() {} } };
      if (name === "@/lib/api/error-message") return errorMessage;
      if (name === "lucide-react") return { FileText: "FileText", Mic: "Mic" };
      if (name === "@/components/ui/button") return { Button: "Button" };
      if (name === "@/components/ui/spinner") return { Spinner: "Spinner" };
      if (name === "@/components/common/state-views") return { ErrorState: "ErrorState" };
      if (name === "@/components/ui/sheet") return { Sheet: "Sheet", SheetContent: "SheetContent", SheetDescription: "SheetDescription", SheetHeader: "SheetHeader", SheetTitle: "SheetTitle" };
      throw new Error(name);
    },
    window: { setTimeout(fn, delay) { const id = ++timerId; timers.set(id, { fn, delay }); return id; }, clearTimeout(id) { timers.delete(id); } },
    Date: FakeDate,
    setTimeout() { return 1; }, clearTimeout() {},
  });
  const render = (sourceId = "s1", highlightChunkId) => {
    do {
      dirty = false;
      cursor = 0;
      tree = exports.SourceViewer({ workspaceId: "w1", sourceId, highlightChunkId, onClose() {} });
      for (const effect of effects) if (effect?.run) { effect.run = false; effect.cleanup = effect.fn(); }
    } while (dirty);
  };
  const find = (predicate, node = tree) => {
    if (!node || typeof node !== "object") return undefined;
    if (Array.isArray(node)) return node.map((child) => find(predicate, child)).find(Boolean);
    if (predicate(node)) return node;
    const children = node.props?.children;
    return (Array.isArray(children) ? children : [children]).map((child) => child == null ? undefined : find(predicate, child)).find(Boolean);
  };
  return { render, find, audio, timers, advance(ms) { now += ms; } };
}

test("playback URL refreshes before expiry, keeps position, and retries only after a media error click", async () => {
  const replies = [];
  const api = {
    listSources: async () => [], listPeople: async () => [], listProjects: async () => [],
    getSourcePlaybackUrl() { return new Promise((resolve) => replies.push(resolve)); },
  };
  const view = viewerHarness(api);
  const button = () => view.find((node) => node.type === "Button" && typeof node.props.children === "string" && node.props.children.startsWith("녹음"));
  view.render();
  button().props.onClick();
  assert.equal(replies.length, 1);
  replies.shift()({ url: "first", expiresAt: new Date(Date.now() + 31_000).toISOString() });
  await new Promise(setImmediate);
  view.render();
  assert.equal(view.find((node) => node.type === "audio").props.src, "first");
  view.audio.currentTime = 45;
  view.audio.paused = false;
  const refresh = [...view.timers.values()].find((timer) => timer.delay < 31_000);
  assert.ok(refresh, "refresh is scheduled before expiration");
  view.advance(refresh.delay + 1);
  refresh.fn();
  button().props.onClick();
  assert.equal(replies.length, 1, "timer and click share one request");
  replies.shift()({ url: "second", expiresAt: new Date(Date.now() + 300_000).toISOString() });
  await new Promise(setImmediate);
  view.render();
  view.audio.metadata();
  view.render();
  assert.equal(view.audio.currentTime, 45);
  assert.equal(view.audio.paused, false);
  view.find((node) => node.type === "audio").props.onError({ currentTarget: view.audio });
  view.render();
  assert.equal(replies.length, 0, "media error does not retry automatically");
  assert.equal(button().props.children, "녹음 다시 시도");
  button().props.onClick();
  assert.equal(replies.length, 1);
  replies.shift()({ url: "third", expiresAt: new Date(Date.now() + 300_000).toISOString() });
  await new Promise(setImmediate);
  view.render();
  view.audio.metadata();
  view.render();
  assert.equal(view.audio.currentTime, 45);
});

test("saved review text remains visible without chunks and timestamps can seek recording", async () => {
  const api = { listSources: async () => [], listPeople: async () => [], listProjects: async () => [], getSourcePlaybackUrl: async () => ({ url: "recording", expiresAt: new Date(Date.now() + 300_000).toISOString() }) };
  const view = viewerHarness(api, { content: {
    kind: "meeting", title: "Confirmed draft", hasRecording: true, originalText: "민규: 수정한 원문",
    utterances: [{ id: "turn-1", speakerName: "민규", text: "수정한 원문", startSeconds: 9 }], chunks: [],
  } });
  view.render();
  const saved = view.find((node) => node.type === "section" && node.props["aria-label"] === "저장된 원문");
  assert.ok(saved);
  assert.match(JSON.stringify(saved), /수정한 원문/);
  assert.equal(view.find((node) => node.type === "section" && node.props["aria-label"] === "인용된 구간"), undefined);
  view.find((node) => node.type === "button" && JSON.stringify(node.props.children).includes("0:09")).props.onClick();
  await new Promise(setImmediate);
  view.render();
  view.audio.metadata();
  view.render();
  assert.equal(view.audio.currentTime, 9);
});

test("indexed evidence is still reachable by its real chunk ID", () => {
  const api = { listSources: async () => [], listPeople: async () => [], listProjects: async () => [] };
  const view = viewerHarness(api, { content: {
    kind: "meeting", title: "Confirmed draft", hasRecording: false, originalText: "수정한 원문",
    utterances: [], chunks: [{ id: "real-chunk", text: "Indexed excerpt" }],
  } });
  view.render("s1", "real-chunk");
  assert.ok(view.find((node) => node.type === "section" && node.props["aria-label"] === "저장된 원문"));
  assert.ok(view.find((node) => node.type === "section" && node.props["aria-label"] === "인용된 구간"));
  assert.ok(view.find((node) => node.type === "li" && JSON.stringify(node.props.children).includes("Indexed excerpt")));
});

const flush = () => new Promise(setImmediate);
const source = (id, associations = [], projectIds = []) => ({
  id, kind: "meeting", associationRevision: 1, associations, projectIds,
});

function sourceApi(sources, onSave) {
  return {
    listSources: async () => sources,
    listPeople: async () => [{ id: "person-1", name: "Kim", archivedAt: null }],
    listProjects: async () => [{ id: "project-1", name: "Project", archivedAt: null }],
    updateSourceAssociations: onSave,
  };
}

test("source switch hides old associations immediately and ignores an old save response", async () => {
  const pending = [];
  const sources = [source("s1", [{ personId: "person-1", role: "participant" }], ["project-1"]), source("s2")];
  const api = sourceApi(sources, (workspaceId, sourceId, input) => new Promise((resolve) => pending.push({ sourceId, input, resolve })));
  const view = viewerHarness(api, { demo: false });
  const saveButton = () => view.find((node) => node.type === "Button" && node.props.children === "연결 저장");
  const selected = () => view.find((node) => node.type === "input" && node.props["aria-label"] === "Kim 참여자");
  view.render("s1"); await flush(); view.render("s1");
  assert.equal(selected().props.checked, true);
  saveButton().props.onClick();
  assert.equal(pending.length, 1);
  view.render("s2");
  assert.equal(saveButton(), undefined, "old source controls disappear on the first new-source render");
  await flush(); view.render("s2");
  assert.equal(selected().props.checked, false);
  pending[0].resolve({ revision: 2, projectIds: ["project-1"], people: [{ personId: "person-1", role: "participant" }] });
  await flush(); view.render("s2");
  assert.equal(selected().props.checked, false, "old save cannot update the new source");
});

test("a person with participant and author roles keeps both on save", async () => {
  let saved;
  const associations = [{ personId: "person-1", role: "participant" }, { personId: "person-1", role: "author" }];
  const api = sourceApi([source("s1", associations)], async (workspaceId, sourceId, input) => { saved = input; return { revision: 2, projectIds: [], people: input.people }; });
  const view = viewerHarness(api, { demo: false });
  view.render(); await flush(); view.render();
  assert.equal(view.find((node) => node.type === "input" && node.props["aria-label"] === "Kim 참여자").props.checked, true);
  assert.equal(view.find((node) => node.type === "input" && node.props["aria-label"] === "Kim 작성자").props.checked, true);
  view.find((node) => node.type === "Button" && node.props.children === "연결 저장").props.onClick();
  await flush();
  assert.deepEqual(JSON.parse(JSON.stringify(saved.people)), associations);
});

test("archived selected project and person role can be removed but not added again", async () => {
  let saved;
  const api = sourceApi([source("s1", [{ personId: "person-1", role: "author" }], ["project-1"])], async (workspaceId, sourceId, input) => { saved = input; return { revision: 2, projectIds: input.projectIds, people: input.people }; });
  api.listPeople = async () => [{ id: "person-1", name: "Kim", archivedAt: "2026-09-01" }];
  api.listProjects = async () => [{ id: "project-1", name: "Project", archivedAt: "2026-09-01" }];
  const view = viewerHarness(api, { demo: false });
  const project = () => view.find((node) => node.type === "input" && node.props.checked && !node.props["aria-label"]);
  const author = () => view.find((node) => node.type === "input" && node.props["aria-label"] === "Kim 작성자");
  const participant = () => view.find((node) => node.type === "input" && node.props["aria-label"] === "Kim 참여자");
  view.render(); await flush(); view.render();
  assert.equal(project().props.disabled, false);
  assert.equal(author().props.disabled, false);
  assert.equal(participant().props.disabled, true);
  project().props.onChange({ target: { checked: false } });
  author().props.onChange({ target: { checked: false } });
  view.render();
  assert.equal(project(), undefined);
  view.find((node) => node.type === "Button" && node.props.children === "연결 저장").props.onClick();
  await flush();
  assert.deepEqual(JSON.parse(JSON.stringify(saved)), { revision: 1, projectIds: [], people: [] });
});

test("late source-list response cannot restore associations from a previous source", async () => {
  const pending = [];
  const api = sourceApi([], async () => { throw new Error("unexpected save"); });
  api.listSources = () => new Promise((resolve) => pending.push(resolve));
  const view = viewerHarness(api, { demo: false });
  const selected = () => view.find((node) => node.type === "input" && node.props["aria-label"] === "Kim 참여자");
  view.render("s1");
  view.render("s2");
  pending[1]([source("s2")]);
  await flush(); view.render("s2");
  assert.equal(selected().props.checked, false);
  pending[0]([source("s1", [{ personId: "person-1", role: "participant" }])]);
  await flush(); view.render("s2");
  assert.equal(selected().props.checked, false);
});

test("a failed association load shows the reason with a retry instead of rendering nothing", async () => {
  let calls = 0;
  const api = sourceApi([source("s1")], async () => { throw new Error("unexpected save"); });
  api.listSources = async () => { calls += 1; if (calls === 1) throw new Error("boom"); return [source("s1")]; };
  const view = viewerHarness(api, { demo: false });
  const alert = () => view.find((node) => node.type === "div" && node.props.role === "alert");
  const saveButton = () => view.find((node) => node.type === "Button" && node.props.children === "연결 저장");
  view.render();
  assert.ok(view.find((node) => node.type === "p" && node.props.role === "status"), "loading placeholder before the first response");
  await flush(); view.render();
  assert.match(JSON.stringify(alert()), /프로젝트·사람 연결을 불러오지 못했습니다/);
  assert.equal(saveButton(), undefined);
  view.find((node) => node.type === "Button" && node.props.children === "다시 시도").props.onClick();
  view.render(); await flush(); view.render();
  assert.equal(alert(), undefined);
  assert.ok(saveButton());
});

test("a missing evidence chunk is announced and timestamps describe the playback action", () => {
  const api = { listSources: async () => [], listPeople: async () => [], listProjects: async () => [] };
  const view = viewerHarness(api, { content: {
    kind: "meeting", title: "Meeting", hasRecording: true, originalText: "민규: 원문",
    utterances: [{ id: "turn-1", speakerName: "민규", text: "원문", startSeconds: 83 }], chunks: [{ id: "other", text: "Other" }],
  } });
  view.render("s1", "missing-chunk");
  assert.ok(view.find((node) => node.type === "p" && JSON.stringify(node.props.children).includes("인용된 구간을 찾지 못해 원문 전체를 보여줍니다.")));
  assert.equal(view.find((node) => node.type === "button" && JSON.stringify(node.props.children).includes("1:23")).props["aria-label"], "1:23부터 녹음 듣기");
});

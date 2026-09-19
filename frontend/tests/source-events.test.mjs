import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

function load(relative, modules = {}, globals = {}) {
  const exports = {};
  const code = ts.transpileModule(fs.readFileSync(new URL(relative, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(code, { exports, require: (name) => modules[name], AbortController, setTimeout, clearTimeout, console, process: { env: { NODE_ENV: "test" } }, ...globals });
  return exports;
}

const { parseSseFrames } = load("../src/lib/api/sse.ts");

test("SSE parser handles split frames, optional event fields, comments and multiline data", () => {
  const first = parseSseFrames(': heartbeat\r\nevent: job\r\ndata: {"id":"a",\r\n');
  assert.equal(first.payloads.length, 0);
  const second = parseSseFrames(first.remainder + 'data: "progress":0.5}\r\n\r\n');
  assert.equal(JSON.parse(second.payloads[0]).progress, 0.5);
  assert.equal(second.remainder, "");
  const done = parseSseFrames('data: [DONE]\n\ndata: {"ignored":true}\n\n');
  assert.equal(done.done, true);
  assert.equal(done.payloads.length, 0);
});

test("one channel shares a stream, reconnects after closure, and aborts on last unsubscribe", async () => {
  const { SourceEventChannel } = load("../src/features/source-ingestion/hooks/use-workspace-source-events.ts", {
    react: {}, "@/lib/api/context": {},
  });
  let calls = 0;
  let aborted = false;
  const receivedA = [];
  const receivedB = [];
  const api = { async *sourceEvents(workspaceId, ids, signal) {
    assert.equal(workspaceId, "workspace-1");
    assert.deepEqual([...ids], ["source-1"]);
    calls++;
    yield { id: "job-1", sourceId: "source-1", status: "processing", progress: calls / 10 };
    if (calls > 1) await new Promise((resolve) => signal.addEventListener("abort", () => { aborted = true; resolve(); }, { once: true }));
  } };
  const channel = new SourceEventChannel(api, "workspace-1");
  const unsubscribeA = channel.subscribe({ ids: new Set(["source-1"]), onJob: (job) => receivedA.push(job.progress) });
  const unsubscribeB = channel.subscribe({ ids: new Set(["source-1"]), onJob: (job) => receivedB.push(job.progress) });
  await new Promise((resolve) => setTimeout(resolve, 650));
  assert.equal(calls, 2);
  assert.deepEqual(receivedA, [0.1, 0.2]);
  assert.deepEqual(receivedB, [0.1, 0.2]);
  unsubscribeA();
  assert.equal(aborted, false);
  unsubscribeB();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(aborted, true);
  assert.equal(channel.empty, true);
});

test("channel batches more than 100 source IDs and aborts every batch", async () => {
  const { SourceEventChannel } = load("../src/features/source-ingestion/hooks/use-workspace-source-events.ts", { react: {}, "@/lib/api/context": {} });
  const calls = [];
  const api = { async *sourceEvents(_workspaceId, ids, signal) {
    calls.push({ ids, signal });
    await new Promise((resolve) => signal.addEventListener("abort", resolve, { once: true }));
  } };
  const channel = new SourceEventChannel(api, "workspace-1");
  const ids = Array.from({ length: 205 }, (_, index) => `source-${String(index).padStart(3, "0")}`);
  const unsubscribe = channel.subscribe({ ids: new Set(ids), onJob() {} });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(calls.map((call) => call.ids.length), [100, 100, 5]);
  assert.equal(new Set(calls.flatMap((call) => call.ids)).size, 205);
  unsubscribe();
  assert.ok(calls.every((call) => call.signal.aborted));
});

for (const status of [404, 422]) test(`HTTP ${status} isolates an invalid source and leaves the valid source live`, async () => {
  const { SourceEventChannel } = load("../src/features/source-ingestion/hooks/use-workspace-source-events.ts", { react: {}, "@/lib/api/context": {} });
  const calls = [];
  const invalid = [];
  const received = [];
  const api = { async *sourceEvents(_workspaceId, ids, signal) {
    calls.push([...ids]);
    if (ids.includes("bad")) throw { status };
    yield { id: "good", sourceId: "good", status: "processing", progress: 0.4 };
    await new Promise((resolve) => signal.addEventListener("abort", resolve, { once: true }));
  } };
  const channel = new SourceEventChannel(api, "workspace-1");
  const unsubscribe = channel.subscribe({ ids: new Set(["bad", "good"]), onJob: (job) => received.push(job.sourceId), onInvalid: (id, code) => invalid.push([id, code]) });
  await new Promise((resolve) => setTimeout(resolve, 50));
  assert.deepEqual(invalid, [["bad", status]]);
  assert.ok(received.includes("good"));
  assert.equal(calls.filter((ids) => ids.includes("bad")).length, 2);
  const lateInvalid = [];
  const unsubscribeLate = channel.subscribe({ ids: new Set(["bad"]), onJob() {}, onInvalid: (id, code) => lateInvalid.push([id, code]) });
  assert.deepEqual(lateInvalid, [["bad", status]]);
  unsubscribeLate();
  unsubscribe();
});

for (const status of [401, 403]) test(`HTTP ${status} stops a workspace subscription without retrying`, async () => {
  const { SourceEventChannel } = load("../src/features/source-ingestion/hooks/use-workspace-source-events.ts", { react: {}, "@/lib/api/context": {} });
  let calls = 0;
  const invalid = [];
  const channel = new SourceEventChannel({ async *sourceEvents() { calls++; throw { status }; } }, "workspace-1");
  const unsubscribe = channel.subscribe({ ids: new Set(["a", "b"]), onJob() {}, onInvalid: (id) => invalid.push(id) });
  await new Promise((resolve) => setTimeout(resolve, 650));
  assert.equal(calls, 1);
  assert.deepEqual(invalid, ["a", "b"]);
  unsubscribe();
});

test("HTTP 503 reconnects and keeps source event delivery", async () => {
  const { SourceEventChannel } = load("../src/features/source-ingestion/hooks/use-workspace-source-events.ts", { react: {}, "@/lib/api/context": {} });
  let calls = 0;
  const received = [];
  const channel = new SourceEventChannel({ async *sourceEvents(_workspaceId, _ids, signal) {
    calls++;
    if (calls === 1) throw { status: 503 };
    yield { id: "a", sourceId: "a", status: "processing", progress: 0.5 };
    await new Promise((resolve) => signal.addEventListener("abort", resolve, { once: true }));
  } }, "workspace-1");
  const unsubscribe = channel.subscribe({ ids: new Set(["a"]), onJob: (job) => received.push(job.progress) });
  await new Promise((resolve) => setTimeout(resolve, 1100));
  assert.equal(calls, 2);
  assert.deepEqual(received, [0.5]);
  unsubscribe();
});

test("source rows and progress stay visible while a settled refresh is in flight", async () => {
  const slots = [];
  const effects = [];
  let cursor = 0;
  let callback;
  let invalidCallback;
  const requests = [];
  const react = {
    useState(initial) { const index = cursor++; if (!(index in slots)) slots[index] = initial; return [slots[index], (next) => { slots[index] = typeof next === "function" ? next(slots[index]) : next; }]; },
    useRef(initial) { const index = cursor++; if (!(index in slots)) slots[index] = { current: initial }; return slots[index]; },
    useCallback(fn, deps) { const index = cursor++; const previous = slots[index]; if (!previous || deps.some((dep, i) => dep !== previous.deps[i])) slots[index] = { fn, deps }; return slots[index].fn; },
    useEffect(fn, deps) { const index = cursor++; const previous = slots[index]; if (!previous || deps.some((dep, i) => dep !== previous.deps[i])) { previous?.cleanup?.(); effects.push(() => { slots[index] = { deps, cleanup: fn() }; }); } },
  };
  const api = { listSources(_workspace, _signal) { return new Promise((resolve, reject) => requests.push({ resolve, reject })); } };
  const { useLiveSources } = load("../src/features/source-ingestion/hooks/use-live-sources.ts", {
    react,
    "@/lib/api/context": { useApi: () => api, useDemoMode: () => false },
    "./use-workspace-source-events": { useWorkspaceSourceEvents: (_workspace, _ids, onJob, _enabled, onInvalid) => { callback = onJob; invalidCallback = onInvalid; } },
  }, { window: { addEventListener() {}, removeEventListener() {} } });
  function render(workspace = "workspace-1") { cursor = 0; const value = useLiveSources(workspace); while (effects.length) effects.shift()(); return value; } // eslint-disable-line react-hooks/rules-of-hooks
  render();
  const original = [{ id: "source-1", status: "processing", title: "Meeting" }];
  requests.shift().resolve(original);
  await Promise.resolve();
  assert.equal(render().sources[0].title, "Meeting");
  callback({ id: "source-1", sourceId: "source-1", status: "succeeded", progress: 1 });
  const settled = render();
  assert.equal(settled.sources[0].status, "succeeded");
  assert.equal(settled.progress["source-1"], 1);
  assert.equal(settled.isLoading, false);
  assert.equal(requests.length, 1);
  requests.shift().reject(new Error("offline"));
  await new Promise(setImmediate);
  assert.match(render().error.message, /offline/);
  const switched = render("workspace-2");
  assert.equal(switched.sources, undefined);
  assert.equal(switched.error, undefined);
  assert.equal(switched.progress["source-1"], undefined);
  assert.equal(switched.isLoading, true);
  callback({ id: "source-1", sourceId: "source-1", status: "succeeded", progress: 0.8 });
  render("workspace-2");
  assert.equal(requests.length, 2, "settled metadata from the previous workspace must not suppress reconciliation");
  invalidCallback("missing", 404);
  invalidCallback("missing", 404);
  render("workspace-2");
  assert.equal(requests.length, 3, "an invalid source triggers only one list reconciliation");
});

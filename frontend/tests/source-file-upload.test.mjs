import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

function load(path, modules, globals = {}) {
  const exports = {};
  const code = ts.transpileModule(fs.readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  vm.runInNewContext(code, { exports, require: (name) => modules[name], File, Blob, Map, Set, ...globals });
  return exports;
}

const validation = { ACCEPTED_DOCUMENT_EXTENSIONS: [".pdf", ".docx", ".txt", ".md"] };
const classifier = load("../src/features/source-ingestion/lib/classify-source-file.ts", { "./validate-file": validation });

function file(name, type = "", size = 5) {
  return new File([new Uint8Array(size)], name, { type, lastModified: 17 });
}

test("supported audio, empty MIME, and document classification match the backend contract", () => {
  for (const extension of classifier.ACCEPTED_AUDIO_EXTENSIONS) {
    const result = classifier.classifySourceFile(file(`sample${extension}`));
    assert.equal(result.kind, "audio");
    assert.match(result.file.type, /^audio\//);
    assert.equal(result.file.name, `sample${extension}`);
  }
  assert.equal(classifier.classifySourceFile(file("notes.pdf", "application/pdf")).kind, "document");
  for (const [name, mime] of [["recording.mp4", "video/mp4"], ["recording.webm", "video/webm"]]) {
    const result = classifier.classifySourceFile(file(name, mime));
    assert.equal(result.kind, "audio");
    assert.equal(result.file.type, mime);
  }
  assert.equal(classifier.classifySourceFile(file("movie.mov", "video/quicktime")).kind, "unsupported");
  assert.equal(classifier.classifySourceFile(file("wrong.mp4", "video/webm")).kind, "unsupported");
  assert.equal(classifier.classifySourceFile(file("empty.mp4", "video/mp4", 0)).kind, "unsupported");
  assert.equal(classifier.classifySourceFile(file("large.webm", "video/webm", classifier.MAX_AUDIO_BYTES + 1)).kind, "unsupported");
  assert.equal(classifier.classifySourceFile(file("wrong.mp3", "audio/wav")).kind, "unsupported");
  assert.equal(classifier.classifySourceFile(file("empty.wav", "audio/wav", 0)).kind, "unsupported");
  assert.equal(classifier.classifySourceFile(file("recording.webm", "audio/mp4")).kind, "audio");
});

function componentHarness(onDocuments, onAudio) {
  let cursor = 0;
  let first = true;
  const slots = [];
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = initial;
      return [slots[index], (value) => { slots[index] = typeof value === "function" ? value(slots[index]) : value; }];
    },
    useRef(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = { current: initial };
      return slots[index];
    },
    useCallback(fn) { return fn; },
    useEffect(fn) { if (first) fn(); },
  };
  const element = (type, props) => ({ type, props });
  const errors = [];
  const exports = load("../src/features/source-ingestion/components/source-file-upload.tsx", {
    react,
    "react/jsx-runtime": { jsx: element, jsxs: element },
    "next/link": { default: "Link" },
    sonner: { toast: { error: (message) => errors.push(message) } },
    "@/components/ui/button": { Button: "Button" },
    "@/lib/api/context": { useApi: () => ({ listProjects: async () => [{ id: "project-1", name: "Project" }] }), useWorkspacePath: () => () => "/directory" },
    "../lib/classify-source-file": classifier,
    "../lib/validate-file": validation,
    "./upload-dropzone": { UploadDropzone: "UploadDropzone" },
  });
  function render() {
    cursor = 0;
    const tree = exports.SourceFileUpload({ workspaceId: "workspace-1", onDocuments, onAudio });
    first = false;
    return tree;
  }
  return { render, errors };
}

function allNodes(node) {
  if (Array.isArray(node)) return node.flatMap(allNodes);
  if (!node || typeof node !== "object") return [];
  return [node, ...allNodes(node.props?.children)];
}

test("mixed selection sends audio once to recording upload with projects and documents once to document upload", async () => {
  const documents = [];
  const recordings = [];
  const harness = componentHarness(async (files) => documents.push(files), async (...args) => recordings.push(args));
  let tree = harness.render();
  // Project metadata loads asynchronously; selection is available after the next render.
  await Promise.resolve();
  tree = harness.render();
  allNodes(tree).find((node) => node.type === "input" && node.props.type === "checkbox").props.onChange({ target: { checked: true } });
  tree = harness.render();
  const choose = allNodes(tree).find((node) => node.type === "UploadDropzone").props.onFilesSelected;
  const audio = file("meeting.m4a");
  const document = file("notes.txt", "text/plain");
  choose([audio, document, file("clip.mov", "video/quicktime")]);
  choose([audio]);
  await Promise.resolve();
  assert.equal(recordings.length, 1);
  assert.equal(recordings[0][0].name, "meeting.m4a");
  assert.equal(recordings[0][3], "project-1");
  assert.deepEqual(Array.from(recordings[0][4]), ["project-1"]);
  assert.equal(documents.length, 1);
  assert.equal(documents[0][0], document);
  assert.match(harness.errors[0], /동영상/);
  choose([audio]);
  await Promise.resolve();
  assert.equal(recordings.length, 1);
});

test("failed audio stays selectable for a single retry", async () => {
  let calls = 0;
  const harness = componentHarness(async () => {}, async () => { calls++; if (calls === 1) throw new Error("offline"); });
  let tree = harness.render();
  const choose = allNodes(tree).find((node) => node.type === "UploadDropzone").props.onFilesSelected;
  choose([file("failed.wav", "audio/wav")]);
  await new Promise(setImmediate);
  tree = harness.render();
  const retry = allNodes(tree).find((node) => node.type === "Button" && node.props.children === "업로드 다시 시도");
  assert.ok(retry);
  retry.props.onClick();
  retry.props.onClick();
  await new Promise(setImmediate);
  assert.equal(calls, 2);
  tree = harness.render();
  assert.equal(allNodes(tree).some((node) => node.type === "Button" && node.props.children === "업로드 다시 시도"), false);
});

test("an awaiting-review recording opens the existing review dialog", () => {
  let cursor = 0;
  const slots = [];
  let settled;
  const react = {
    useState(initial) { const index = cursor++; if (!(index in slots)) slots[index] = initial; return [slots[index], (value) => { slots[index] = typeof value === "function" ? value(slots[index]) : value; }]; },
    useMemo(fn) { return fn(); },
    useCallback(fn) { return fn; },
  };
  const element = (type, props) => ({ type, props });
  const exports = load("../src/features/source-ingestion/components/source-upload-dialog.tsx", {
    react,
    "react/jsx-runtime": { jsx: element, jsxs: element },
    sonner: { toast: { info() {}, error() {}, success() {} } },
    "@/components/ui/button": { Button: "Button" },
    "@/components/ui/dialog": { Dialog: "Dialog", DialogContent: "DialogContent", DialogHeader: "DialogHeader", DialogTitle: "DialogTitle", DialogDescription: "DialogDescription" },
    "../hooks/use-source-upload": { useSourceUpload: () => ({ items: [], uploadDocuments() {}, uploadRecording() {}, uploadTranscript() {}, dismiss() {} }) },
    "../hooks/use-job-polling": { useJobPolling: (_ids, callback) => { settled = callback; return {}; } },
    "./meeting-capture": { MeetingCapture: "MeetingCapture" },
    "./meeting-review-dialog": { MeetingReviewDialog: "MeetingReviewDialog" },
    "./source-file-upload": { SourceFileUpload: "SourceFileUpload" },
    "./upload-queue": { UploadQueue: "UploadQueue" },
  }, { window: { dispatchEvent() {} }, Event });
  function render() { cursor = 0; return exports.SourceUploadDialog({ workspaceId: "workspace-1", mode: "document", onClose() {} }); }
  render();
  settled({ id: "job-1", sourceId: "source-1", sourceKind: "meeting", status: "awaiting_review" });
  const review = allNodes(render()).find((node) => node.type === "MeetingReviewDialog");
  assert.equal(review.props.sourceId, "source-1");
});

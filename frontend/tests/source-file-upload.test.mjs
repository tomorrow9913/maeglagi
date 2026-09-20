import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

// 공용 문구 모듈은 실제 구현을 그대로 씁니다.
import * as copy from "../src/features/source-ingestion/lib/copy.ts";

function load(path, modules, globals = {}) {
  const exports = {};
  const code = ts.transpileModule(fs.readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  vm.runInNewContext(code, { exports, require: (name) => modules[name], File, Blob, Map, Set, ...globals });
  return exports;
}

const validation = { ACCEPTED_DOCUMENT_EXTENSIONS: [".pdf", ".docx", ".txt", ".md"], MAX_DOCUMENT_BYTES: 20 * 1024 * 1024 };
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

function componentHarness(onDocuments, onAudio, projects = [{ id: "project-1", name: "Project" }]) {
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
    "@/lib/api/context": { useApi: () => ({ listProjects: async () => projects }), useWorkspacePath: () => () => "/directory" },
    "../lib/classify-source-file": classifier,
    "../lib/copy": copy,
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

// 실패한 녹음 파일의 사유와 "다시 시도"는 업로드 큐 항목 한 곳에만 보입니다(tests/recording.test.mjs).
// 이 컴포넌트는 같은 실패를 따로 알리지 않고, 같은 파일을 다시 고를 수 있게만 둡니다.
test("failed audio shows no duplicate inline alert and the same file can be chosen again", async () => {
  let calls = 0;
  const harness = componentHarness(async () => {}, async () => { calls++; if (calls === 1) throw new Error("offline"); });
  let tree = harness.render();
  const choose = allNodes(tree).find((node) => node.type === "UploadDropzone").props.onFilesSelected;
  const audio = file("failed.wav", "audio/wav");
  choose([audio]);
  choose([audio]);
  await new Promise(setImmediate);
  assert.equal(calls, 1, "a duplicate selection while the upload is pending is ignored");
  tree = harness.render();
  assert.equal(allNodes(tree).some((node) => node.props?.role === "alert"), false);
  choose([audio]);
  await new Promise(setImmediate);
  assert.equal(calls, 2, "a failed file is not remembered as submitted");
  choose([audio]);
  await new Promise(setImmediate);
  assert.equal(calls, 2, "an uploaded file is not sent twice");
});

test("dropzone hint states both size limits and an empty project list explains itself", async () => {
  const harness = componentHarness(async () => {}, async () => {}, []);
  harness.render();
  await Promise.resolve();
  const nodes = allNodes(harness.render());
  const hint = nodes.find((node) => node.type === "UploadDropzone").props.hint;
  assert.match(hint, /최대 20MB/);
  assert.match(hint, /최대 50MB/);
  assert.ok(nodes.some((node) => node.props?.children === copy.NO_PROJECTS_HINT));
});

test("meeting panel remains mounted when collapsed and review opens only on request", () => {
  let cursor = 0;
  const slots = [];
  let settled;
  let reviewAction;
  let mode = "meeting";
  const react = {
    useState(initial) { const index = cursor++; if (!(index in slots)) slots[index] = initial; return [slots[index], (value) => { slots[index] = typeof value === "function" ? value(slots[index]) : value; }]; },
    useEffect(fn) { fn(); },
    useCallback(fn) { return fn; },
  };
  const element = (type, props) => ({ type, props });
  let uploadItems = [];
  const exports = load("../src/features/source-ingestion/components/source-upload-dialog.tsx", {
    react,
    "react/jsx-runtime": { jsx: element, jsxs: element },
    sonner: { toast: { info(_message, options) { reviewAction = options?.action; }, error() {}, success() {} } },
    "lucide-react": { Mic: "Mic", Minus: "Minus" },
    "../lib/copy": copy,
    "@/components/ui/button": { Button: "Button" },
    "@/components/ui/dialog": { Dialog: "Dialog", DialogContent: "DialogContent", DialogHeader: "DialogHeader", DialogTitle: "DialogTitle", DialogDescription: "DialogDescription" },
    "../hooks/use-source-upload": { useSourceUpload: () => ({ items: uploadItems, uploadDocuments() {}, uploadRecording() {}, uploadTranscript() {}, dismiss() {} }) },
    "../hooks/use-job-events": { useJobEvents: (_workspaceId, _jobs, callback) => { settled = callback; return { jobs: {}, connection: "connected" }; } },
    "./meeting-capture": { MeetingCapture: "MeetingCapture" },
    "./meeting-review-dialog": { MeetingReviewDialog: "MeetingReviewDialog" },
    "./source-file-upload": { SourceFileUpload: "SourceFileUpload" },
    "./upload-queue": { UploadQueue: "UploadQueue" },
  }, { window: { dispatchEvent() {} }, Event });
  function render() { cursor = 0; return exports.SourceUploadDialog({ workspaceId: "workspace-1", mode, onClose() { mode = null; } }); }
  let tree = render();
  assert.ok(allNodes(tree).some((node) => node.type === "MeetingCapture"));
  allNodes(tree).find((node) => node.type === "Button" && node.props["aria-label"] === "회의 패널 접기").props.onClick();
  tree = render();
  assert.ok(allNodes(tree).some((node) => node.type === "MeetingCapture"));
  assert.ok(allNodes(tree).some((node) => node.type === "Button" && node.props["aria-label"] === "회의 패널 다시 열기"));
  assert.match(allNodes(tree).find((node) => node.type === "aside").props.className, /bottom-\[calc\(7rem\+env\(safe-area-inset-bottom\)\)\]/);
  settled({ id: "job-1", sourceId: "source-1", sourceKind: "meeting", status: "awaiting_review" });
  assert.equal(allNodes(render()).find((node) => node.type === "MeetingReviewDialog").props.sourceId, undefined);
  reviewAction.onClick();
  const review = allNodes(render()).find((node) => node.type === "MeetingReviewDialog");
  assert.equal(review.props.sourceId, "source-1");

  // 전송 중에도 창을 닫을 수 있고, 업로드가 계속된다는 안내가 보입니다.
  mode = "document";
  uploadItems = [{ id: "upload-1", fileName: "notes.pdf", status: "uploading", progress: 0.3 }];
  tree = render();
  const dialog = allNodes(tree).find((node) => node.type === "Dialog");
  const content = allNodes(tree).find((node) => node.type === "DialogContent");
  assert.equal(content.props.showCloseButton, undefined);
  assert.equal(content.props.onEscapeKeyDown, undefined);
  assert.equal(content.props.onInteractOutside, undefined);
  assert.ok(allNodes(tree).some((node) => node.props?.children === copy.UPLOAD_CONTINUES_IN_BACKGROUND));
  assert.ok(allNodes(tree).some((node) => node.type === "Button" && node.props.children === "Ask로 돌아가기"));
  dialog.props.onOpenChange(false);
  assert.equal(mode, null);
});

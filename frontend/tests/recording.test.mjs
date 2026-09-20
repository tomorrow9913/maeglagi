import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

import * as errorMessage from "../src/lib/api/error-message.ts";
import * as copy from "../src/features/source-ingestion/lib/copy.ts";

// Minimal hook runner deliberately replays updater functions as React Strict Mode does.
function loadHook(path, globals = {}, modules = {}) {
  let cursor = 0;
  let first = true;
  const slots = [];
  const cleanups = [];
  const react = {
    useState(initial) {
      const index = cursor++;
      if (first) slots[index] = initial;
      return [
        slots[index],
        (value) => {
          if (typeof value === "function") {
            value(slots[index]);
            slots[index] = value(slots[index]);
          } else slots[index] = value;
        },
      ];
    },
    useRef(initial) {
      const index = cursor++;
      if (first) slots[index] = { current: initial };
      return slots[index];
    },
    useCallback(fn) {
      return fn;
    },
    useEffect(fn) {
      if (first) cleanups.push(fn());
    },
  };
  const exports = {};
  const code = ts.transpileModule(fs.readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(code, {
    exports,
    // 사용자용 오류 문구와 공용 문구 모듈은 실제 구현을 그대로 씁니다.
    require: (name) =>
      name === "react" ? react
        : name === "@/lib/api/error-message" ? errorMessage
        : name === "../lib/copy" ? copy
        : modules[name],
    AbortController,
    Blob,
    Date,
    DOMException,
    setInterval: () => 1,
    clearInterval() {},
    setTimeout: () => 1,
    clearTimeout() {},
    ...globals,
  });
  return {
    render(name, argument) {
      cursor = 0;
      const value = exports[name](argument);
      first = false;
      return value;
    },
    unmount() {
      cleanups.forEach((fn) => fn?.());
    },
  };
}

function audioEnvironment(getMedia) {
  const recorders = [];
  let released = 0;
  const stream = { getTracks: () => [{ stop: () => released++ }] };
  class Recorder {
    static isTypeSupported() {
      return true;
    }
    constructor() {
      this.state = "inactive";
      this.mimeType = "audio/webm";
      this.events = {};
      recorders.push(this);
    }
    addEventListener(name, callback) {
      this.events[name] = callback;
    }
    start() {
      this.state = "recording";
    }
    stop() {
      this.state = "inactive";
      this.events.dataavailable({ data: new Blob(["audio"]) });
      this.events.stop();
    }
  }
  return {
    globals: {
      window: {},
      navigator: { mediaDevices: { getUserMedia: getMedia ?? (async () => stream) } },
      MediaRecorder: Recorder,
    },
    recorders,
    stream,
    released: () => released,
  };
}

test("audio completion uploads once despite Strict Mode updater replay and repeated stop", async () => {
  const env = audioEnvironment();
  const hook = loadHook(
    "../src/features/source-ingestion/hooks/use-audio-recorder.ts",
    env.globals,
  );
  const completed = [];
  const audio = hook.render("useAudioRecorder", { onComplete: (...args) => completed.push(args) });
  await Promise.all([audio.start(), audio.start()]);
  assert.equal(env.recorders.length, 1);
  audio.stop();
  audio.stop();
  env.recorders[0].events.stop();
  assert.equal(completed.length, 1);
  assert.equal(completed[0][0].size, 5);
  assert.equal(env.released(), 1);
});

test("unmount during permission request releases later stream without upload", async () => {
  let resolve;
  const env = audioEnvironment(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  const hook = loadHook(
    "../src/features/source-ingestion/hooks/use-audio-recorder.ts",
    env.globals,
  );
  let count = 0;
  const audio = hook.render("useAudioRecorder", { onComplete: () => count++ });
  const pending = audio.start();
  hook.unmount();
  resolve(env.stream);
  await pending;
  assert.equal(count, 0);
  assert.equal(env.recorders.length, 0);
  assert.equal(env.released(), 1);
});

test("unmount while recording discards audio instead of uploading", async () => {
  const env = audioEnvironment();
  const hook = loadHook(
    "../src/features/source-ingestion/hooks/use-audio-recorder.ts",
    env.globals,
  );
  let count = 0;
  const audio = hook.render("useAudioRecorder", { onComplete: () => count++ });
  await audio.start();
  hook.unmount();
  assert.equal(count, 0);
  assert.equal(env.released(), 1);
});

test("recorder error ends capture, releases microphone, and never uploads a partial blob", async () => {
  const env = audioEnvironment();
  const hook = loadHook(
    "../src/features/source-ingestion/hooks/use-audio-recorder.ts",
    env.globals,
  );
  let completed = 0;
  const recorder = hook.render("useAudioRecorder", { onComplete: () => completed++ });
  await recorder.start();
  env.recorders[0].events.error();
  assert.equal(env.released(), 1);
  assert.equal(completed, 0);
  assert.equal(hook.render("useAudioRecorder", { onComplete: () => completed++ }).status, "error");
});

function speechEnvironment() {
  const instances = [];
  class Recognition {
    constructor() {
      instances.push(this);
    }
    start() {}
    stop() {}
    abort() {
      this.onend?.();
    }
  }
  return { instances, globals: { window: { SpeechRecognition: Recognition } } };
}
const result = (text, isFinal) => ({ 0: { transcript: text }, isFinal });

test("speech replaces interim results, waits for final stop event, and completes once", () => {
  const env = speechEnvironment();
  const hook = loadHook(
    "../src/features/source-ingestion/hooks/use-browser-transcript.ts",
    env.globals,
  );
  const completed = [];
  const callback = (...args) => completed.push(args);
  let speech = hook.render("useBrowserTranscript", callback);
  speech.start();
  const recognition = env.instances[0];
  recognition.onresult({ results: [result("첫 문장", true), result("초안", false)] });
  recognition.onresult({ results: [result("첫 문장", true), result("고친 문장", false)] });
  speech = hook.render("useBrowserTranscript", callback);
  assert.equal(speech.lines.length, 1);
  assert.equal(speech.interim, "고친 문장");
  speech.stop();
  assert.equal(completed.length, 0);
  recognition.onresult({ results: [result("첫 문장", true), result("최종 문장", true)] });
  recognition.onend();
  recognition.onend();
  assert.equal(completed.length, 1);
  assert.deepEqual(Array.from(completed[0][0]), ["첫 문장", "최종 문장"]);
});

test("speech preserves tentative tail for review when service ends and aborts silently on unmount", () => {
  const env = speechEnvironment();
  const hook = loadHook(
    "../src/features/source-ingestion/hooks/use-browser-transcript.ts",
    env.globals,
  );
  const completed = [];
  const callback = (lines) => completed.push(lines);
  const speech = hook.render("useBrowserTranscript", callback);
  speech.start();
  const recognition = env.instances[0];
  recognition.onresult({ results: [result("확인 필요", false)] });
  recognition.onend();
  assert.deepEqual(Array.from(completed[0]), ["확인 필요"]);
  speech.start();
  hook.unmount();
  assert.equal(completed.length, 1);
});

test("speech stop timeout finalizes the draft if the browser never emits end", () => {
  const env = speechEnvironment();
  const timers = [];
  const hook = loadHook(
    "../src/features/source-ingestion/hooks/use-browser-transcript.ts",
    {
      ...env.globals,
      setTimeout(callback) { timers.push(callback); return timers.length; },
    },
  );
  const completed = [];
  let speech = hook.render("useBrowserTranscript", (lines) => completed.push(lines));
  speech.start();
  env.instances[0].onresult({ results: [result("남은 발언", false)] });
  speech = hook.render("useBrowserTranscript", (lines) => completed.push(lines));
  speech.stop();
  assert.equal(completed.length, 0);
  timers[0]();
  assert.equal(completed.length, 1);
  assert.deepEqual(Array.from(completed[0]), ["남은 발언"]);
});

test("transcript upload sends edited text once and preserves the payload on failure", async () => {
  let shouldFail = true;
  const sent = [];
  const input = { title: "편집 회의", text: "김민수: 수정한 문장", durationSeconds: 20 };
  const hook = loadHook(
    "../src/features/source-ingestion/hooks/use-source-upload.ts",
    {
      window: { dispatchEvent() {} },
      Event,
      Error,
    },
    {
      sonner: { toast: { error() {}, success() {} } },
      "@/lib/api/context": {
        useApi: () => ({
          async uploadTranscript(workspace, body) {
            sent.push({ workspace, body });
            if (shouldFail) throw new Error("서버에 연결하지 못했습니다.");
            return { id: "job-1", transcriptSource: "browser" };
          },
        }),
      },
      "../lib/validate-file": {},
    },
  );
  let upload = hook.render("useSourceUpload", "workspace-1");
  assert.equal(await upload.uploadTranscript(input), false);
  upload = hook.render("useSourceUpload", "workspace-1");
  assert.equal(upload.items.length, 1);
  assert.equal(upload.items[0].status, "failed");
  // API 계층이 만든 사용자용 문구는 그대로 큐 항목에 남습니다.
  assert.equal(upload.items[0].errorMessage, "서버에 연결하지 못했습니다.");
  assert.equal(input.text, "김민수: 수정한 문장");
  shouldFail = false;
  assert.equal(await upload.uploadTranscript(input, "project-7"), true);
  assert.equal(sent.length, 2);
  assert.deepEqual(JSON.parse(JSON.stringify(sent[1])), { workspace: "workspace-1", body: { ...input, projectId: "project-7", projectIds: ["project-7"] } });
  upload = hook.render("useSourceUpload", "workspace-1");
  assert.equal(upload.items[0].status, "uploaded");
  assert.equal(upload.items[0].job.id, "job-1");
});

test("recording upload carries the chosen project and live draft", async () => {
  const sent = [];
  const hook = loadHook(
    "../src/features/source-ingestion/hooks/use-source-upload.ts",
    { window: { dispatchEvent() {} }, Event },
    {
      sonner: { toast: { error() {}, success() {} } },
      "@/lib/api/context": { useApi: () => ({
        async uploadRecording(...args) { sent.push(args); return { id: "source-1", sourceId: "source-1" }; },
      }) },
      "../lib/validate-file": {},
    },
  );
  const upload = hook.render("useSourceUpload", "workspace-1");
  const audio = new Blob(["audio"]);
  const liveDraft = { utterances: [{ id: "u-1", personId: null, speakerName: "화자 1", text: "확인" }] };
  await upload.uploadRecording(audio, 4, liveDraft, "project-7");
  assert.equal(sent.length, 1);
  assert.equal(sent[0][0], "workspace-1");
  assert.equal(sent[0][1], audio);
  assert.deepEqual(sent[0][2], liveDraft);
  assert.equal(sent[0][3], "project-7");
});

function uploadHarness(api, toasts = { error: [], success: [] }) {
  const hook = loadHook(
    "../src/features/source-ingestion/hooks/use-source-upload.ts",
    { window: { dispatchEvent() {} }, Event, Error, File },
    {
      sonner: { toast: { error: (message) => toasts.error.push(message), success: (message) => toasts.success.push(message) } },
      "@/lib/api/context": { useApi: () => api },
      "../lib/validate-file": { validateDocuments: (files) => ({ accepted: files, rejected: [] }) },
    },
  );
  return { render: () => hook.render("useSourceUpload", "workspace-1"), toasts };
}

/** Rejects like apiUpload does when its signal aborts. */
function abortable(signal) {
  return new Promise((_resolve, reject) => {
    signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
  });
}

test("an uploading document can be cancelled without an error toast and retried on the same item", async () => {
  const signals = [];
  let mode = "hang";
  const harness = uploadHarness({
    uploadDocument(_workspace, _file, options) {
      signals.push(options.signal);
      options.onProgress(0.4);
      return mode === "hang" ? abortable(options.signal) : Promise.resolve({ id: "job-1", sourceId: "source-1" });
    },
  });
  let upload = harness.render();
  const file = new File(["text"], "notes.txt");
  const pending = upload.uploadDocuments([file]);
  upload = harness.render();
  assert.equal(upload.items.length, 1);
  assert.equal(upload.items[0].status, "uploading");
  assert.equal(upload.items[0].progress, 0.4);
  assert.equal(upload.items[0].file, file);

  upload.cancel(upload.items[0].id);
  await pending;
  assert.equal(signals[0].aborted, true);
  upload = harness.render();
  assert.equal(upload.items[0].status, "cancelled");
  assert.equal(upload.items[0].canRetry, true);
  assert.deepEqual(harness.toasts.error, [], "cancelling is not a failure");

  mode = "succeed";
  upload.retry(upload.items[0].id);
  await new Promise(setImmediate);
  upload = harness.render();
  assert.equal(upload.items.length, 1, "retry updates the same queue item");
  assert.equal(upload.items[0].status, "uploaded");
  assert.equal(upload.items[0].job.id, "job-1");
  assert.equal(signals.length, 2);
});

test("a stalled upload that times out becomes one failed item with one toast, and retry ignores double clicks", async () => {
  let calls = 0;
  const harness = uploadHarness({
    async uploadDocument() {
      calls++;
      if (calls === 1) throw Object.assign(new Error("서버 응답이 늦어지고 있습니다. 잠시 후 다시 시도해 주세요."), { kind: "timeout" });
      await new Promise(setImmediate);
      return { id: "job-2", sourceId: "source-2" };
    },
  });
  let upload = harness.render();
  await upload.uploadDocuments([new File(["text"], "slow.pdf")]);
  upload = harness.render();
  assert.equal(upload.items[0].status, "failed");
  assert.match(upload.items[0].errorMessage, /늦어지고/);
  assert.equal(upload.items[0].canRetry, true);
  assert.equal(harness.toasts.error.length, 1);
  assert.match(harness.toasts.error[0], /slow\.pdf/);

  upload.retry(upload.items[0].id);
  upload.retry(upload.items[0].id);
  await new Promise(setImmediate);
  await new Promise(setImmediate);
  assert.equal(calls, 2, "a second click while the retry is in flight is ignored");
  upload = harness.render();
  assert.equal(upload.items.length, 1);
  assert.equal(upload.items[0].status, "uploaded");
});

test("recording retries reuse their queue item; only file recordings are retryable from the queue", async () => {
  let shouldFail = true;
  const drafts = [];
  const harness = uploadHarness({
    async uploadRecording(_workspace, _audio, liveDraft) {
      drafts.push(liveDraft);
      if (shouldFail) throw new Error("서버에 연결하지 못했습니다.");
      return { id: "job-3", sourceId: "source-3" };
    },
  });
  let upload = harness.render();
  const live = new Blob(["live"]);
  const draft = { utterances: [] };
  await assert.rejects(upload.uploadRecording(live, 3, draft));
  upload = harness.render();
  assert.equal(upload.items.length, 1);
  assert.equal(upload.items[0].status, "failed");
  assert.equal(upload.items[0].canRetry, false, "the capture screen re-uploads live recordings with the edited draft");
  shouldFail = false;
  const edited = { utterances: [{ id: "u-1", personId: null, speakerName: "화자 1", text: "수정" }] };
  await upload.uploadRecording(live, 3, edited);
  upload = harness.render();
  assert.equal(upload.items.length, 1, "retrying the same recording does not add a second row");
  assert.equal(upload.items[0].status, "uploaded");
  assert.equal(drafts[1], edited);

  shouldFail = true;
  const file = new File(["file"], "meeting.m4a");
  await assert.rejects(upload.uploadRecording(file, 0));
  upload = harness.render();
  assert.equal(upload.items.length, 2);
  assert.equal(upload.items[0].fileName, "meeting.m4a");
  assert.equal(upload.items[0].canRetry, true);
  shouldFail = false;
  upload.retry(upload.items[0].id);
  await new Promise(setImmediate);
  upload = harness.render();
  assert.equal(upload.items.length, 2);
  assert.equal(upload.items[0].status, "uploaded");
});

test("speech error codes are mapped to Korean reasons and never shown raw", () => {
  const env = speechEnvironment();
  const hook = loadHook("../src/features/source-ingestion/hooks/use-browser-transcript.ts", env.globals);
  let speech = hook.render("useBrowserTranscript", () => {});
  assert.equal(speech.supported, true);
  speech.start();
  for (const code of ["network", "not-allowed", "service-not-allowed", "audio-capture", "no-speech", "aborted", "bad-grammar"]) {
    env.instances[0].onerror({ error: code });
    speech = hook.render("useBrowserTranscript", () => {});
    assert.match(speech.error, /[가-힣]/);
    assert.equal(speech.error.includes(code), false, code);
    assert.doesNotMatch(speech.error, /[A-Za-z]/, code);
  }
});

test("unsupported browsers report speech as unsupported so the screen can disable dictation", () => {
  const hook = loadHook("../src/features/source-ingestion/hooks/use-browser-transcript.ts", { window: {} });
  hook.render("useBrowserTranscript", () => {});
  const speech = hook.render("useBrowserTranscript", () => {});
  assert.equal(speech.supported, false);
  assert.equal(speech.start(), false);
  assert.match(hook.render("useBrowserTranscript", () => {}).error, /지원하지 않습니다/);
});

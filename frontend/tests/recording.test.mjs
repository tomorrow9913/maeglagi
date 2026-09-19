import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

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
    require: (name) => (name === "react" ? react : modules[name]),
    Blob,
    Date,
    DOMException,
    setInterval: () => 1,
    clearInterval() {},
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

test("transcript upload sends edited text once and preserves the payload on failure", async () => {
  let shouldFail = true;
  const sent = [];
  const input = { title: "편집 회의", text: "김민수: 수정한 문장", durationSeconds: 20 };
  const hook = loadHook(
    "../src/features/source-ingestion/hooks/use-source-upload.ts",
    {
      window: { dispatchEvent() {} },
      Event,
    },
    {
      sonner: { toast: { error() {}, success() {} } },
      "@/lib/api": {
        api: {
          async uploadTranscript(workspace, body) {
            sent.push({ workspace, body });
            if (shouldFail) throw new Error("offline");
            return { id: "job-1", transcriptSource: "browser" };
          },
        },
      },
      "../lib/validate-file": {},
    },
  );
  let upload = hook.render("useSourceUpload", "workspace-1");
  assert.equal(await upload.uploadTranscript(input), false);
  upload = hook.render("useSourceUpload", "workspace-1");
  assert.equal(upload.items.length, 1);
  assert.equal(upload.items[0].status, "failed");
  assert.equal(input.text, "김민수: 수정한 문장");
  shouldFail = false;
  assert.equal(await upload.uploadTranscript(input), true);
  assert.equal(sent.length, 2);
  assert.deepEqual(sent[1], { workspace: "workspace-1", body: input });
});

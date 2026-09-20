import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const exports = {};
const code = ts.transpileModule(fs.readFileSync(new URL("../src/features/source-ingestion/lib/saved-recording-transcriber.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
vm.runInNewContext(code, { exports, setTimeout, clearTimeout });
const { SavedRecordingTranscriber, supportsSavedRecordingTranscript } = exports;

function fixture() {
  const track = { kind: "audio", readyState: "live", stopped: false, stop() { this.stopped = true; } };
  const stream = { getAudioTracks: () => [track], getTracks: () => [track] };
  const listeners = new Map();
  const audio = {
    src: "", crossOrigin: "", preload: "", currentTime: 0, duration: 12, readyState: 3,
    played: false, paused: false, ontimeupdate: null, onended: null,
    captureStream() { return stream; },
    async play() { this.played = true; },
    pause() { this.paused = true; },
    removeAttribute(name) { if (name === "src") this.src = ""; },
    addEventListener(name, listener) { listeners.set(name, listener); },
    removeEventListener(name) { listeners.delete(name); },
    load() {},
  };
  class Recognition {
    constructor() { Recognition.instance = this; }
    onresult = null; onerror = null; onend = null;
    start(...args) { this.startArgs = args; }
    stop() { this.stopped = true; }
    abort() { this.aborted = true; }
  }
  const updates = [];
  const transcriber = new SavedRecordingTranscriber(audio, Recognition, (update) => updates.push(update));
  return { audio, track, Recognition, updates, transcriber };
}

test("saved recording recognition requires an audio track and completes only after playback and recognition end", async () => {
  const { audio, track, Recognition, updates, transcriber } = fixture();
  await transcriber.start("https://example.test/signed-recording");
  assert.equal(audio.crossOrigin, "anonymous");
  assert.equal(audio.src, "https://example.test/signed-recording");
  assert.equal(audio.played, true);
  assert.deepEqual(Recognition.instance.startArgs, [track], "must never fall back to microphone start()");
  Recognition.instance.onresult({ results: [{ isFinal: true, 0: { transcript: "회의 결과" } }] });
  assert.equal(updates.at(-1).phase, "transcribing");
  audio.currentTime = audio.duration;
  audio.onended();
  assert.equal(Recognition.instance.stopped, true);
  assert.equal(updates.at(-1).phase, "transcribing", "playback end alone is not completion");
  Recognition.instance.onend();
  assert.equal(updates.at(-1).phase, "complete");
  assert.equal(updates.at(-1).utterances[0].text, "회의 결과");
  assert.equal(audio.paused, true);
  assert.equal(track.stopped, true);
});

test("early recognition end stays partial and cancel prevents late results", async () => {
  const { audio, Recognition, updates, transcriber } = fixture();
  await transcriber.start("https://example.test/signed-recording");
  Recognition.instance.onresult({ results: [{ isFinal: true, 0: { transcript: "앞부분" } }] });
  Recognition.instance.onend();
  assert.equal(updates.at(-1).phase, "partial");
  assert.equal(updates.at(-1).utterances[0].text, "앞부분");
  assert.equal(audio.paused, true);
  const previous = updates.length;
  transcriber.cancel();
  assert.equal(Recognition.instance.onresult, null);
  assert.equal(updates.length, previous);
});

test("cancel during media loading releases listeners before recognition can start", async () => {
  const { audio, Recognition, updates, transcriber } = fixture();
  const listeners = new Map();
  audio.readyState = 0;
  audio.addEventListener = (name, listener) => listeners.set(name, listener);
  audio.removeEventListener = (name) => listeners.delete(name);
  const opening = transcriber.start("https://example.test/signed-recording");
  assert.equal(listeners.has("canplay"), true);
  transcriber.cancel();
  await opening;
  assert.equal(listeners.size, 0);
  assert.equal(Recognition.instance, undefined);
  assert.equal(updates.at(-1).phase, "loading");
  assert.equal(audio.paused, true);
});

test("immediate media error and later playback error both stop without microphone fallback", async () => {
  const immediate = fixture();
  const listeners = new Map();
  immediate.audio.readyState = 0;
  immediate.audio.addEventListener = (name, listener) => listeners.set(name, listener);
  immediate.audio.removeEventListener = (name) => listeners.delete(name);
  immediate.audio.load = () => listeners.get("error")?.();
  await immediate.transcriber.start("https://example.test/broken");
  assert.equal(immediate.updates.at(-1).phase, "partial");
  assert.equal(listeners.size, 0);
  assert.equal(immediate.Recognition.instance, undefined);

  const later = fixture();
  await later.transcriber.start("https://example.test/signed-recording");
  later.audio.onerror();
  assert.equal(later.updates.at(-1).phase, "partial");
  assert.equal(later.track.stopped, true);
  assert.equal(later.audio.onerror, null);
});

test("audio-track recovery is gated to supported desktop Chromium", () => {
  assert.equal(supportsSavedRecordingTranscript("Mozilla/5.0 Chrome/135.0.0.0", true, true), true);
  assert.equal(supportsSavedRecordingTranscript("Mozilla/5.0 Chrome/135.0.0.0 Edg/135.0.0.0", true, true), true);
  assert.equal(supportsSavedRecordingTranscript("Mozilla/5.0 Chrome/134.0.0.0", true, true), false);
  assert.equal(supportsSavedRecordingTranscript("Mozilla/5.0 Chrome/135.0.0.0 Edg/134.0.0.0", true, true), false);
  assert.equal(supportsSavedRecordingTranscript("Mozilla/5.0 Android Chrome/135.0.0.0", true, true), false);
  assert.equal(supportsSavedRecordingTranscript("Mozilla/5.0 Version/18 Safari/605", true, true), false);
  assert.equal(supportsSavedRecordingTranscript("Mozilla/5.0 Chrome/135.0.0.0", false, true), false);
  assert.equal(supportsSavedRecordingTranscript("Mozilla/5.0 Chrome/135.0.0.0", true, false), false);
});

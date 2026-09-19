import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

function loadTs(path) {
  const exports = {};
  const source = fs.readFileSync(new URL(path, import.meta.url), "utf8");
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(code, { exports, Set });
  return exports;
}

const { addRoster, meetingUtterances, nextLocalSpeakerName, projectRoster, removeSpeaker } = loadTs("../src/features/source-ingestion/lib/meeting-roster.ts");
const { mergeTranscript } = loadTs("../src/features/source-ingestion/lib/transcript-draft.ts");
const plain = (value) => JSON.parse(JSON.stringify(value));
const person = (id, email) => ({ id, name: id, email, archivedAt: null });
const alice = person("alice", "Alice@example.com");
const duplicateAlice = person("alice-copy", " alice@EXAMPLE.com ");
const bob = person("bob", "bob@example.com");
const projects = [
  { id: "one", ownerPersonId: "alice", participantIds: ["alice", "bob"] },
  { id: "two", ownerPersonId: "bob", participantIds: ["alice-copy", "alice"] },
];

test("project roster deduplicates IDs and email backed people", () => {
  const roster = projectRoster(["one", "two"], projects, [alice, duplicateAlice, bob]);
  assert.deepEqual(plain(roster.map((item) => item.id)), ["alice", "bob"]);
  assert.deepEqual(plain(addRoster([{ id: "bob", name: "bob" }], roster, [alice, duplicateAlice, bob]).map((item) => item.id)), ["bob", "alice"]);
  assert.deepEqual(plain(addRoster([{ id: "alice-copy", name: "alice-copy" }], roster, [alice, duplicateAlice, bob]).map((item) => item.id)), ["alice-copy", "bob"]);
});

test("archived projects and people are not loaded", () => {
  const archived = { ...bob, archivedAt: "2026-01-01" };
  assert.deepEqual(plain(projectRoster(["one", "two"], [
    { ...projects[0], archivedAt: "2026-01-01" }, projects[1],
  ], [alice, duplicateAlice, archived]).map((item) => item.id)), ["alice"]);
  assert.deepEqual(plain(projectRoster(["one"], [{ ...projects[0], archivedAt: "2026-01-01" }], [alice, bob])), []);
});

test("automatic local names use an unused positive number after deletions", () => {
  assert.equal(nextLocalSpeakerName([{ id: "a", name: "화자 1" }, { id: "b", name: "화자 3" }]), "화자 2");
  assert.equal(nextLocalSpeakerName([{ id: "a", name: "Alice" }]), "화자 1");
});

test("unused noncurrent speaker removal simply removes its chip", () => {
  const rows = [{ id: 1, speaker: "alice", text: "hello", isFinal: true }];
  const result = removeSpeaker([{ id: "alice", name: "Alice" }, { id: "bob", name: "Bob" }], rows, "alice", "bob", "local-new");
  assert.deepEqual(plain(result.rows), rows);
  assert.equal(result.currentSpeaker, "alice");
  assert.equal(result.reassigned, 0);
  assert.equal(result.replacement, null);
  assert.deepEqual(plain(result.speakers.map((item) => item.id)), ["alice"]);
});

test("used speaker removal inserts an editable replacement in place and preserves serialized turns", () => {
  const rows = [
    { id: 1, speaker: "alice", personId: "alice", text: "edited text", edited: true, isFinal: true, startSeconds: 2, endSeconds: 4 },
    { id: 2, speaker: "alice", personId: "alice", text: "second", isFinal: true },
    { id: 3, speaker: "bob", personId: "bob", text: "other", isFinal: true },
  ];
  const speakers = [{ id: "bob", name: "Bob" }, { id: "alice", name: "Alice" }, { id: "local-1", name: "화자 1" }];
  const result = removeSpeaker(speakers, rows, "bob", "alice", "local-new");
  assert.equal(result.reassigned, 2);
  assert.equal(result.currentSpeaker, "bob");
  assert.deepEqual(plain(result.replacement), { id: "local-new", name: "화자 2" });
  assert.deepEqual(plain(result.speakers.map((item) => item.id)), ["bob", "local-new", "local-1"]);
  assert.deepEqual(plain(result.rows[0]), { ...rows[0], speaker: "local-new", personId: null });
  assert.deepEqual(plain(result.rows[1]), { ...rows[1], speaker: "local-new", personId: null });
  assert.deepEqual(plain(result.rows[2]), rows[2]);
  const utterances = meetingUtterances(result.rows, result.speakers, [alice, bob]);
  assert.deepEqual(plain(utterances.map((item) => [item.personId, item.speakerName, item.text])), [
    [null, "화자 2", "edited text"], [null, "화자 2", "second"], ["bob", "Bob", "other"],
  ]);
  assert.equal(utterances[0].startSeconds, 2);
  assert.equal(utterances[0].endSeconds, 4);
  assert.equal(utterances.map((item) => `${item.speakerName}: ${item.text.trim()}`).join("\n\n"), "화자 2: edited text\n\n화자 2: second\n\nBob: other");
});

test("current unused and last speaker removal each creates a fresh current local speaker", () => {
  const current = removeSpeaker([{ id: "alice", name: "Alice" }, { id: "bob", name: "Bob" }], [], "alice", "alice", "local-next");
  assert.deepEqual(plain(current.speakers.map((item) => item.id)), ["local-next", "bob"]);
  assert.equal(current.currentSpeaker, "local-next");
  assert.equal(current.replacement.name, "화자 1");
  const last = removeSpeaker([{ id: "local-1", name: "화자 1" }], [], "local-1", "local-1", "local-other");
  assert.deepEqual(plain(last.speakers), [{ id: "local-other", name: "화자 2" }]);
  assert.equal(last.currentSpeaker, "local-other");
});

test("separate removed speakers retain distinct replacements and utterance identities", () => {
  const rows = [
    { id: 1, speaker: "alice", personId: "alice", text: "A", isFinal: true },
    { id: 2, speaker: "bob", personId: "bob", text: "B", isFinal: true },
  ];
  const first = removeSpeaker([{ id: "alice", name: "Alice" }, { id: "bob", name: "Bob" }], rows, "alice", "alice", "local-a");
  const second = removeSpeaker(first.speakers, first.rows, first.currentSpeaker, "bob", "local-b");
  assert.deepEqual(plain(second.rows.map((row) => row.speaker)), ["local-a", "local-b"]);
  assert.deepEqual(plain(second.speakers.map((speaker) => speaker.name)), ["화자 1", "화자 2"]);
  assert.equal(second.currentSpeaker, "local-a");
});

test("later STT words still update an unfinished remapped turn", () => {
  const row = { id: 7, speaker: "alice", personId: "alice", text: "안녕", isFinal: false, edited: false };
  const removed = removeSpeaker([{ id: "alice", name: "Alice" }], [row], "alice", "alice", "local-fresh");
  const updated = mergeTranscript(removed.rows, [{ id: 7, text: "안녕하세요", isFinal: true }], removed.currentSpeaker);
  assert.equal(updated[0].text, "안녕하세요");
  assert.equal(updated[0].speaker, "local-fresh");
  assert.equal(updated[0].personId, null);
  assert.equal(updated[0].edited, false);
});

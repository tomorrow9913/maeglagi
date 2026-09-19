import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const exports = {};
const source = fs.readFileSync(
  new URL("../src/features/source-ingestion/lib/transcript-draft.ts", import.meta.url),
  "utf8",
);
const code = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
vm.runInNewContext(code, { exports });
const { mergeTranscript, serializeTranscript } = exports;
const plain = (value) => JSON.parse(JSON.stringify(value));

test("interim rows evolve into final rows by stable ID without mutating inputs", () => {
  const first = [{ id: 0, text: "초안", isFinal: false }];
  const draft = mergeTranscript([], first, "0");
  const next = [{ id: 0, text: "완성 문장", isFinal: true }];
  const result = mergeTranscript(draft, next, "1");

  assert.deepEqual(plain(result), [{ id: 0, text: "완성 문장", isFinal: true, speaker: "0" }]);
  assert.deepEqual(plain(draft), [{ id: 0, text: "초안", isFinal: false, speaker: "0" }]);
  assert.deepEqual(first, [{ id: 0, text: "초안", isFinal: false }]);
  assert.deepEqual(next, [{ id: 0, text: "완성 문장", isFinal: true }]);
  assert.notStrictEqual(result[0], draft[0]);
});

test("manual text edits survive STT updates while finality advances", () => {
  const draft = [{ id: 4, text: "직접 고친 문장", isFinal: false, speaker: "0", edited: true }];
  const result = mergeTranscript(draft, [{ id: 4, text: "인식기가 바꾼 문장", isFinal: true }], "1");

  assert.deepEqual(plain(result), [
    { id: 4, text: "직접 고친 문장", isFinal: true, speaker: "0", edited: true },
  ]);
  assert.equal(draft[0].isFinal, false);
});

test("speaker changes apply only to new rows", () => {
  const first = mergeTranscript([], [{ id: 0, text: "첫 문장", isFinal: true }], "0");
  const next = mergeTranscript(
    first,
    [
      { id: 0, text: "첫 문장", isFinal: true },
      { id: 1, text: "둘째 문장", isFinal: false },
    ],
    "1",
  );

  assert.deepEqual(plain(next.map(({ id, speaker }) => ({ id, speaker }))), [
    { id: 0, speaker: "0" },
    { id: 1, speaker: "1" },
  ]);
});

test("vanished interim rows are removed while final, edited, and manual rows remain", () => {
  const current = [
    { id: 0, text: "최종", isFinal: true, speaker: "0" },
    { id: 1, text: "사라진 초안", isFinal: false, speaker: "0" },
    { id: 2, text: "수정한 초안", isFinal: false, speaker: "1", edited: true },
    { id: -1, text: "직접 추가", isFinal: false, speaker: "1" },
  ];
  const result = mergeTranscript(current, [{ id: 3, text: "새 초안", isFinal: false }], "2");

  assert.deepEqual(plain(result.map(({ id }) => id)), [0, 2, -1, 3]);
  assert.equal(result[3].speaker, "2");
  assert.equal(current.length, 4);
});

test("serialization trims text, skips blanks, and falls back for missing speaker names", () => {
  const rows = [
    { id: 0, text: "  안녕하세요  ", isFinal: true, speaker: "0" },
    { id: 1, text: " \n ", isFinal: false, speaker: "0" },
    { id: 2, text: "  다음 문장 ", isFinal: true, speaker: "1" },
    { id: -1, text: "메모", isFinal: true, speaker: "3" },
  ];

  assert.equal(
    serializeTranscript(rows, ["  민지  ", "  "]),
    "민지: 안녕하세요\n\n화자 2: 다음 문장\n\n화자 4: 메모",
  );
  assert.equal(serializeTranscript([], []), "");
  assert.equal(rows[0].text, "  안녕하세요  ");
});

import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

import {
  DISCONNECTED_MESSAGE,
  NO_EVIDENCE_MESSAGE,
  STORED_TURN_LIMIT,
  failTurn,
  isNearBottom,
  isNoEvidenceEvent,
  newTurn,
  parseTurns,
  reduceTurn,
  serializeTurns,
  settleTurn,
  turnsStorageKey,
  waitingLabel,
} from "../src/features/ask/lib/ask-turns.ts";
import { formatOffset, formatSourceMeta } from "../src/features/ask/lib/source-meta.ts";
import { connectionLabels, modelOptionLabel } from "../src/features/ask/lib/model-label.ts";

const source = {
  index: 1,
  sourceId: "source-1",
  chunkId: "chunk-1",
  kind: "meeting",
  title: "9월 12일 회의",
  excerpt: "p95가 320ms로 내려갔습니다.",
  timestamp: 754,
};

function reduceAll(events) {
  return events.reduce(reduceTurn, newTurn("turn-1", "왜 바꿨나요?"));
}

test("the no-evidence and waiting copy match the docs/voice.md table", () => {
  const voice = fs.readFileSync(new URL("../../docs/voice.md", import.meta.url), "utf8");
  assert.equal(
    NO_EVIDENCE_MESSAGE,
    "이 워크스페이스의 소스에서는 답할 근거를 찾지 못했어요. 관련 회의나 문서를 먼저 올려주세요.",
  );
  assert.ok(voice.includes(`| ${NO_EVIDENCE_MESSAGE} |`));
  assert.ok(voice.includes(`| ${waitingLabel({ sources: [] })} |`));
});

test("sources, tokens and done build a finished answer", () => {
  const turn = reduceAll([
    { type: "sources", sources: [source] },
    { type: "token", text: "p95가 " },
    { type: "token", text: "내려갔습니다[1]." },
    { type: "done" },
  ]);
  assert.equal(turn.status, "done");
  assert.equal(turn.answer, "p95가 내려갔습니다[1].");
  assert.deepEqual(turn.sources, [source]);
});

test("no evidence is a normal outcome, by code or by an older server's message", () => {
  assert.equal(isNoEvidenceEvent({ code: "no_evidence", message: "anything" }), true);
  assert.equal(
    isNoEvidenceEvent({
      message: "질문과 관련된 근거를 찾지 못했습니다. 회의나 문서를 올린 뒤 다시 물어봐 주세요.",
    }),
    true,
  );
  assert.equal(isNoEvidenceEvent({ message: "답변을 만드는 중 문제가 생겼습니다." }), false);

  const turn = reduceAll([{ type: "error", message: "서버 문구", code: "no_evidence" }]);
  assert.equal(turn.status, "no_evidence");
  assert.equal(turn.errorMessage, undefined);
});

test("a mid-stream failure keeps the text already received", () => {
  const turn = reduceAll([
    { type: "sources", sources: [source] },
    { type: "token", text: "p95가 내려갔습니다" },
    { type: "error", message: "모델 응답이 중단됐습니다." },
  ]);
  assert.equal(turn.status, "error");
  assert.equal(turn.errorMessage, "모델 응답이 중단됐습니다.");
  assert.equal(turn.answer, "p95가 내려갔습니다");
  assert.deepEqual(turn.sources, [source]);
});

test("events after the end do not reopen a finished turn", () => {
  const done = reduceAll([{ type: "token", text: "끝" }, { type: "done" }]);
  assert.equal(reduceTurn(done, { type: "token", text: " 더" }), done);
  assert.equal(reduceTurn(done, { type: "error", message: "늦은 오류" }), done);
});

test("a stream that ends without done never stays streaming", () => {
  const partial = reduceAll([{ type: "token", text: "받은 데까지" }]);

  const disconnected = settleTurn(partial, "disconnected");
  assert.equal(disconnected.status, "error");
  assert.equal(disconnected.errorMessage, DISCONNECTED_MESSAGE);
  assert.equal(disconnected.answer, "받은 데까지");

  const aborted = settleTurn(partial, "aborted");
  assert.equal(aborted.status, "aborted");
  assert.equal(aborted.answer, "받은 데까지");

  const done = reduceTurn(partial, { type: "done" });
  assert.equal(settleTurn(done, "disconnected"), done);
  assert.equal(failTurn(done, "무시"), done);
  assert.equal(failTurn(partial, "모델 없음", "settings").errorAction, "settings");
});

test("the waiting line stops saying it is searching once sources arrived", () => {
  assert.equal(waitingLabel({ sources: [] }), "관련 회의와 문서를 찾아보고 있어요");
  assert.equal(waitingLabel({ sources: [source] }), "찾은 근거로 답변을 쓰고 있어요");
});

test("only finished turns are stored and none comes back streaming", () => {
  const done = reduceAll([
    { type: "sources", sources: [source] },
    { type: "token", text: "답" },
    { type: "done" },
  ]);
  const streaming = { ...newTurn("turn-2", "진행 중"), answer: "쓰는 중" };
  const raw = serializeTurns([done, streaming]);

  assert.deepEqual(parseTurns(raw), [done]);
  assert.equal(turnsStorageKey("ws-1"), "maeglagi:ask:ws-1");

  // 누군가 저장소를 고쳐 streaming을 넣어도 되살리지 않습니다.
  const tampered = JSON.stringify({ version: 1, turns: [streaming, done] });
  assert.deepEqual(parseTurns(tampered), [done]);
});

test("broken or foreign stored values are dropped instead of throwing", () => {
  assert.deepEqual(parseTurns(null), []);
  assert.deepEqual(parseTurns(""), []);
  assert.deepEqual(parseTurns("{not json"), []);
  assert.deepEqual(parseTurns(JSON.stringify({ version: 99, turns: [] })), []);
  assert.deepEqual(parseTurns(JSON.stringify({ version: 1, turns: "nope" })), []);
  assert.deepEqual(
    parseTurns(
      JSON.stringify({
        version: 1,
        turns: [
          { id: "a", question: "q", answer: "a", status: "done", sources: [{ index: "1" }] },
          { id: "b", question: "q", status: "done", sources: [] },
          null,
        ],
      }),
    ),
    [],
  );
});

test("storage keeps only the most recent turns", () => {
  const many = Array.from({ length: STORED_TURN_LIMIT + 5 }, (_, index) => ({
    ...newTurn(`turn-${index}`, `질문 ${index}`),
    status: "done",
  }));
  const restored = parseTurns(serializeTurns(many));
  assert.equal(restored.length, STORED_TURN_LIMIT);
  assert.equal(restored.at(-1).id, `turn-${STORED_TURN_LIMIT + 4}`);
});

test("auto-follow only applies near the bottom", () => {
  assert.equal(isNearBottom({ scrollTop: 880, clientHeight: 1000, scrollHeight: 2000 }), true);
  assert.equal(isNearBottom({ scrollTop: 879, clientHeight: 1000, scrollHeight: 2000 }), false);
  assert.equal(isNearBottom({ scrollTop: 0, clientHeight: 800, scrollHeight: 600 }), true);
  assert.equal(isNearBottom({ scrollTop: 500, clientHeight: 1000, scrollHeight: 2000 }, 500), true);
});

test("source cards say meeting or document in words, with the meeting offset", () => {
  assert.equal(formatSourceMeta("document"), "문서");
  assert.equal(formatSourceMeta("document", 30), "문서");
  assert.equal(formatSourceMeta("meeting"), "회의");
  assert.equal(formatSourceMeta("meeting", 754), "회의 · 12:34");
  assert.equal(formatSourceMeta("meeting", 754.9), "회의 · 12:34");
  assert.equal(formatSourceMeta("meeting", 0), "회의 · 00:00");
  assert.equal(formatSourceMeta("meeting", -1), "회의");
  assert.equal(formatOffset(3725), "1:02:05");
});

test("model options are named by connection label, never by id or URL", () => {
  const labels = connectionLabels([
    { id: "11111111-aaaa", label: "팀 키", keyHint: "ab12" },
    { id: "22222222-bbbb", label: "팀 키", keyHint: "cd34" },
    { id: "33333333-cccc", label: "개인 키", keyHint: "ef56" },
    { id: "44444444-dddd", label: "로컬", keyHint: "local" },
    { id: "55555555-eeee", label: "로컬", keyHint: "none" },
  ]);
  const name = (id) => (id === "openai" ? "OpenAI" : id);

  assert.equal(
    modelOptionLabel(
      { provider: "openai", model: "gpt-x", credentialId: "33333333-cccc" },
      name,
      labels,
    ),
    "OpenAI · gpt-x · 개인 키",
  );
  assert.equal(
    modelOptionLabel(
      { provider: "openai", model: "gpt-x", credentialId: "22222222-bbbb" },
      name,
      labels,
    ),
    "OpenAI · gpt-x · 팀 키 (끝자리 cd34)",
  );
  assert.equal(labels.get("44444444-dddd"), "로컬 (1)");
  assert.equal(labels.get("55555555-eeee"), "로컬 (2)");
  // 목록에 없는 연결은 id 조각을 보여주지 않고 연결 이름을 뺍니다.
  assert.equal(
    modelOptionLabel(
      { provider: "ollama", model: "llama", credentialId: "99999999-ffff" },
      name,
      labels,
    ),
    "ollama · llama",
  );
  assert.equal(
    modelOptionLabel({ provider: "openai", model: "gpt-x" }, name, labels),
    "OpenAI · gpt-x",
  );
});

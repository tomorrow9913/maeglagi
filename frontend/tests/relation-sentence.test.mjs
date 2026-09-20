import assert from "node:assert/strict";
import test from "node:test";

import { loadTs } from "./_load-ts.mjs";

const { josa, relationSentence } = loadTs("features/knowledge-graph/lib/relation-sentence.ts");

test("particles follow the final consonant of the name", () => {
  assert.equal(josa("홍길동", "이/가"), "이");
  assert.equal(josa("김민지", "이/가"), "가");
  assert.equal(josa("범위 결정", "을/를"), "을");
  assert.equal(josa("킥오프 회의", "을/를"), "를");
  assert.equal(josa("홍길동", "과/와"), "과");
  assert.equal(josa("김민지", "과/와"), "와");
  // ㄹ 받침은 "로"
  assert.equal(josa("하이브리드 검색", "으로/로"), "으로");
  assert.equal(josa("서울", "으로/로"), "로");
  assert.equal(josa("재검토", "으로/로"), "로");
});

test("numbers read aloud, closing brackets are skipped, unknown sounds show both forms", () => {
  assert.equal(josa("스프린트 3", "이/가"), "이"); // 삼
  assert.equal(josa("스프린트 2", "이/가"), "가"); // 이
  assert.equal(josa("9/8 회의 (오전)", "을/를"), "을");
  assert.equal(josa("BYOK", "이/가"), "이(가)");
  assert.equal(josa("BYOK", "으로/로"), "(으)로");
});

const sentence = (relation, direction, otherLabel, sourceType = "person") =>
  relationSentence({ relation, direction, otherLabel, sourceType });

test("relations read as sentences from the viewed node's side, without arrows", () => {
  // 사람 → 이벤트
  assert.equal(sentence("participates_in", "in", "홍길동"), "홍길동이 참여");
  assert.equal(sentence("participates_in", "out", "킥오프 회의"), "킥오프 회의에 참여");
  // 업무 → 사람
  assert.equal(sentence("assigned_to", "out", "김민지", "task"), "김민지가 담당");
  assert.equal(sentence("assigned_to", "in", "BYOK 설정 화면", "task"), "BYOK 설정 화면을 담당");
  // 막는 쪽 → 막히는 쪽
  assert.equal(sentence("blocks", "out", "배포", "task"), "배포를 막음");
  assert.equal(sentence("blocks", "in", "인증 오류", "task"), "인증 오류가 막음");
  // 새 결정 → 이전 결정
  assert.equal(
    sentence("supersedes", "out", "전체 범위 개발", "decision"),
    "전체 범위 개발을 대체",
  );
  assert.equal(
    sentence("supersedes", "in", "하이브리드 검색", "decision"),
    "하이브리드 검색으로 대체됨",
  );
  assert.equal(sentence("relates_to", "in", "맥락이", "decision"), "맥락이와 관련");
});

test("'decided' reads correctly for both edge directions the data uses", () => {
  // 서버: 결정 → 결정이 나온 회의
  assert.equal(sentence("decided", "out", "킥오프 회의", "decision"), "킥오프 회의에서 결정됨");
  assert.equal(sentence("decided", "in", "범위 결정", "decision"), "범위 결정을 결정함");
  // mock: 사람 → 결정
  assert.equal(sentence("decided", "out", "범위 결정", "person"), "범위 결정을 결정함");
  assert.equal(sentence("decided", "in", "홍길동", "person"), "홍길동이 결정함");
});

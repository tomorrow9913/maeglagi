import assert from "node:assert/strict";
import test from "node:test";

import {
  errorKindForStatus,
  parseRetryAfter,
  toUserMessage,
  userMessageForResponse,
} from "../src/lib/api/error-message.ts";

test("English backend detail never reaches the user", () => {
  for (const [status, detail] of [
    [404, "Workspace not found"],
    [409, "Stale review revision"],
    [400, "Invalid Ollama baseUrl"],
    [403, "Provider mismatch"],
  ]) {
    const message = userMessageForResponse(status, { detail });
    assert.doesNotMatch(message, /[A-Za-z]{4,}/, `${status} leaked: ${message}`);
    assert.match(message, /[가-힣]/);
  }
});

test("Korean backend detail written for users passes through", () => {
  const detail = "임베딩을 지원하는 API key가 없습니다.";
  assert.equal(userMessageForResponse(422, { detail }), detail);
});

test("validation arrays and non-JSON bodies fall back to a status message without the code", () => {
  const pydantic = { detail: [{ loc: ["body", "name"], msg: "String should have at most 120" }] };
  for (const body of [pydantic, undefined, "<html>502</html>"]) {
    const message = userMessageForResponse(body === pydantic ? 422 : 502, body);
    assert.doesNotMatch(message, /\d{3}/);
    assert.match(message, /[가-힣]/);
  }
});

test("an expired session always tells the user to log in again", () => {
  assert.equal(errorKindForStatus(401), "auth");
  assert.match(userMessageForResponse(401, { detail: "Invalid or expired access token" }), /로그인/);
  assert.match(userMessageForResponse(401, { detail: "토큰이 없습니다." }), /다시 로그인/);
});

test("status codes map to the kinds screens branch on", () => {
  assert.equal(errorKindForStatus(0), "network");
  assert.equal(errorKindForStatus(409), "conflict");
  assert.equal(errorKindForStatus(413), "tooLarge");
  assert.equal(errorKindForStatus(422), "invalid");
  assert.equal(errorKindForStatus(429), "rateLimited");
  assert.equal(errorKindForStatus(503), "server");
});

test("Retry-After accepts seconds and HTTP dates", () => {
  assert.equal(parseRetryAfter("30"), 30);
  assert.equal(parseRetryAfter(null), undefined);
  assert.equal(parseRetryAfter("soon"), undefined);
  const now = Date.parse("2026-09-20T00:00:00Z");
  assert.equal(parseRetryAfter("Sun, 20 Sep 2026 00:00:45 GMT", now), 45);
});

test("caught non-API errors use the Korean fallback instead of English text", () => {
  assert.equal(toUserMessage(new TypeError("Failed to fetch"), "불러오지 못했습니다."), "불러오지 못했습니다.");
  assert.equal(toUserMessage(new Error("파일이 너무 큽니다."), "fallback"), "파일이 너무 큽니다.");
  assert.equal(toUserMessage("boom", "불러오지 못했습니다."), "불러오지 못했습니다.");
});

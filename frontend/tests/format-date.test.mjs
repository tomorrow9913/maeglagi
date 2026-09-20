import assert from "node:assert/strict";
import test from "node:test";

import { localDateKey, localDateLabel, localTime } from "../src/lib/format-date.ts";

const seoul = "Asia/Seoul";

test("a UTC timestamp shows the viewer's wall-clock time, not the UTC digits", () => {
  assert.equal(localTime("2026-09-11T06:20:00Z", seoul), "15:20");
  assert.equal(localTime("2026-09-11T15:05:00Z", seoul), "00:05");
});

test("items near midnight land on the local day", () => {
  assert.equal(localDateKey("2026-09-11T15:30:00Z", seoul), "2026-09-12");
  assert.equal(localDateKey("2026-09-11T14:59:00Z", seoul), "2026-09-11");
  assert.equal(localDateLabel("2026-09-11T15:30:00Z", seoul), "2026년 9월 12일 (토)");
});

test("unparseable input falls back to the raw digits instead of throwing", () => {
  assert.equal(localDateKey("2026-09-11", seoul), "2026-09-11");
  assert.equal(localTime("not a date"), "");
});

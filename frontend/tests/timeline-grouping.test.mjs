import assert from "node:assert/strict";
import test from "node:test";

import { loadTs } from "./_load-ts.mjs";

const { groupByDate } = loadTs("features/context-timeline/lib/group-by-date.ts");

const seoul = "Asia/Seoul";
const item = (id, occurredAt) => ({
  id,
  kind: "decision",
  title: id,
  summary: "",
  occurredAt,
  sources: [],
});

test("an item just after local midnight groups under the viewer's day, not the UTC day", () => {
  const groups = groupByDate([item("late", "2026-09-11T15:30:00Z")], seoul);

  assert.equal(groups.length, 1);
  assert.equal(groups[0].date, "2026-09-12");
  assert.equal(groups[0].label, "2026년 9월 12일 (토)");
});

test("items on the same UTC day split into two local days around midnight", () => {
  const groups = groupByDate(
    [
      item("afternoon", "2026-09-11T06:20:00Z"), // 9/11 15:20 KST
      item("before-midnight", "2026-09-11T14:59:00Z"), // 9/11 23:59 KST
      item("after-midnight", "2026-09-11T15:30:00Z"), // 9/12 00:30 KST
    ],
    seoul,
  );

  assert.deepEqual(
    groups.map((group) => [group.date, group.items.map((entry) => entry.id)]),
    [
      ["2026-09-12", ["after-midnight"]],
      ["2026-09-11", ["before-midnight", "afternoon"]],
    ],
  );
  assert.equal(groups[1].label, "2026년 9월 11일 (금)");
});

test("the same instants group differently for a viewer in another time zone", () => {
  const groups = groupByDate(
    [item("a", "2026-09-11T15:30:00Z"), item("b", "2026-09-11T03:00:00Z")],
    "America/Los_Angeles",
  );

  assert.deepEqual(
    groups.map((group) => [group.date, group.items.map((entry) => entry.id)]),
    [
      ["2026-09-11", ["a"]],
      ["2026-09-10", ["b"]],
    ],
  );
});

test("ordering inside a day compares instants, so mixed UTC offsets still sort newest first", () => {
  const groups = groupByDate(
    [
      item("kst-morning", "2026-09-12T09:00:00+09:00"), // 00:00Z
      item("utc-early", "2026-09-12T01:00:00Z"), // 10:00 KST, later than kst-morning
    ],
    seoul,
  );

  assert.deepEqual(
    groups[0].items.map((entry) => entry.id),
    ["utc-early", "kst-morning"],
  );
});

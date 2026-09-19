import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const exports = {};
vm.runInNewContext(
  ts.transpileModule(
    fs.readFileSync(
      new URL("../src/features/directory/lib/project-people.ts", import.meta.url),
      "utf8",
    ),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } },
  ).outputText,
  { exports, Map, Set },
);
const { listProjectPeople } = exports;

const owner = { id: "owner", name: "Owner", archivedAt: null };
const member = { id: "member", name: "Member", archivedAt: null };

test("owner-only project exposes its owner in the clickable roster", () => {
  const roster = listProjectPeople(
    { ownerPersonId: owner.id, participantIds: [] },
    [owner],
  );
  assert.equal(roster.length, 1);
  assert.equal(roster[0].person, owner);
  assert.equal(roster[0].isOwner, true);
});

test("owner who is also a member appears once, before other participants", () => {
  const roster = listProjectPeople(
    { ownerPersonId: owner.id, participantIds: [member.id, owner.id] },
    [owner, member],
  );
  assert.equal(roster.map((item) => item.id).join(","), "owner,member");
  assert.equal(roster[0].isOwner, true);
  assert.equal(roster[1].isOwner, false);
});

test("archived owner remains reachable for person restore", () => {
  const archivedOwner = { ...owner, archivedAt: "2026-09-19T00:00:00Z" };
  const roster = listProjectPeople(
    { ownerPersonId: owner.id, participantIds: [] },
    [archivedOwner],
  );
  assert.equal(roster.length, 1);
  assert.equal(roster[0].person, archivedOwner);
  assert.equal(roster[0].person.archivedAt, archivedOwner.archivedAt);
});

import assert from "node:assert/strict";
import test from "node:test";

import { loadTs } from "./_load-ts.mjs";

const { isFormDirty, parseAliases, personFormFrom, projectDateError, projectFormFrom } = loadTs(
  "features/directory/lib/directory-forms.ts",
);
const { directoryToast, mutationErrorMessage } = loadTs(
  "features/directory/lib/directory-messages.ts",
);

const person = { id: "p1", name: "김민지", email: null, aliases: ["민지", "MJ"], role: null };
const project = {
  id: "pr1",
  name: "맥락이",
  goal: null,
  description: "설명",
  ownerPersonId: null,
  participantIds: ["a", "b"],
  startsOn: "2026-09-01",
  endsOn: null,
};

test("an abandoned edit is replaced by the stored values when the form is rebuilt", () => {
  const abandoned = { ...personFormFrom(person), name: "지우다 만 이름" };
  assert.equal(isFormDirty(abandoned, personFormFrom(person)), true);

  assert.deepEqual(personFormFrom(person), {
    name: "김민지",
    email: "",
    aliases: "민지, MJ",
    role: "",
  });
  assert.deepEqual(parseAliases(" 민지, ,MJ ,"), ["민지", "MJ"]);
});

test("dirty check ignores surrounding whitespace and participant order", () => {
  const initial = projectFormFrom(project);

  assert.equal(isFormDirty({ ...initial }, initial), false);
  assert.equal(isFormDirty({ ...initial, name: " 맥락이 " }, initial), false);
  assert.equal(isFormDirty({ ...initial, participantIds: ["b", "a"] }, initial), false);
  assert.equal(isFormDirty({ ...initial, participantIds: ["a"] }, initial), true);
  assert.equal(isFormDirty({ ...initial, goal: "새 목표" }, initial), true);
});

test("an inverted period explains itself instead of silently disabling save", () => {
  assert.equal(
    projectDateError({ startsOn: "2026-09-10", endsOn: "2026-09-09" }),
    "종료일은 시작일 이후여야 합니다.",
  );
  assert.equal(projectDateError({ startsOn: "2026-09-10", endsOn: "2026-09-10" }), undefined);
  assert.equal(projectDateError({ startsOn: "", endsOn: "2026-09-09" }), undefined);
});

test("a conflict says what to do next, and an email clash is not called a stale edit", () => {
  const stale = Object.assign(new Error("다른 곳에서 먼저 바뀌었습니다."), {
    kind: "conflict",
    detail: { detail: "Stale project revision" },
  });
  assert.equal(
    mutationErrorMessage(stale),
    "다른 곳에서 먼저 바뀌었습니다. 최신 내용으로 다시 열어 주세요.",
  );

  const emailClash = Object.assign(new Error("x"), {
    kind: "conflict",
    detail: { detail: "Person email conflict" },
  });
  assert.match(mutationErrorMessage(emailClash), /같은 이메일을 쓰는 참여자가 이미 있습니다/);
});

test("raw English errors never reach the toast, Korean messages pass through", () => {
  assert.equal(
    mutationErrorMessage(new Error("Failed to fetch")),
    "요청을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.",
  );
  assert.equal(
    mutationErrorMessage(new Error("프로젝트를 찾을 수 없습니다.")),
    "프로젝트를 찾을 수 없습니다.",
  );
});

test("each action has its own toast, written as a plain statement", () => {
  assert.equal(directoryToast.projectArchived("맥락이"), "'맥락이' 프로젝트를 보관했습니다.");
  assert.equal(directoryToast.personAdded, "참여자를 추가했습니다.");

  const all = Object.values(directoryToast).map((entry) =>
    typeof entry === "function" ? entry("이름") : entry,
  );
  assert.equal(new Set(all).size, all.length);
  for (const message of all) {
    assert.match(message, /니다\.$/);
    assert.doesNotMatch(message, /[!]|하세요|죄송/);
  }
});

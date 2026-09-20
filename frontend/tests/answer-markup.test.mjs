import assert from "node:assert/strict";
import test from "node:test";

import { parseAnswer, parseInline } from "../src/features/ask/lib/answer-markup.ts";

const text = (value) => ({ type: "text", text: value });

test("plain text with citations keeps the citation positions", () => {
  assert.deepEqual(parseInline("p95가 내려갔습니다[1]. 목표는 500ms입니다[12]."), [
    text("p95가 내려갔습니다"),
    { type: "citation", index: 1, raw: "[1]", offset: 11 },
    text(". 목표는 500ms입니다"),
    { type: "citation", index: 12, raw: "[12]", offset: 28 },
    text("."),
  ]);
});

test("brackets that are not citations stay text", () => {
  assert.deepEqual(parseInline("[참고] 2026-09-12 [메모] 값[a] []"), [
    text("[참고] 2026-09-12 [메모] 값[a] []"),
  ]);
});

test("bold and code are split out, and citations survive inside bold", () => {
  assert.deepEqual(parseInline("**hybrid retrieval[2]**을 `top_k=8`로 씁니다."), [
    {
      type: "bold",
      children: [text("hybrid retrieval"), { type: "citation", index: 2, raw: "[2]", offset: 18 }],
    },
    text("을 "),
    { type: "code", text: "top_k=8" },
    text("로 씁니다."),
  ]);
});

test("a citation-looking token inside code is not a citation", () => {
  assert.deepEqual(parseInline("`items[1]` 값"), [{ type: "code", text: "items[1]" }, text(" 값")]);
});

test("unclosed markers while streaming stay literal", () => {
  assert.deepEqual(parseInline("결정은 **하이브"), [text("결정은 **하이브")]);
  assert.deepEqual(parseInline("값은 `top_k"), [text("값은 `top_k")]);
  assert.deepEqual(parseInline("2 ** 3 ** 4"), [text("2 ** 3 ** 4")]);
  assert.deepEqual(parseInline("****"), [text("****")]);
});

test("markup never spans lines", () => {
  assert.deepEqual(parseInline("**첫 줄\n둘째 줄**"), [text("**첫 줄\n둘째 줄**")]);
});

test("html in the answer is carried as text, not as markup", () => {
  assert.deepEqual(parseAnswer("<img src=x onerror=alert(1)>"), [
    { type: "paragraph", children: [text("<img src=x onerror=alert(1)>")] },
  ]);
});

test("paragraphs split on blank lines and keep single line breaks", () => {
  assert.deepEqual(parseAnswer("첫 문단\n같은 문단\n\n\n둘째 문단[1]"), [
    { type: "paragraph", children: [text("첫 문단\n같은 문단")] },
    {
      type: "paragraph",
      children: [text("둘째 문단"), { type: "citation", index: 1, raw: "[1]", offset: 18 }],
    },
  ]);
});

test("bullet and numbered lines become lists with their citations", () => {
  const blocks = parseAnswer(
    "이유는 둘입니다.\n- 속도[1]\n* **정확도**[2]\n\n3. 셋째\n4) 넷째\n마무리",
  );
  assert.deepEqual(
    blocks.map((block) => block.type),
    ["paragraph", "list", "list", "paragraph"],
  );
  assert.equal(blocks[1].ordered, false);
  assert.deepEqual(blocks[1].items[0], [
    text("속도"),
    { type: "citation", index: 1, raw: "[1]", offset: 14 },
  ]);
  assert.deepEqual(blocks[1].items[1][0], { type: "bold", children: [text("정확도")] });
  assert.equal(blocks[1].items[1][1].index, 2);
  assert.equal(blocks[2].ordered, true);
  assert.equal(blocks[2].start, 3);
  assert.equal(blocks[2].items.length, 2);
});

test("a numbered list separated by blank lines stays one list", () => {
  const blocks = parseAnswer("1. 하나\n\n2. 둘");
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0].items.length, 2);
});

test("dates, negatives and bold-led lines are not list items", () => {
  for (const line of [
    "2026. 9. 12 회의에서 정했습니다.",
    "-5도까지 내려갑니다.",
    "**결론** 입니다",
  ]) {
    assert.equal(parseAnswer(line)[0].type, "paragraph", line);
  }
});

test("citation offsets are unique across the whole answer so keys never collide", () => {
  const offsets = [];
  const walk = (nodes) =>
    nodes.forEach((node) => {
      if (node.type === "citation") offsets.push(node.offset);
      if (node.type === "bold") walk(node.children);
    });
  for (const block of parseAnswer("가[1] 나[1]\n- 다[1]\n- **라[1]**\n\n마[1]")) {
    if (block.type === "paragraph") walk(block.children);
    else block.items.forEach(walk);
  }
  assert.equal(offsets.length, 5);
  assert.equal(new Set(offsets).size, 5);
  const source = "가[1] 나[1]\n- 다[1]\n- **라[1]**\n\n마[1]";
  for (const offset of offsets) assert.equal(source.slice(offset, offset + 3), "[1]");
});

test("empty input yields no blocks", () => {
  assert.deepEqual(parseAnswer(""), []);
  assert.deepEqual(parseAnswer("\n\n"), []);
});

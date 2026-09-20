import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function pageLinks(path, withinTag) {
  const contents = readFileSync(new URL(path, import.meta.url), "utf8");
  const source = ts.createSourceFile(path, contents, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const links = [];

  function visit(node, inScope = !withinTag) {
    if (ts.isJsxElement(node) && node.openingElement.tagName.getText(source) === withinTag) inScope = true;
    if (inScope && ts.isJsxElement(node) && ["Link", "a"].includes(node.openingElement.tagName.getText(source))) {
      const href = node.openingElement.attributes.properties.find((property) => ts.isJsxAttribute(property) && property.name.text === "href")?.initializer;
      if (href && ts.isStringLiteral(href)) {
        links.push({ href: href.text, label: node.children.filter(ts.isJsxText).map((child) => child.text).join("").trim() });
      }
    }
    ts.forEachChild(node, (child) => visit(child, inScope));
  }
  visit(source);
  return links;
}

test("landing page keeps workspace and demo actions while exposing MCP and contribution links", () => {
  const links = pageLinks("../src/app/page.tsx");
  for (const expected of [
    { href: "/workspaces", label: "워크스페이스 열기" },
    { href: "/demo", label: "예시 워크스페이스 둘러보기" },
    { href: "/account/mcp", label: "MCP 설정" },
    { href: "https://github.com/tomorrow9913/maeglagi", label: "GitHub" },
    { href: "https://github.com/tomorrow9913/maeglagi/blob/main/CONTRIBUTING.md", label: "기여하기" },
  ]) assert.deepEqual(links.find((item) => item.href === expected.href && item.label === expected.label), expected);
  assert.deepEqual(pageLinks("../src/app/page.tsx", "header"), [
    { href: "/account/mcp", label: "MCP 설정" },
    { href: "https://github.com/tomorrow9913/maeglagi", label: "GitHub" },
    { href: "https://github.com/tomorrow9913/maeglagi/blob/main/CONTRIBUTING.md", label: "기여하기" },
  ]);
});

test("workspaces header exposes the account MCP settings action", () => {
  assert.deepEqual(pageLinks("../src/app/workspaces/page.tsx").find((item) => item.label === "MCP 설정"), { href: "/account/mcp", label: "MCP 설정" });
});

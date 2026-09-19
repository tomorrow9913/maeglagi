import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

function load(relativePath) {
  const exports = {};
  vm.runInNewContext(
    ts.transpileModule(fs.readFileSync(new URL(relativePath, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText,
    { exports, JSON },
  );
  return exports;
}

const { BOOTSTRAP_AI_PROVIDERS, withOllamaProvider } = load("../src/lib/api/providers.ts");
const { optionKey, sameSelection, bindCredentialToSelections } = load("../src/features/workspace/lib/model-roles.ts");

test("Ollama remains selectable when the server catalog omits it", () => {
  const providers = withOllamaProvider([{ id: "openai", displayName: "OpenAI", capabilities: [], configured: false, models: [] }]);
  assert.equal(providers.find((item) => item.id === "ollama")?.authMode, "optionalApiKey");
  assert.equal(providers.find((item) => item.id === "ollama")?.requiresBaseUrl, true);
  assert.equal(BOOTSTRAP_AI_PROVIDERS.filter((item) => item.id === "ollama").length, 1);
  const legacy = withOllamaProvider([{ id: "ollama", displayName: "Ollama", authMode: "none", configured: false, models: [], capabilities: [] }]);
  assert.equal(legacy[0].authMode, "optionalApiKey");
  assert.equal(legacy[0].requiresBaseUrl, true);
});

test("same model on two Ollama credentials remains two choices", () => {
  const first = { provider: "ollama", model: "llama3.2:latest", credentialId: "server-a" };
  const second = { ...first, credentialId: "server-b" };
  assert.notEqual(optionKey(first), optionKey(second));
  assert.equal(sameSelection(first, second), false);
  assert.equal(sameSelection(first, { ...first }), true);
});

test("new workspace binds every role to its chosen account credential", () => {
  const selections = {
    answer: { provider: "openai", model: "gpt-4.1-mini" },
    extraction: { provider: "openai", model: "gpt-4.1-mini", credentialId: "account-a" },
  };
  const bound = bindCredentialToSelections(selections, "openai", "account-a");
  assert.equal(bound.answer.credentialId, "account-a");
  assert.equal(bound.extraction.credentialId, "account-a");
  assert.equal(selections.answer.credentialId, undefined);
  assert.throws(() => bindCredentialToSelections(selections, "openai", "account-b"));
  assert.throws(() => bindCredentialToSelections(selections, "anthropic", "account-a"));
});

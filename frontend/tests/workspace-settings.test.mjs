import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

function load(relativePath, modules = {}) {
  const exports = {};
  const code = ts.transpileModule(fs.readFileSync(new URL(relativePath, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(code, {
    exports,
    require: (name) => {
      if (!(name in modules)) throw new Error(`unstubbed import: ${name}`);
      return modules[name];
    },
    // 호스트의 Error를 넘겨, 테스트가 만든 오류도 모듈 안의 `instanceof Error`를 통과하게 합니다.
    Error, URL, JSON, Map, Date, Promise, setTimeout, clearTimeout, AbortController, DOMException, structuredClone, console,
    process: { env: {} },
  });
  return exports;
}

const errorMessage = load("../src/lib/api/error-message.ts");
const ollamaUrl = load("../src/features/workspace/lib/ollama-url.ts");
const credentialMessages = load("../src/features/workspace/lib/credential-messages.ts", {
  "@/lib/api/error-message": errorMessage,
});
const { firstUnmetRequirement } = load("../src/features/workspace/lib/create-requirements.ts");

class ApiError extends Error {
  constructor(status, message, detail) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

test("half-typed Ollama addresses are caught on the client and never sent to the server", () => {
  const { ollamaUrlShapeError, isTypingScheme, OLLAMA_URL_SCHEME_MESSAGE, OLLAMA_URL_INCOMPLETE_MESSAGE } = ollamaUrl;
  assert.equal(ollamaUrlShapeError(""), undefined);
  for (const value of ["h", "https", "https:/", "ollama.example.com", "ftp://ollama.example.com", "localhost:11434"]) {
    assert.equal(ollamaUrlShapeError(value), OLLAMA_URL_SCHEME_MESSAGE, value);
  }
  for (const value of ["https://", "http://", "https://:11434"]) {
    assert.equal(ollamaUrlShapeError(value), OLLAMA_URL_INCOMPLETE_MESSAGE, value);
  }
  for (const value of ["https://user:pw@ollama.example.com", "https://ollama.example.com/?a=1", "https://ollama.example.com/#x"]) {
    assert.match(ollamaUrlShapeError(value), /넣을 수 없습니다/, value);
  }
  for (const value of ["https://ollama.example.com", "http://ollama:11434", " https://ollama.example.com/v1 ", "http://[::1]:11434"]) {
    assert.equal(ollamaUrlShapeError(value), undefined, value);
  }
  assert.equal(isTypingScheme("https:/"), true);
  assert.equal(isTypingScheme("HTT"), true);
  assert.equal(isTypingScheme("ollama.example.com"), false);
  assert.equal(isTypingScheme(""), false);
});

test("Ollama failure copy uses a server reason when present and never asserts a guessed cause", () => {
  const { ollamaFailureMessage, isLocalOrPrivateHost } = ollamaUrl;
  const generic = { valid: false, message: "Ollama 서버 주소 또는 연결을 확인해 주세요." };
  assert.equal(
    ollamaFailureMessage({ ...generic, reason: "address_not_permitted" }, "http://localhost:11434"),
    "맥락이 서버에서 접근할 수 없는 주소입니다. localhost나 사설 IP는 쓸 수 없어요.",
  );
  assert.equal(ollamaFailureMessage({ ...generic, reason: "https_required" }, "http://a.example.com"), "공개 주소는 https만 쓸 수 있습니다.");
  assert.equal(ollamaFailureMessage({ ...generic, reason: "unreachable" }, "https://a.example.com"), "서버가 응답하지 않습니다. 주소와 방화벽을 확인해 주세요.");

  // 지금 백엔드는 이유를 주지 않습니다. 주소 모양에서 확실한 규칙만 덧붙입니다.
  assert.match(ollamaFailureMessage(generic, "http://192.168.0.4:11434"), /연결하지 못했습니다.*관리자가 허용한 경우에만/);
  assert.match(ollamaFailureMessage(generic, "http://ollama.example.com"), /연결하지 못했습니다.*https만/);
  assert.equal(ollamaFailureMessage(generic, "https://ollama.example.com"), "Ollama 서버에 연결하지 못했습니다. 주소와 방화벽을 확인해 주세요.");

  // 검증 응답(200)의 영어 원문은 화면에 나가지 않고, 서버의 다른 한국어 문구는 그대로 둡니다.
  assert.doesNotMatch(ollamaFailureMessage({ valid: false, message: "Invalid Ollama baseUrl" }, "https://a"), /[A-Za-z]{6,} [A-Za-z]{6,}/);
  const keyFormat = "API 키에 공백이나 지원하지 않는 문자가 있습니다. 키를 확인해 주세요.";
  assert.equal(ollamaFailureMessage({ valid: false, message: keyFormat }, "https://a.example.com"), keyFormat);

  for (const host of ["localhost", "127.0.0.1", "10.1.2.3", "172.16.0.1", "172.31.255.1", "192.168.1.1", "169.254.169.254", "[::1]", "[fd00::1]"]) {
    assert.equal(isLocalOrPrivateHost(host), true, host);
  }
  for (const host of ["ollama.example.com", "8.8.8.8", "172.32.0.1", "ollama"]) {
    assert.equal(isLocalOrPrivateHost(host), false, host);
  }
});

test("server validation copy is normalized to the app's terms", () => {
  const { normalizeValidationCopy } = ollamaUrl;
  assert.equal(normalizeValidationCopy("Provider에 연결하지 못했습니다.", "x"), "AI 공급자에 연결하지 못했습니다.");
  assert.equal(normalizeValidationCopy("API 키를 입력해 주세요.", "x"), "API key를 입력해 주세요.");
  assert.equal(normalizeValidationCopy("API key is required", "API key를 확인해 주세요."), "API key를 확인해 주세요.");
});

test("credential delete refusals map to a specific next step and never leak the English detail", () => {
  const { credentialDeleteErrorMessage, credentialDefaultErrorMessage, credentialStatusInfo,
    CREDENTIAL_IN_USE_MESSAGE, CREDENTIAL_DEFAULT_MESSAGE, CREDENTIAL_LAST_FOR_PROVIDER_MESSAGE } = credentialMessages;
  const conflict = (detail) => new ApiError(409, "다른 곳에서 먼저 바뀌었습니다.", { detail });
  assert.equal(credentialDeleteErrorMessage(conflict("This credential is selected by a workspace model")), CREDENTIAL_IN_USE_MESSAGE);
  assert.equal(credentialDeleteErrorMessage(conflict("Choose another default before deletion")), CREDENTIAL_DEFAULT_MESSAGE);
  assert.equal(credentialDeleteErrorMessage(conflict("This is the last active credential for a selected model provider")), CREDENTIAL_LAST_FOR_PROVIDER_MESSAGE);
  assert.match(credentialDeleteErrorMessage(conflict("Something new")), /삭제할 수 없습니다/);
  assert.equal(credentialDeleteErrorMessage(new ApiError(404, "요청한 내용을 찾지 못했습니다.", { detail: "Credential not found" })), "이미 삭제된 연결입니다.");
  assert.equal(credentialDeleteErrorMessage(new ApiError(0, "서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.")), "서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.");
  assert.equal(credentialDeleteErrorMessage(new TypeError("Failed to fetch")), "AI 연결을 삭제하지 못했습니다.");
  assert.match(credentialDefaultErrorMessage(conflict("Credential is not active")), /기본으로 지정할 수 없습니다/);
  for (const message of [CREDENTIAL_IN_USE_MESSAGE, CREDENTIAL_DEFAULT_MESSAGE, CREDENTIAL_LAST_FOR_PROVIDER_MESSAGE]) {
    assert.doesNotMatch(message, /[A-Za-z]{4,}|하세요|!/);
  }
  assert.deepEqual({ ...credentialStatusInfo("active") }, { label: "활성", tone: "success" });
  assert.equal(credentialStatusInfo("invalid").label, "확인 필요");
});

test("the create button's hint names the first unmet requirement in order", () => {
  const ready = {
    name: "제품팀", setupMode: "service", credentialsReady: true, credentialsFailed: false,
    addingConnection: true, connectionLabel: "회사 계정", duplicateLabel: false, needsBaseUrl: false,
    baseUrl: "", isConnectionValid: true, modelsLoading: false, modelsFailed: false, hasRoles: true, selectionCount: 2,
  };
  assert.equal(firstUnmetRequirement(ready), undefined);
  assert.equal(firstUnmetRequirement({ ...ready, name: "  " }), "워크스페이스 이름을 입력해 주세요.");
  // 에이전트 방식은 이름만 있으면 됩니다.
  assert.equal(firstUnmetRequirement({ ...ready, setupMode: "agent", credentialsReady: false, isConnectionValid: false, hasRoles: false, selectionCount: 0 }), undefined);
  assert.match(firstUnmetRequirement({ ...ready, credentialsReady: false, credentialsFailed: true }), /다시 시도/);
  assert.match(firstUnmetRequirement({ ...ready, credentialsReady: false }), /불러오고 있어요/);
  assert.equal(firstUnmetRequirement({ ...ready, connectionLabel: "", isConnectionValid: false }), "연결 이름을 입력해 주세요.");
  assert.equal(firstUnmetRequirement({ ...ready, duplicateLabel: true }), "다른 연결 이름을 입력해 주세요.");
  assert.equal(firstUnmetRequirement({ ...ready, needsBaseUrl: true, isConnectionValid: false }), "Ollama 서버 주소를 입력해 주세요.");
  assert.equal(firstUnmetRequirement({ ...ready, needsBaseUrl: true, baseUrl: "https://a", isConnectionValid: false }), "Ollama 서버 연결 확인이 끝나야 합니다.");
  assert.equal(firstUnmetRequirement({ ...ready, isConnectionValid: false }), "API key 확인이 끝나야 합니다.");
  assert.equal(firstUnmetRequirement({ ...ready, addingConnection: false, connectionLabel: "", isConnectionValid: false }), "AI 연결을 골라 주세요.");
  assert.match(firstUnmetRequirement({ ...ready, modelsLoading: true, hasRoles: false, selectionCount: 0 }), /모델 목록을 불러오고 있어요/);
  assert.match(firstUnmetRequirement({ ...ready, modelsFailed: true, hasRoles: false, selectionCount: 0 }), /다시 시도/);
  assert.match(firstUnmetRequirement({ ...ready, selectionCount: 0 }), /쓸 수 있는 모델이 없습니다/);
});

function loadMockApi() {
  return load("../src/lib/api/mock/index.ts", {
    "../client": { ApiError },
    "../config": { MOCK_LATENCY_MS: 0 },
    "../providers": load("../src/lib/api/providers.ts"),
    "./fixtures": load("../src/lib/api/mock/fixtures.ts"),
  }).mockApi;
}

const openAiKey = "sk-test-0123456789abcdefghij";

test("mock: choosing a default moves the single default flag", async () => {
  const api = loadMockApi();
  const added = await api.createAccountCredential({ provider: "openai", label: "회사", apiKey: openAiKey });
  await api.setDefaultAccountCredential("demo-credential");
  let list = await api.listAccountCredentials();
  const defaultIds = (items) => items.filter((item) => item.isDefault).map((item) => item.id).join(",");
  assert.equal(defaultIds(list), "demo-credential");
  const chosen = await api.setDefaultAccountCredential(added.id);
  assert.equal(chosen.isDefault, true);
  list = await api.listAccountCredentials();
  assert.equal(defaultIds(list), added.id);
  await assert.rejects(api.setDefaultAccountCredential("missing"), (error) => error.status === 404);
});

test("mock: delete follows the backend's refusal rules and removes the row otherwise", async () => {
  const api = loadMockApi();
  const { credentialDeleteErrorMessage, CREDENTIAL_DEFAULT_MESSAGE, CREDENTIAL_IN_USE_MESSAGE, CREDENTIAL_LAST_FOR_PROVIDER_MESSAGE } = credentialMessages;
  const spare = await api.createAccountCredential({ provider: "openai", label: "예비", apiKey: openAiKey });
  const second = await api.createAccountCredential({ provider: "openai", label: "회사", apiKey: openAiKey });

  // 방금 추가한 연결이 기본입니다. 다른 연결이 남아 있으면 기본 연결은 지울 수 없습니다.
  await assert.rejects(api.deleteAccountCredential(second.id), (error) =>
    error.status === 409 && credentialDeleteErrorMessage(error) === CREDENTIAL_DEFAULT_MESSAGE);

  // demo 워크스페이스가 anthropic 모델을 쓰고 있고, anthropic 연결은 하나뿐입니다.
  await assert.rejects(api.deleteAccountCredential("demo-credential"), (error) =>
    error.status === 409 && credentialDeleteErrorMessage(error) === CREDENTIAL_LAST_FOR_PROVIDER_MESSAGE);

  // 워크스페이스 모델이 직접 가리키는 연결은 지울 수 없습니다.
  const workspace = await api.createWorkspace({
    name: "삭제 규칙",
    credentialId: spare.id,
    models: { answer: { provider: "openai", model: "gpt-4o-mini", credentialId: spare.id } },
  });
  assert.ok(workspace.id);
  await assert.rejects(api.deleteAccountCredential(spare.id), (error) =>
    error.status === 409 && credentialDeleteErrorMessage(error) === CREDENTIAL_IN_USE_MESSAGE);

  // 기본이 아니고 쓰이지 않는 연결은 지워집니다.
  const unused = await api.createAccountCredential({ provider: "openai", label: "임시", apiKey: openAiKey });
  await api.setDefaultAccountCredential(second.id);
  assert.equal(await api.deleteAccountCredential(unused.id), undefined);
  const list = await api.listAccountCredentials();
  assert.equal(list.some((item) => item.id === unused.id), false);
  await assert.rejects(api.deleteAccountCredential(unused.id), (error) => error.status === 404);
});

import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

import * as errorMessage from "../src/lib/api/error-message.ts";
import * as askTurns from "../src/features/ask/lib/ask-turns.ts";

class ApiError extends Error {
  constructor(status, message, kind) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.kind = kind;
  }
}

/** 상태가 바뀔 때마다 훅을 다시 돌려 최신 반환값을 보는 최소한의 React 대역입니다. */
function mountUseAsk(api, { storage = new Map(), workspaceId = "ws-1" } = {}) {
  let cursor = 0;
  let mounted = false;
  const slots = [];
  const effects = [];
  const sameDeps = (a, b) =>
    a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!mounted) slots[index] = initial;
      return [
        slots[index],
        (value) => {
          slots[index] = typeof value === "function" ? value(slots[index]) : value;
        },
      ];
    },
    useRef(initial) {
      const index = cursor++;
      if (!mounted) slots[index] = { current: initial };
      return slots[index];
    },
    useCallback: (fn) => fn,
    useEffect(fn, deps) {
      const index = cursor++;
      if (!sameDeps(slots[index], deps)) effects.push(fn);
      slots[index] = deps;
    },
  };
  const sessionStorage = {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: (key) => storage.delete(key),
  };
  const modules = {
    react,
    "@/lib/api": { ApiError },
    "@/lib/api/context": { useApi: () => api },
    "@/lib/api/error-message": errorMessage,
    "../lib/ask-turns": askTurns,
  };
  const exports = {};
  const code = ts.transpileModule(
    fs.readFileSync(new URL("../src/features/ask/hooks/use-ask.ts", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } },
  ).outputText;
  vm.runInNewContext(code, {
    exports,
    require: (name) => {
      if (!(name in modules)) throw new Error(`unstubbed module: ${name}`);
      return modules[name];
    },
    window: { sessionStorage },
    AbortController,
    DOMException,
    Date,
  });

  const render = () => {
    // 효과가 상태를 바꾸면 한 번 더 그려 React처럼 안정된 값을 돌려줍니다.
    let value;
    for (let pass = 0; pass < 5; pass++) {
      cursor = 0;
      value = exports.useAsk(workspaceId);
      mounted = true;
      if (effects.length === 0) break;
      effects.splice(0).forEach((fn) => fn());
    }
    return value;
  };
  return { render, storage };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));
const plain = (value) => JSON.parse(JSON.stringify(value));

function scriptedApi(scripts) {
  const calls = [];
  return {
    calls,
    async *ask(workspaceId, question, signal) {
      calls.push({ workspaceId, question });
      const script = scripts.shift();
      for (const step of script) {
        if (step instanceof Error) throw step;
        if (step === "wait-for-abort") {
          // 실제 apiStream처럼, 중단되면 예외 없이 조용히 끝납니다.
          await new Promise((resolve) => signal.addEventListener("abort", resolve, { once: true }));
          return;
        }
        yield step;
      }
    },
  };
}

test("a stream that ends without done becomes a retryable error and keeps the partial text", async () => {
  const api = scriptedApi([[{ type: "token", text: "받은 데까지" }]]);
  const hook = mountUseAsk(api);
  await hook.render().ask("왜 바꿨나요?");

  const { turns, isStreaming } = hook.render();
  assert.equal(isStreaming, false);
  assert.equal(turns.length, 1);
  assert.equal(turns[0].status, "error");
  assert.equal(turns[0].errorMessage, "연결이 끊겼습니다. 다시 시도해 주세요.");
  assert.equal(turns[0].answer, "받은 데까지");
});

test("stopping ends the turn as aborted even though the stream ends silently", async () => {
  const api = scriptedApi([[{ type: "token", text: "쓰던 " }, "wait-for-abort"]]);
  const hook = mountUseAsk(api);
  const pending = hook.render().ask("질문");
  await tick();
  assert.equal(hook.render().isStreaming, true);
  hook.render().stop();
  await pending;

  const { turns, isStreaming } = hook.render();
  assert.equal(isStreaming, false);
  assert.equal(turns[0].status, "aborted");
  assert.equal(turns[0].answer, "쓰던 ");
});

test("retry replaces the failed turn instead of stacking the same question", async () => {
  const api = scriptedApi([
    [{ type: "error", message: "답변을 만드는 중 문제가 생겼습니다." }],
    [{ type: "token", text: "답[1]" }, { type: "done" }],
  ]);
  const hook = mountUseAsk(api);
  await hook.render().ask("  같은 질문  ");
  const failed = hook.render().turns[0];
  assert.equal(failed.status, "error");

  hook.render().retry(failed.id);
  await tick();
  await tick();

  const { turns } = hook.render();
  assert.equal(turns.length, 1);
  assert.notEqual(turns[0].id, failed.id);
  assert.equal(turns[0].question, "같은 질문");
  assert.equal(turns[0].status, "done");
  assert.deepEqual(
    api.calls.map((call) => call.question),
    ["같은 질문", "같은 질문"],
  );
});

test("no evidence is not an error, and a missing model points at settings", async () => {
  const api = scriptedApi([
    [{ type: "error", message: "서버 문구", code: "no_evidence" }],
    [new ApiError(422, "선택한 모델을 제공하는 API key가 없습니다.", "invalid")],
    [new ApiError(500, "서버에 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.", "server")],
    [new TypeError("Failed to fetch")],
  ]);
  const hook = mountUseAsk(api);
  for (const question of ["하나", "둘", "셋", "넷"]) await hook.render().ask(question);

  const [none, model, server, unknown] = hook.render().turns;
  assert.equal(none.status, "no_evidence");
  assert.equal(model.status, "error");
  assert.equal(model.errorAction, "settings");
  assert.equal(model.errorMessage, "선택한 모델을 제공하는 API key가 없습니다.");
  assert.equal(server.errorAction, undefined);
  // 영어 원문은 화면에 내보내지 않습니다.
  assert.equal(unknown.errorMessage, "답변을 받지 못했습니다.");
});

test("finished turns survive a remount, and clear can be undone", async () => {
  const api = scriptedApi([[{ type: "token", text: "답" }, { type: "done" }]]);
  const first = mountUseAsk(api);
  await first.render().ask("기억할 질문");
  first.render();

  const second = mountUseAsk(scriptedApi([]), { storage: first.storage });
  const restored = second.render();
  assert.equal(restored.isRestored, true);
  assert.equal(restored.turns.length, 1);
  assert.equal(restored.turns[0].question, "기억할 질문");
  assert.equal(restored.turns[0].status, "done");

  const removed = second.render().clear();
  assert.equal(second.render().turns.length, 0);
  assert.equal(second.storage.size, 0);

  second.render().restore(removed);
  assert.deepEqual(plain(second.render().turns), plain(removed));
  assert.equal(second.storage.size, 1);

  // 다른 워크스페이스에는 보이지 않습니다.
  const other = mountUseAsk(scriptedApi([]), { storage: first.storage, workspaceId: "ws-2" });
  assert.equal(other.render().turns.length, 0);
});

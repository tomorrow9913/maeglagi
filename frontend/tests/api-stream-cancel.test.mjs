import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

import { parseSseFrames } from "../src/lib/api/sse.ts";

test("Ask finishes after done even when cancelling the SSE body never resolves", async () => {
  const exports = {};
  const modules = {
    "./config": { API_BASE_URL: "https://example.invalid" },
    "../supabase/config": { isSupabaseConfigured: false },
    "../supabase/client": {},
    "./sse": { parseSseFrames },
    "./error-message": {
      errorKindForStatus: () => "server",
      messageForKind: () => "오류",
      parseRetryAfter: () => undefined,
      userMessageForResponse: () => "오류",
    },
  };
  const code = ts.transpileModule(
    fs.readFileSync(new URL("../src/lib/api/client.ts", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } },
  ).outputText;
  vm.runInNewContext(code, {
    exports,
    require: (name) => modules[name],
    fetch: async () => new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode('data: {"type":"done"}\n\n'));
        },
        cancel() { return new Promise(() => {}); },
      }),
      { status: 200, headers: { "Content-Type": "text/event-stream" } },
    ),
    AbortController,
    DOMException,
    TextDecoderStream,
    setTimeout,
    clearTimeout,
  });

  const events = [];
  await Promise.race([
    (async () => {
      for await (const event of exports.apiStream("/ask", { method: "POST" })) {
        events.push(event);
        if (event.type === "done") break;
      }
    })(),
    new Promise((_, reject) => setTimeout(() => reject(new Error("stream stayed busy")), 500)),
  ]);
  assert.deepEqual(JSON.parse(JSON.stringify(events)), [{ type: "done" }]);
});

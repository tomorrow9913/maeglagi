import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

import { safeNextPath } from "../src/lib/auth-redirect.ts";

const source = readFileSync(new URL("../src/app/auth/callback/route.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function callback(exchangeError = null) {
  const loaded = { exports: {} };
  let exchangedCode;
  const mocks = {
    "next/server": { NextResponse: { redirect: (url) => url } },
    "@/lib/supabase/server": {
      createClient: async () => ({
        auth: {
          exchangeCodeForSession: async (code) => {
            exchangedCode = code;
            return { error: exchangeError };
          },
        },
      }),
    },
    "@/lib/auth-redirect": { safeNextPath },
  };
  new Function("require", "module", "exports", compiled)(
    (name) => mocks[name],
    loaded,
    loaded.exports,
  );
  return { GET: loaded.exports.GET, exchangedCode: () => exchangedCode };
}

test("callback exchanges code and returns only to a safe local destination", async () => {
  const handler = callback();
  const result = await handler.GET(
    new Request("https://app.example/auth/callback?code=abc&next=%2Fworkspaces%2F123"),
  );
  assert.equal(result.href, "https://app.example/workspaces/123");
  assert.equal(handler.exchangedCode(), "abc");

  const unsafe = await handler.GET(
    new Request("https://app.example/auth/callback?code=def&next=%2F%5Cevil.example"),
  );
  assert.equal(unsafe.href, "https://app.example/workspaces");
});

test("callback errors return to login with feedback and preserve safe next", async () => {
  const handler = callback(new Error("exchange failed"));
  const failed = await handler.GET(
    new Request("https://app.example/auth/callback?code=abc&next=%2Fworkspaces%2F123"),
  );
  assert.equal(failed.href, "https://app.example/login?error=callback&next=%2Fworkspaces%2F123");

  const denied = await handler.GET(
    new Request("https://app.example/auth/callback?error=access_denied&next=%2F%5Cevil.example"),
  );
  assert.equal(denied.href, "https://app.example/login?error=callback");
});

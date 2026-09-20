import assert from "node:assert/strict";
import test from "node:test";

import {
  authCallbackUrl,
  kakaoIdentityLinkOptions,
  kakaoOAuthOptions,
  safeNextPath,
} from "../src/lib/auth-redirect.ts";

test("auth next accepts local paths and rejects external or ambiguous destinations", () => {
  assert.equal(
    safeNextPath("/workspaces/123/sources?view=all"),
    "/workspaces/123/sources?view=all",
  );
  for (const value of [
    null,
    "",
    "https://evil.example",
    "//evil.example",
    "/\\evil.example",
    "/%5cevil.example",
    "/%255cevil.example",
    "/%2fevil.example",
    "/%252fevil.example",
    "/some%0apath",
    "/bad%",
    "\\evil.example",
  ]) {
    assert.equal(safeNextPath(value), "/workspaces", String(value));
  }
});

test("OAuth callback keeps a valid next path as a query parameter", () => {
  const url = new URL(
    authCallbackUrl("https://app.example", safeNextPath("/workspaces/123?tab=a&b=1")),
  );
  assert.equal(url.origin, "https://app.example");
  assert.equal(url.pathname, "/auth/callback");
  assert.equal(url.searchParams.get("next"), "/workspaces/123?tab=a&b=1");
  assert.equal(
    new URL(authCallbackUrl("https://app.example", safeNextPath("//evil.example"))).search,
    "",
  );
});

test("Kakao OAuth overrides Supabase's email scope default", () => {
  const config = kakaoOAuthOptions("https://app.example", "/workspaces");
  assert.equal(config.provider, "kakao");
  assert.equal(config.options.queryParams.scope, "profile_nickname profile_image");
  assert.equal(config.options.redirectTo, "https://app.example/auth/callback");
  assert.equal("scopes" in config.options, false);
  assert.equal(JSON.stringify(config).includes("account_email"), false);
});

test("Kakao identity linking returns to the authenticated account page", () => {
  const config = kakaoIdentityLinkOptions("https://app.example");
  assert.equal(config.provider, "kakao");
  assert.equal(config.options.queryParams.scope, "profile_nickname profile_image");
  assert.equal(
    config.options.redirectTo,
    "https://app.example/auth/callback?next=%2Faccount%2Fsecurity&intent=link",
  );
});

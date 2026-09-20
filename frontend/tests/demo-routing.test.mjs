import assert from "node:assert/strict";
import test from "node:test";

import {
  demoPath,
  isDemoPath,
  requiresWorkspaceAuth,
  selectRouteApi,
} from "../src/lib/demo-routing.ts";

test("public demo paths stay in the seeded route", () => {
  assert.equal(demoPath(), "/demo");
  for (const section of ["ask", "sources", "timeline", "graph", "settings"]) {
    assert.equal(demoPath(section), `/demo/${section}`);
    assert.equal(isDemoPath(demoPath(section)), true);
    assert.equal(requiresWorkspaceAuth(demoPath(section)), false);
  }
  assert.equal(isDemoPath("/demography"), false);
  assert.equal(isDemoPath("/demo-foo"), false);
});

test("live mode keeps real workspace API and auth separate from demo API", () => {
  const httpApi = { name: "http" };
  const seededApi = { name: "seeded" };
  assert.equal(selectRouteApi(false, httpApi, seededApi), httpApi);
  assert.equal(selectRouteApi(true, httpApi, seededApi), seededApi);
  assert.equal(requiresWorkspaceAuth("/workspaces"), true);
  assert.equal(requiresWorkspaceAuth("/workspaces/real-id/ask"), true);
  assert.equal(requiresWorkspaceAuth("/account/mcp"), true);
  assert.equal(requiresWorkspaceAuth("/workspaces-demo"), false);
});

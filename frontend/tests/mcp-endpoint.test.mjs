import assert from "node:assert/strict";
import test from "node:test";

import { mcpEndpointUrl } from "../src/lib/api/config.ts";

test("MCP endpoint uses the configured API origin beside /api/v1", () => {
  assert.equal(mcpEndpointUrl("https://api.example.com/api/v1"), "https://api.example.com/mcp");
  assert.equal(mcpEndpointUrl("https://example.com/service/api/v1/"), "https://example.com/service/mcp");
});

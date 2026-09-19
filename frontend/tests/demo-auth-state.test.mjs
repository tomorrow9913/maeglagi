import assert from "node:assert/strict";
import test from "node:test";

import { watchDemoAuthState } from "../src/lib/demo-auth-state.ts";

function authHarness() {
  let resolveSession;
  let rejectSession;
  let listener;
  let unsubscribed = false;
  const session = new Promise((resolve, reject) => {
    resolveSession = resolve;
    rejectSession = reject;
  });
  return {
    auth: {
      getSession: () => session,
      onAuthStateChange(callback) {
        listener = callback;
        return { data: { subscription: { unsubscribe: () => { unsubscribed = true; } } } };
      },
    },
    resolve: (user) => resolveSession({ data: { session: user ? { user } : null } }),
    reject: () => rejectSession(new Error("session lookup failed")),
    emit: (user) => listener("SIGNED_IN", user ? { user } : null),
    get unsubscribed() { return unsubscribed; },
  };
}

test("starts loading, then resolves a signed-in browser session", async () => {
  const harness = authHarness();
  const states = [];
  const stop = watchDemoAuthState(harness.auth, (state) => states.push(state));
  assert.deepEqual(states, ["loading"]);
  harness.resolve({ id: "person" });
  await Promise.resolve();
  assert.deepEqual(states, ["loading", "signed-in"]);
  stop();
});

test("reacts to sign-in and sign-out after a signed-out session", async () => {
  const harness = authHarness();
  const states = [];
  const stop = watchDemoAuthState(harness.auth, (state) => states.push(state));
  harness.resolve(null);
  await Promise.resolve();
  harness.emit({ id: "person" });
  harness.emit(null);
  assert.deepEqual(states, ["loading", "signed-out", "signed-in", "signed-out"]);
  stop();
  assert.equal(harness.unsubscribed, true);
});

test("an auth event wins over a stale getSession result", async () => {
  const harness = authHarness();
  const states = [];
  const stop = watchDemoAuthState(harness.auth, (state) => states.push(state));
  harness.emit({ id: "person" });
  harness.resolve(null);
  await Promise.resolve();
  assert.deepEqual(states, ["loading", "signed-in"]);
  stop();
});

test("session errors settle as signed-out and cleanup prevents later updates", async () => {
  const harness = authHarness();
  const states = [];
  const stop = watchDemoAuthState(harness.auth, (state) => states.push(state));
  harness.reject();
  await Promise.resolve();
  assert.deepEqual(states, ["loading", "signed-out"]);
  stop();
  harness.emit({ id: "person" });
  assert.deepEqual(states, ["loading", "signed-out"]);
});

import assert from "node:assert/strict";
import test from "node:test";

import { registerNavigationGuard, shouldInterceptNavigation } from "../src/lib/navigation-guard.ts";

const current = "https://app.example.com/workspaces/w1/sources?tab=meeting";
const click = (overrides = {}) => ({ button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false, defaultPrevented: false, ...overrides });
const anchor = (href, overrides = {}) => ({ href, target: null, download: false, ...overrides });

test("plain clicks on same-origin links to another screen are intercepted", () => {
  assert.equal(shouldInterceptNavigation(click(), anchor("/workspaces/w1/ask"), current), true);
  assert.equal(shouldInterceptNavigation(click(), anchor("https://app.example.com/account/mcp"), current), true);
  assert.equal(shouldInterceptNavigation(click(), anchor("timeline"), current), true);
  assert.equal(shouldInterceptNavigation(click(), anchor("/workspaces/w1/sources?source=s1"), current), true, "a different query is a different screen state");
  assert.equal(shouldInterceptNavigation(click(), anchor("/workspaces/w1/ask", { target: "_self" }), current), true);
});

test("clicks that do not leave the current screen are ignored", () => {
  for (const modifier of ["metaKey", "ctrlKey", "shiftKey", "altKey"]) {
    assert.equal(shouldInterceptNavigation(click({ [modifier]: true }), anchor("/workspaces/w1/ask"), current), false, modifier);
  }
  assert.equal(shouldInterceptNavigation(click({ button: 1 }), anchor("/workspaces/w1/ask"), current), false);
  assert.equal(shouldInterceptNavigation(click({ defaultPrevented: true }), anchor("/workspaces/w1/ask"), current), false);
  assert.equal(shouldInterceptNavigation(click(), anchor("/workspaces/w1/ask", { target: "_blank" }), current), false);
  assert.equal(shouldInterceptNavigation(click(), anchor("/files/export.md", { download: true }), current), false);
  assert.equal(shouldInterceptNavigation(click(), anchor("#transcript"), current), false);
  assert.equal(shouldInterceptNavigation(click(), anchor("/workspaces/w1/sources?tab=meeting#transcript"), current), false);
  assert.equal(shouldInterceptNavigation(click(), anchor(current), current), false);
  assert.equal(shouldInterceptNavigation(click(), anchor(null), current), false);
  assert.equal(shouldInterceptNavigation(click(), anchor(""), current), false);
});

test("other origins and non-http schemes are left to the browser", () => {
  assert.equal(shouldInterceptNavigation(click(), anchor("https://example.org/docs"), current), false);
  assert.equal(shouldInterceptNavigation(click(), anchor("mailto:team@example.com"), current), false);
  assert.equal(shouldInterceptNavigation(click(), anchor("blob:https://app.example.com/1234"), current), false);
  assert.equal(shouldInterceptNavigation(click(), anchor("http://[bad"), current), false);
});

function fakeDom(confirmResult) {
  const listeners = [];
  const asked = [];
  class FakeElement {
    constructor(anchorAttributes) { this.anchorAttributes = anchorAttributes; }
    closest() {
      const attributes = this.anchorAttributes;
      return attributes ? { getAttribute: (name) => attributes[name] ?? null, hasAttribute: (name) => name in attributes } : null;
    }
  }
  globalThis.Element = FakeElement;
  globalThis.document = {
    addEventListener(type, handler, capture) { listeners.push({ type, handler, capture }); },
    removeEventListener(type, handler) { const index = listeners.findIndex((item) => item.type === type && item.handler === handler); if (index >= 0) listeners.splice(index, 1); },
  };
  globalThis.window = { location: { href: current }, confirm(message) { asked.push(message); return confirmResult; } };
  const dispatch = (attributes) => {
    const event = { ...click(), target: new FakeElement(attributes), prevented: false, stopped: false, preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; } };
    for (const item of [...listeners]) item.handler(event);
    return event;
  };
  return { listeners, asked, dispatch, restore() { delete globalThis.Element; delete globalThis.document; delete globalThis.window; } };
}

test("a registered guard asks once per click, blocks on cancel, and detaches when released", () => {
  const dom = fakeDom(false);
  try {
    const release = registerNavigationGuard("이동할까요?");
    assert.equal(dom.listeners.length, 1);
    assert.equal(dom.listeners[0].type, "click");
    assert.equal(dom.listeners[0].capture, true);
    const second = registerNavigationGuard("두 번째 문구");
    assert.equal(dom.listeners.length, 1, "one document listener serves every guard");

    const blocked = dom.dispatch({ href: "/workspaces/w1/ask" });
    assert.deepEqual(dom.asked, ["두 번째 문구"]);
    assert.equal(blocked.prevented, true);
    assert.equal(blocked.stopped, true);

    const ignored = dom.dispatch({ href: "/workspaces/w1/ask", target: "_blank" });
    assert.equal(dom.asked.length, 1);
    assert.equal(ignored.prevented, false);
    assert.equal(dom.dispatch(undefined).prevented, false, "clicks outside links are untouched");

    second();
    dom.dispatch({ href: "/workspaces/w1/ask" });
    assert.equal(dom.asked.at(-1), "이동할까요?");
    release();
    assert.equal(dom.listeners.length, 0);
    release();
    assert.equal(dom.listeners.length, 0);
  } finally { dom.restore(); }
});

test("confirming lets the navigation continue", () => {
  const dom = fakeDom(true);
  try {
    const release = registerNavigationGuard("이동할까요?");
    const event = dom.dispatch({ href: "/workspaces/w1/ask" });
    assert.equal(dom.asked.length, 1);
    assert.equal(event.prevented, false);
    assert.equal(event.stopped, false);
    release();
  } finally { dom.restore(); }
});

import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import vm from "node:vm";


function loadTracker() {
  const filename = new URL("./analytics.js", import.meta.url);
  assert.equal(existsSync(filename), true, "analytics.js must exist");
  const module = { exports: {} };
  vm.runInNewContext(readFileSync(filename, "utf8"), { module, exports: module.exports, globalThis: {} });
  assert.equal(typeof module.exports.createAnalyticsTracker, "function");
  return module.exports.createAnalyticsTracker;
}


test("tracker reports one session and only counts visible time", async () => {
  const createAnalyticsTracker = loadTracker();
  const requests = [];
  const listeners = {};
  let intervalCallback;
  let now = 0;
  let visible = true;

  const tracker = createAnalyticsTracker({
    now: () => now,
    isVisible: () => visible,
    randomUUID: () => "session-0000000001",
    fetch: async (url, options) => requests.push({ url, options }),
    sendBeacon: () => true,
    addEventListener: (name, callback) => { listeners[name] = callback; },
    setInterval: (callback) => { intervalCallback = callback; },
  });

  tracker.start();
  await Promise.resolve();
  assert.equal(requests.length, 1);
  assert.deepEqual(JSON.parse(requests[0].options.body), {
    session_id: "session-0000000001",
    active_seconds: 0,
  });

  now = 15_000;
  intervalCallback();
  await Promise.resolve();
  assert.equal(JSON.parse(requests[1].options.body).active_seconds, 15);

  visible = false;
  listeners.visibilitychange();
  now = 30_000;
  intervalCallback();
  await Promise.resolve();
  assert.equal(JSON.parse(requests.at(-1).options.body).active_seconds, 15);
});


test("admin hidden states stay out of the layout", () => {
  const css = readFileSync(new URL("./admin.css", import.meta.url), "utf8");
  assert.match(css, /\[hidden\]\s*\{[^}]*display:\s*none\s*!important/);
});

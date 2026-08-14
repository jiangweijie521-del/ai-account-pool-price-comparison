"use strict";

(function analyticsModule() {
  function browserEnvironment() {
    return {
      now: () => Date.now(),
      isVisible: () => document.visibilityState === "visible",
      randomUUID: () => globalThis.crypto?.randomUUID?.() || `session-${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`,
      fetch: globalThis.fetch.bind(globalThis),
      sendBeacon: (url, body) => navigator.sendBeacon(url, new Blob([body], { type: "application/json" })),
      addEventListener: globalThis.addEventListener.bind(globalThis),
      setInterval: globalThis.setInterval.bind(globalThis),
    };
  }

  function createAnalyticsTracker(overrides = {}) {
    const environment = Object.assign(
      typeof window === "undefined" ? {} : browserEnvironment(),
      overrides,
    );
    const sessionId = environment.randomUUID();
    let activeSeconds = 0;
    let visibleSince = environment.isVisible() ? environment.now() : null;
    let started = false;

    function updateVisibleTime() {
      if (visibleSince === null) return;
      const current = environment.now();
      activeSeconds += Math.max(0, Math.floor((current - visibleSince) / 1000));
      visibleSince = current;
    }

    function body() {
      return JSON.stringify({ session_id: sessionId, active_seconds: activeSeconds });
    }

    function report(useBeacon = false) {
      updateVisibleTime();
      const payload = body();
      if (useBeacon && environment.sendBeacon("/api/analytics/session", payload)) return;
      Promise.resolve(environment.fetch("/api/analytics/session", {
        method: "POST",
        cache: "no-store",
        keepalive: true,
        headers: { "Content-Type": "application/json" },
        body: payload,
      })).catch(() => {});
    }

    function handleVisibilityChange() {
      updateVisibleTime();
      const visible = environment.isVisible();
      visibleSince = visible ? environment.now() : null;
      if (visible) report(false);
    }

    function start() {
      if (started) return;
      started = true;
      report(false);
      environment.setInterval(() => {
        if (environment.isVisible()) report(false);
      }, 15_000);
      environment.addEventListener("visibilitychange", handleVisibilityChange);
      environment.addEventListener("pagehide", () => report(true));
    }

    return { start };
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { createAnalyticsTracker };
  } else {
    createAnalyticsTracker().start();
  }
})();

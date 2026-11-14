// Runs only on Aura's /aura/companion/connect page. Passes the scoped token from the signed-in page to the extension.
// Reuses the January Aura extension's bridge pattern: same window, same origin, typed messages only.
(function () {
  window.addEventListener("message", (event) => {
    if (event.source !== window || event.origin !== window.location.origin) return;
    const data = event.data || {};
    if (data.type === "AURA_EXTENSION_PING") window.postMessage({ type: "AURA_EXTENSION_READY" }, window.location.origin);
    if (data.type !== "AURA_EXTENSION_TOKEN" || typeof data.token !== "string") return;
    chrome.runtime.sendMessage({ type: "connect", token: data.token, expiresAt: data.expiresAt, email: data.email }, (reply) => {
      if (reply && reply.ok) window.postMessage({ type: "AURA_EXTENSION_CONNECTED", email: reply.email }, window.location.origin);
    });
  });
  window.postMessage({ type: "AURA_EXTENSION_READY" }, window.location.origin);
})();

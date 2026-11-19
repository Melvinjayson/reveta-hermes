/* Aura Companion service worker: settings, the local context trail, per-site opt-in and the connection token.
 * It never calls a model and does no work on a timer; model calls happen only when the person taps in the side panel. */
importScripts("config.js", "lib/redact.js", "lib/policy.js");

const RETENTION_MS = { "1h": 3600e3, "1d": 86400e3, "7d": 7 * 86400e3 };
const DEFAULTS = { paused: false, optedIn: [], unblocked: [], retention: "1d", auraOrigin: globalThis.AURA_ORIGINS[0] };
const MAX_TRAIL = 50;
const CAPTURE_FILES = ["lib/redact.js", "lib/policy.js", "lib/takeover.js", "capture.js"];

async function getSettings() {
  const { settings } = await chrome.storage.local.get("settings");
  return { ...DEFAULTS, ...(settings || {}) };
}
async function saveSettings(patch) {
  const next = { ...(await getSettings()), ...patch };
  await chrome.storage.local.set({ settings: next });
  return next;
}

/** Drops entries older than the retention window. Runs whenever the trail is read or written, never on a timer. */
async function getTrail() {
  const [{ trail }, s] = await Promise.all([chrome.storage.local.get("trail"), getSettings()]);
  const cutoff = Date.now() - (RETENTION_MS[s.retention] || RETENTION_MS["1d"]);
  const kept = (trail || []).filter((entry) => Date.parse(entry.at) >= cutoff);
  if (kept.length !== (trail || []).length) await chrome.storage.local.set({ trail: kept });
  return kept;
}

async function capture(page, tabUrl) {
  const s = await getSettings();
  const decision = AuraPolicy.siteDecision(tabUrl, s);
  if (!decision.allowed) return { ok: false, reason: decision.reason };
  const url = AuraRedact.cleanUrl(tabUrl);
  const entry = {
    id: crypto.randomUUID(), host: decision.host, url,
    title: AuraRedact.redactText(String(page.title || "").slice(0, 200)).text,
    excerpt: AuraRedact.redactText(String(page.excerpt || "").slice(0, 4000)).text,
    at: new Date().toISOString(),
  };
  const trail = (await getTrail()).filter((e) => e.url !== url);
  await chrome.storage.local.set({ trail: [entry, ...trail].slice(0, MAX_TRAIL) });
  return { ok: true };
}

/** Keeps one dynamic content script whose matches are exactly the opted-in, still-permitted hosts. */
async function syncCaptureScript() {
  const s = await getSettings();
  const hosts = s.optedIn.filter((h) => !AuraPolicy.denyCategory(h, s.unblocked));
  const matches = hosts.flatMap((h) => [`https://${h}/*`, `http://${h}/*`]);
  const granted = [];
  for (const m of matches) if (await chrome.permissions.contains({ origins: [m] })) granted.push(m);
  const existing = await chrome.scripting.getRegisteredContentScripts({ ids: ["aura-capture"] });
  if (existing.length) await chrome.scripting.unregisterContentScripts({ ids: ["aura-capture"] });
  if (granted.length) {
    await chrome.scripting.registerContentScripts([{ id: "aura-capture", matches: granted, js: CAPTURE_FILES, runAt: "document_idle", persistAcrossSessions: true }]);
  }
}

async function optIn(host, tabId) {
  const s = await getSettings();
  if (AuraPolicy.denyCategory(host, s.unblocked)) return { ok: false, reason: "denied" };
  if (!s.optedIn.includes(host)) await saveSettings({ optedIn: [...s.optedIn, host] });
  await syncCaptureScript();
  if (tabId) await chrome.scripting.executeScript({ target: { tabId }, files: CAPTURE_FILES }).catch(() => {});
  return { ok: true };
}

async function optOut(host) {
  const s = await getSettings();
  await saveSettings({ optedIn: s.optedIn.filter((h) => h !== host) });
  await chrome.permissions.remove({ origins: [`https://${host}/*`, `http://${host}/*`] }).catch(() => {});
  await syncCaptureScript();
  await chrome.storage.local.set({ trail: (await getTrail()).filter((e) => e.host !== host) });
  return { ok: true };
}

// Server-side take-over gate (hermes_cli/web_routers/aura_companion_actions.py). Every step is asked for and
// reported; approve/deny come only from the side panel. Any failure reads as "not granted".
const GATE_PATHS = { action: "/api/aura/companion/action", result: "/api/aura/companion/action/result",
  approve: "/api/aura/companion/action/approve", deny: "/api/aura/companion/action/deny" };
async function gate(op, body, sender) {
  const fromPanel = sender.id === chrome.runtime.id && sender.url && sender.url.startsWith(chrome.runtime.getURL(""));
  if (!GATE_PATHS[op] || ((op === "approve" || op === "deny") && !fromPanel)) return { ok: false, error: "Not allowed." };
  const { auth } = await chrome.storage.session.get("auth");
  if (!auth) return { ok: false, error: "Connect to Aura first." };
  const s = await getSettings();
  try {
    const response = await fetch(`${s.auraOrigin}${GATE_PATHS[op]}`, { method: "POST", credentials: "omit",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${auth.token}` }, body: JSON.stringify(body) });
    const data = await response.json().catch(() => ({}));
    return response.ok ? { ok: true, ...data } : { ok: false, error: data.error || `Aura returned ${response.status}.` };
  } catch { return { ok: false, error: "Couldn't reach Aura, so the step was not run." }; }
}

async function handle(message, sender) {
  switch (message.type) {
    case "connect": {
      // Only Aura's own connect page (bridge.js) may hand over a token.
      const s = await getSettings();
      const from = sender.url ? new URL(sender.url) : null;
      if (!from || from.origin !== s.auraOrigin || from.pathname !== "/aura/companion/connect") return { ok: false };
      if (!/^aura_ext\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(message.token)) return { ok: false };
      await chrome.storage.session.set({ auth: { token: message.token, expiresAt: String(message.expiresAt || ""), email: String(message.email || "") } });
      return { ok: true, email: message.email };
    }
    case "capture": return sender.tab ? capture(message.page || {}, sender.tab.url) : { ok: false };
    case "site-status": {
      const s = await getSettings();
      return { decision: AuraPolicy.siteDecision(sender.tab ? sender.tab.url : message.url, s), paused: s.paused };
    }
    case "set-paused": await saveSettings({ paused: Boolean(message.value) }); return { ok: true };
    case "opt-in": return optIn(String(message.host || ""), message.tabId);
    case "opt-out": return optOut(String(message.host || ""));
    case "unblock": {
      const s = await getSettings();
      if (!s.unblocked.includes(message.entry)) await saveSettings({ unblocked: [...s.unblocked, String(message.entry)] });
      return { ok: true };
    }
    case "set-retention": if (RETENTION_MS[message.value]) await saveSettings({ retention: message.value }); await getTrail(); return { ok: true };
    case "set-origin": if (globalThis.AURA_ORIGINS.includes(message.value)) { await saveSettings({ auraOrigin: message.value }); await chrome.storage.session.remove("auth"); } return { ok: true };
    case "delete-entry": await chrome.storage.local.set({ trail: (await getTrail()).filter((e) => e.id !== message.id) }); return { ok: true };
    case "delete-all": await chrome.storage.local.remove("trail"); return { ok: true };
    case "gate": return gate(String(message.op || ""), message.body || {}, sender);
    case "disconnect": await chrome.storage.session.remove("auth"); return { ok: true };
    case "state": return { settings: await getSettings(), trail: await getTrail() };
    default: return { ok: false };
  }
}

chrome.runtime.onMessage.addListener((message, sender, reply) => {
  // Content scripts may only report captures, read their site's status and pause; everything else is the side panel's.
  // Decided by the sender's URL, not by sender.tab: the side panel opened in a tab is still an extension page.
  const fromContent = !(sender.id === chrome.runtime.id && sender.url && sender.url.startsWith(chrome.runtime.getURL("")));
  if (fromContent && !["capture", "site-status", "set-paused", "connect", "gate"].includes(message && message.type)) return false;
  handle(message || {}, sender).then(reply, (error) => reply({ ok: false, error: String(error && error.message || error) }));
  return true;
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
  syncCaptureScript().catch(() => {});
});

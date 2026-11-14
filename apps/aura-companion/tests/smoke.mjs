// Loads the unpacked Aura Companion into Playwright's Chromium against a real local Hermes dashboard and drives the
// connect flow, the ask route, capture, redaction, pause, approval and stop. Not part of CI (needs a browser and a
// running server). Run:
//   1. Start Hermes with the sign-in gate on and the companion switched on for one user, e.g.
//      HERMES_DASHBOARD_BASIC_AUTH_USERNAME=melvin HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=<test pass>
//      AURA_COMPANION_SECRET=<32+ chars> AURA_COMPANION_ADMINS=melvin hermes dashboard --host 0.0.0.0 --port 9119
//   2. SMOKE_USER=melvin SMOKE_PASS=<test pass> node apps/aura-companion/tests/smoke.mjs
// Set PLAYWRIGHT_DIR to a folder whose node_modules has playwright if it isn't resolvable from here.
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(process.env.PLAYWRIGHT_DIR ? path.join(process.env.PLAYWRIGHT_DIR, "x.js") : import.meta.url);
const { chromium } = require("playwright");

const AURA = "http://127.0.0.1:9119"; // in AURA_ORIGINS and the manifest, so no permission prompt
const USER = process.env.SMOKE_USER || "melvin";
const PASS = process.env.SMOKE_PASS || "";
const PAGE = `<!doctype html><title>Smoke page</title><main><h1>Quarterly plan</h1>
<p>Contact ops. Stripe key sk_live_51Habcdefghijklmnopqrs and card 4111 1111 1111 1111.</p>
<form onsubmit="event.preventDefault();document.title='SUBMITTED'"><input id="q" type="search" aria-label="Search">
<input id="pw" type="password" aria-label="Password" value="hunter2-secret">
<button id="go" type="submit">Send</button></form><a id="more" href="#more" onclick="document.body.dataset.more='1'">Show more</a></main>`;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " (" + detail + ")" : ""}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const ext = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ctx = await chromium.launchPersistentContext("", { channel: "chromium", headless: true, args: [`--disable-extensions-except=${ext}`, `--load-extension=${ext}`] });
// The test page is served by the browser itself under Aura's origin; everything else reaches the real Hermes server.
await ctx.route(`${AURA}/smoke/**`, (route) => route.fulfill({ status: 200, contentType: "text/html", body: PAGE }));
try {
  let [worker] = ctx.serviceWorkers();
  if (!worker) worker = await ctx.waitForEvent("serviceworker", { timeout: 15000 });
  check("extension loads and its service worker starts", Boolean(worker), worker.url());
  const sw = (fn, arg) => worker.evaluate(fn, arg);
  await sw(async (origin) => { await chrome.storage.local.clear(); await chrome.storage.session.clear(); await chrome.storage.local.set({ settings: { paused: false, optedIn: [], unblocked: [], retention: "1d", auraOrigin: origin } }); }, AURA);

  // ---- Connect: Hermes sign-in, then the connect page hands a key to the extension -------------------------------
  const connect = await ctx.newPage();
  await connect.goto(`${AURA}/aura/companion/connect`);
  check("the connect page sends a signed-out visitor to Hermes sign-in", /\/login|\/auth\//.test(connect.url()), connect.url());
  await connect.fill("input[name=username]", USER);
  await connect.fill("input[name=password]", PASS);
  await connect.press("input[name=password]", "Enter");
  await connect.waitForURL(`${AURA}/aura/companion/connect`, { timeout: 15000 });
  check("after sign-in Hermes returns to the connect page", connect.url() === `${AURA}/aura/companion/connect`);
  check("the connect page has no password field", (await connect.locator("input[type=password]").count()) === 0);
  await connect.click("#connect");
  await connect.waitForFunction(() => /Connected/.test(document.getElementById("status").textContent), null, { timeout: 10000 });
  const auth = await sw(async () => (await chrome.storage.session.get("auth")).auth);
  check("the extension holds a 12-hour aura_ext key in session storage", /^aura_ext\./.test(auth?.token || "") &&
    Math.abs(Date.parse(auth.expiresAt) - Date.now() - 12 * 3600e3) < 120e3, auth && auth.expiresAt);

  // ---- The key: accepted only by the ask route, only from the extension ------------------------------------------
  const ask = { messages: [{ role: "user", content: "What is this page?" }], page: { intent: "ask", url: `${AURA}/smoke/doc`, title: "Smoke", excerpt: "Quarterly plan" } };
  const fromExt = await sw(async ([url, token, body]) => {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify(body), credentials: "omit" });
    return { status: r.status, body: await r.json() };
  }, [`${AURA}/api/aura/companion/ask`, auth.token, ask]);
  // No model key is configured on this smoke server, so the route reaches the free-only model layer and reports it.
  check("the ask route accepts the key from the extension and reaches the model layer", [200, 502, 503].includes(fromExt.status), `${fromExt.status} ${JSON.stringify(fromExt.body)}`);
  const stranger = await ctx.newPage(); // a fresh, signed-in tab on Aura's own origin, standing in for any web page
  await stranger.goto(`${AURA}/smoke/web`);
  const fromWeb = await stranger.evaluate(async ([token, body]) => (await fetch("/api/aura/companion/ask", { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify(body) })).status, [auth.token, ask]);
  check("a web page holding the key is refused", fromWeb === 403, String(fromWeb));
  const elsewhere = await sw(async ([url, token]) => (await fetch(url, { headers: { Authorization: `Bearer ${token}` }, credentials: "omit" })).status, [`${AURA}/api/reveta/overview`, auth.token]);
  check("the key opens no other Hermes route", elsewhere === 401, String(elsewhere));
  const noKey = await sw(async ([url, body]) => (await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), credentials: "omit" })).status, [`${AURA}/api/aura/companion/ask`, ask]);
  check("the ask route refuses a call with no key", noKey === 401, String(noKey));
  await stranger.close();
  await connect.close();

  // ---- Capture, redaction, take-over, pause (same checks as the aura-agent build) --------------------------------
  const page = await ctx.newPage();
  await page.goto(`${AURA}/smoke/doc?token=abc`);
  const inject = () => sw(async (origin) => {
    const [tab] = await chrome.tabs.query({ url: `${origin}/smoke/*` });
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["lib/redact.js", "lib/policy.js", "lib/takeover.js", "capture.js"] });
    return tab.id;
  }, AURA);
  const tabId = await inject();
  await sleep(800);
  let state = await sw(async () => (await chrome.storage.local.get("trail")).trail || []);
  check("nothing is captured before the site is followed", state.length === 0);
  check("the visible indicator appears", await page.evaluate(() => document.documentElement.lastElementChild?.shadowRoot === null && document.documentElement.lastElementChild?.tagName === "DIV"));

  await sw(async () => { const { settings } = await chrome.storage.local.get("settings"); await chrome.storage.local.set({ settings: { ...settings, optedIn: ["127.0.0.1"] } }); });
  await page.reload();
  await inject();
  await sleep(1200);
  state = await sw(async () => (await chrome.storage.local.get("trail")).trail || []);
  const entry = state[0] || {};
  check("a followed site is captured", state.length === 1, entry.title);
  check("the stored URL has no query string", entry.url === `${AURA}/smoke/doc`, entry.url);
  check("keys and card numbers are redacted before storage", !/sk_live|4111/.test(entry.excerpt || "") && /\[redacted\]/.test(entry.excerpt || ""));
  check("password field values are never captured", !JSON.stringify(state).includes("hunter2"));

  const collected = await sw(async (id) => chrome.tabs.sendMessage(id, { type: "collect", withElements: true }), tabId);
  const labels = collected.elements.map((e) => e.label);
  check("the element list omits the password field", !labels.includes("Password") && labels.includes("Search"), labels.join(", "));
  check("a sign-in field on the page is flagged for handoff", collected.handoff === "sign_in");
  const ids = Object.fromEntries(collected.described.map((d) => [d.label, d.id]));
  check("element ids are the companion's own (not the page's DOM ids)", collected.described.every((d, i) => d.id === collected.elements[i].id && /^e\d+$/.test(d.id)));
  const handPlan = { summary: "t", steps: [{ action: "type", target: ids.Search, value: "dublin", consequential: false, label: "Search" }, { action: "click", target: ids.Send, consequential: true, label: "Send" }] };
  await page.evaluate(() => { document.querySelector("#pw").remove(); }); // clear the sign-in blocker for the run
  await sw(async ([id, p]) => chrome.tabs.sendMessage(id, { type: "takeover-start", plan: p }), [tabId, handPlan]);
  await sleep(1500);
  check("the ordinary step ran", (await page.inputValue("#q")) === "dublin");
  check("the Send click waited for approval", (await page.title()) !== "SUBMITTED");
  await page.keyboard.press("Escape");
  await sleep(300);
  const approved = await sw(async (id) => chrome.tabs.sendMessage(id, { type: "takeover-approve", index: 1 }), tabId);
  await sleep(1200);
  check("after Esc, a late approval is refused and nothing is sent", approved.ok === false && (await page.title()) !== "SUBMITTED");
  await page.fill("#q", "");
  await sw(async ([id, p]) => chrome.tabs.sendMessage(id, { type: "takeover-start", plan: p }), [tabId, handPlan]);
  await sleep(1500);
  const ok = await sw(async (id) => chrome.tabs.sendMessage(id, { type: "takeover-approve", index: 1 }), tabId);
  await sleep(1500);
  check("with approval, the Send click runs", ok.ok === true && (await page.title()) === "SUBMITTED");

  await sw(async () => { await chrome.storage.local.remove("trail"); const { settings } = await chrome.storage.local.get("settings"); await chrome.storage.local.set({ settings: { ...settings, paused: true } }); });
  await page.reload();
  await inject();
  await sleep(1200);
  state = await sw(async () => (await chrome.storage.local.get("trail")).trail || []);
  check("paused: nothing is captured", state.length === 0);

  // ---- Side panel: connected, and an Ask shows Hermes's answer or its error, with no page errors -----------------
  await sw(async () => { const { settings } = await chrome.storage.local.get("settings"); await chrome.storage.local.set({ settings: { ...settings, paused: false } }); });
  const panel = await ctx.newPage();
  const errors = [];
  panel.on("pageerror", (e) => errors.push(String(e)));
  await panel.goto(worker.url().replace("background.js", "sidepanel.html"));
  await sleep(800);
  const panelText = await panel.textContent("#account");
  check("the side panel shows the connection", /Connected to Aura as/.test(panelText) && errors.length === 0, panelText.trim().slice(0, 80) + (errors.length ? "; " + errors.join("; ") : ""));

  const denied = await sw(async () => AuraPolicy.siteDecision("https://mail.google.com/", { optedIn: ["mail.google.com"] }));
  check("deny list beats opt-in in the worker", denied.allowed === false && denied.category === "private_mail");
} catch (error) {
  check("smoke run", false, String(error && error.stack || error));
} finally {
  await ctx.close();
  const failed = results.filter((r) => !r.ok).length;
  console.log(`${results.length - failed}/${results.length} passed`);
  process.exitCode = failed ? 1 : 0;
}

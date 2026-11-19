/* Aura Companion content script. Injected only on sites the person switched on. It shows a visible indicator with a
 * one-tap pause, keeps a minimal redacted snapshot of the page, and runs a take-over only when the side panel asks.
 * It never reads form field values, and never lists or touches password, payment or code fields. */
(function () {
  if (globalThis.__auraCompanion) return;
  globalThis.__auraCompanion = true;
  const { redactText } = globalThis.AuraRedact;
  const Policy = globalThis.AuraPolicy;
  const Takeover = globalThis.AuraTakeover;
  const STEP_DELAY_MS = 700;
  let run = null;

  // ---- Visible indicator, in a closed shadow root so the page can't restyle or hide it.
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;right:12px;bottom:12px;z-index:2147483647";
  const root = host.attachShadow({ mode: "closed" });
  root.innerHTML = `<style>
    .pill{font:12px/1.2 system-ui,sans-serif;display:flex;gap:8px;align-items:center;background:#111;color:#fff;border-radius:999px;padding:6px 10px;box-shadow:0 2px 8px rgba(0,0,0,.3)}
    .dot{width:8px;height:8px;border-radius:50%;background:#34d399}.paused .dot{background:#9ca3af}.acting .dot{background:#f59e0b}
    button{font:inherit;background:#fff;color:#111;border:0;border-radius:999px;padding:3px 8px;cursor:pointer}
  </style><div class="pill" role="status"><span class="dot"></span><span class="label">Aura is following</span><button type="button" class="toggle">Pause</button></div>`;
  const pill = root.querySelector(".pill");
  const label = root.querySelector(".label");
  const toggle = root.querySelector(".toggle");
  let paused = false;

  function render() {
    pill.classList.toggle("paused", paused && !run);
    pill.classList.toggle("acting", Boolean(run));
    if (run) { label.textContent = "Aura is acting on this page"; toggle.textContent = "Stop"; return; }
    label.textContent = paused ? "Aura is paused" : "Aura is following";
    toggle.textContent = paused ? "Resume" : "Pause";
  }
  toggle.addEventListener("click", () => {
    if (run) return stopRun("You stopped Aura.");
    paused = !paused;
    render();
    chrome.runtime.sendMessage({ type: "set-paused", value: paused });
    if (!paused) snapshot();
  });
  document.documentElement.appendChild(host);

  // ---- Minimal page snapshot: title, cleaned URL, the start of the main text. Field values are never included.
  function mainText() {
    const node = document.querySelector("main, article, [role=main]") || document.body;
    return redactText(String((node && node.innerText) || "").replace(/\s+/g, " ").trim().slice(0, 4000)).text;
  }
  function pageSignals() {
    return {
      frames: Array.from(document.querySelectorAll("iframe")).map((f) => f.src || "").slice(0, 30),
      hasPasswordField: Boolean(document.querySelector("input[type=password]")),
      hasOneTimeCodeField: Boolean(document.querySelector("input[autocomplete=one-time-code]")),
      text: (document.body && document.body.innerText || "").slice(0, 4000),
    };
  }
  let lastCapture = { url: "", at: 0 };
  async function snapshot() {
    const status = await chrome.runtime.sendMessage({ type: "site-status" }).catch(() => null);
    paused = Boolean(status && status.paused);
    render();
    if (!status || !status.decision.allowed) return;
    if (lastCapture.url === location.href && Date.now() - lastCapture.at < 30000) return;
    lastCapture = { url: location.href, at: Date.now() };
    chrome.runtime.sendMessage({ type: "capture", page: { title: document.title, excerpt: mainText() } }).catch(() => {});
  }

  // ---- Interactive elements the model may target. Protected fields are left out entirely.
  function describe(el) {
    const tag = el.tagName.toLowerCase();
    const labelEl = el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null;
    const text = el.getAttribute("aria-label") || (labelEl && labelEl.innerText) || (tag === "input" ? el.value && ["submit", "button"].includes(el.type) ? el.value : "" : el.innerText) || el.getAttribute("placeholder") || el.getAttribute("title") || el.getAttribute("name") || "";
    return {
      tag, type: (el.getAttribute("type") || "").toLowerCase(), name: el.getAttribute("name") || "", id: el.id || "",
      autocomplete: el.getAttribute("autocomplete") || "", placeholder: el.getAttribute("placeholder") || "",
      label: redactText(String(text).replace(/\s+/g, " ").trim().slice(0, 120)).text, inForm: Boolean(el.form || el.closest("form")),
    };
  }
  let elementMap = new Map();
  function listElements() {
    elementMap = new Map();
    const list = [];
    const nodes = document.querySelectorAll("a[href], button, input:not([type=hidden]), select, textarea, [role=button]");
    for (const el of nodes) {
      if (list.length >= 60) break;
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0 || el.disabled || host.contains(el)) continue;
      const d = describe(el);
      if (Policy.isProtectedField(d)) continue;
      const id = `e${list.length + 1}`;
      elementMap.set(id, { el, d });
      list.push({ id, tag: d.tag, type: d.type || undefined, label: d.label || d.tag, _d: d });
    }
    return list;
  }

  // ---- Take-over executor.
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  function report() { chrome.runtime.sendMessage({ type: "takeover-progress", snapshot: run ? run.state.snapshot() : null }).catch(() => {}); }
  function stopRun(reason) {
    if (!run) return;
    run.state.stop();
    run.reason = reason;
    const snap = run.state.snapshot();
    run = null;
    render();
    chrome.runtime.sendMessage({ type: "takeover-progress", snapshot: { ...snap, reason } }).catch(() => {});
  }
  function setNativeValue(el, value) {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }
  function perform(step) {
    if (step.action === "scroll") { window.scrollBy({ top: (step.direction === "up" ? -0.8 : 0.8) * innerHeight, behavior: "smooth" }); return; }
    const entry = elementMap.get(step.target);
    if (!entry || !entry.el.isConnected) throw new Error("That part of the page changed.");
    if (Policy.isProtectedField(describe(entry.el))) throw new Error("Refused: that's a password, payment or code field.");
    entry.el.scrollIntoView({ block: "center" });
    if (step.action === "click") { entry.el.focus(); entry.el.click(); return; }
    if (step.action === "type") { entry.el.focus(); setNativeValue(entry.el, step.value); return; }
    if (step.action === "select") {
      const option = Array.from(entry.el.options || []).find((o) => o.value === step.value || o.text.trim() === step.value);
      if (!option) throw new Error("That option isn't in the list.");
      setNativeValue(entry.el, option.value);
    }
  }
  async function sha256(value) {
    if (typeof value !== "string") return "";
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
    return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
  }
  /** What the server records and classifies; the typed value travels only as a hash. */
  async function gateBody(current, step, index) {
    const entry = step.target ? elementMap.get(step.target) : null;
    const d = entry ? describe(entry.el) : {};
    return { run_id: current.id, index, action: step.action, target: step.target || "", host: location.hostname,
      value_sha256: await sha256(step.value), consequential: Boolean(step.consequential),
      element: { label: String(d.label || "").slice(0, 200), name: String(d.name || "").slice(0, 200),
        domId: String(d.id || "").slice(0, 200), type: String(d.type || ""), tag: String(d.tag || ""), inForm: Boolean(d.inForm) } };
  }
  function gate(op, body) { return chrome.runtime.sendMessage({ type: "gate", op, body }).catch(() => ({ ok: false })); }
  function halt(current, message) { current.state.fail(message); report(); run = null; render(); }
  async function drive() {
    const current = run;
    while (current && run === current) {
      const blocker = Policy.detectHandoff(pageSignals());
      if (blocker && current.state.snapshot().status !== "waiting_for_user") { current.state.handOff(blocker); report(); return; }
      const step = current.state.next();
      const snap = current.state.snapshot();
      if (!step && snap.status === "awaiting_approval" && !snap.approvalId) {
        // Open the server-side approval the person's tap will answer.
        const asked = await gate("action", await gateBody(current, snap.step, snap.index));
        if (run !== current) return;
        if (!asked.ok || asked.status !== "approval_required") { halt(current, asked.error || "Aura's server didn't open an approval."); return; }
        current.state.requireApproval(asked.approval_id);
      }
      report();
      if (!step) { if (["done", "failed", "stopped"].includes(current.state.snapshot().status)) { run = null; render(); } return; }
      const asked = await gate("action", await gateBody(current, step, step.index));
      if (run !== current) return;
      if (asked.ok && asked.status === "approval_required") { current.state.requireApproval(asked.approval_id); report(); return; }
      if (!asked.ok || asked.status !== "granted") { halt(current, asked.error || "Aura's server didn't allow that step."); return; }
      try { perform(step); } catch (error) { await gate("result", { grant: asked.grant, ok: false, error: error.message }); halt(current, error.message); return; }
      const reported = await gate("result", { grant: asked.grant, ok: true });
      if (!reported.ok) { halt(current, "Aura's server didn't record that step, so Aura stopped."); return; }
      await sleep(STEP_DELAY_MS);
      if (run !== current) return; // stopped while waiting
      current.state.completed(step.index);
    }
  }
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && run) stopRun("You pressed Esc."); }, true);

  chrome.runtime.onMessage.addListener((message, sender, reply) => {
    // Only the extension's own pages (the side panel); never another content script.
    if (sender.id !== chrome.runtime.id || !sender.url || !sender.url.startsWith(chrome.runtime.getURL(""))) return false;
    switch (message.type) {
      case "collect": {
        const elements = message.withElements ? listElements() : [];
        const selection = redactText(String(window.getSelection() || "").slice(0, 1500)).text;
        reply({ title: document.title, excerpt: mainText(), selection, elements: elements.map(({ _d, ...e }) => e), described: elements.map((e) => ({ ...e._d, domId: e._d.id, id: e.id })), handoff: Policy.detectHandoff(pageSignals()) });
        return false;
      }
      case "takeover-start": {
        if (run) { reply({ ok: false, error: "Aura is already acting here." }); return false; }
        run = { id: crypto.randomUUID().replace(/-/g, ""), state: Takeover.createRun(message.plan) };
        render();
        reply({ ok: true });
        drive();
        return false;
      }
      case "takeover-approve": { const ok = Boolean(run && run.state.approve(message.index)); reply({ ok }); if (ok) drive(); return false; }
      case "takeover-resume": { const ok = Boolean(run && run.state.resume(Policy.detectHandoff(pageSignals()))); reply({ ok, snapshot: run && run.state.snapshot() }); if (ok) drive(); return false; }
      case "takeover-stop": stopRun("You stopped Aura."); reply({ ok: true }); return false;
      default: return false;
    }
  });

  snapshot();
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") snapshot(); });
  if (globalThis.navigation) globalThis.navigation.addEventListener("navigatesuccess", () => setTimeout(snapshot, 800));
})();

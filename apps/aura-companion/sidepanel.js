/* Aura Companion side panel. The only place that calls Aura, and only when the person taps. Approvals for consequential
 * steps live here, inside the extension, where a web page can't click them. */
(function () {
  const $ = (id) => document.getElementById(id);
  const send = (message) => chrome.runtime.sendMessage(message);
  let tab = null; // active tab
  let state = null;
  let auth = null;
  let plan = null;
  let described = [];
  let runTabId = null;
  let lastSnapshot = null;
  let handoff = null; // { id, instruction, reported } for a task sent from the Aura chat
  let polling = null; // the chat-approval wait for the current step

  async function activeTab() {
    const [t] = await chrome.tabs.query({ active: true, currentWindow: true });
    return t || null;
  }

  async function refresh() {
    tab = await activeTab();
    state = await send({ type: "state" });
    ({ auth } = await chrome.storage.session.get("auth"));
    if (auth && Date.parse(auth.expiresAt) <= Date.now()) { await send({ type: "disconnect" }); auth = null; }
    renderAccount();
    const status = tab ? await send({ type: "site-status", url: tab.url }) : null;
    renderSite(status && status.decision);
    $("paused").checked = state.settings.paused;
    $("retention").value = state.settings.retention;
    renderTrail();
  }

  function renderAccount() {
    const el = $("account");
    el.replaceChildren();
    const p = document.createElement("p");
    const button = document.createElement("button");
    button.type = "button";
    if (auth) {
      p.textContent = `Connected to Aura as ${auth.email}. The key expires ${new Date(auth.expiresAt).toLocaleString()}.`;
      button.textContent = "Disconnect";
      button.className = "quiet";
      button.onclick = async () => { await send({ type: "disconnect" }); refresh(); };
    } else {
      p.textContent = "Not connected. Connecting uses your Aura sign-in; the companion never sees your password.";
      button.textContent = "Connect to Aura";
      button.onclick = () => chrome.tabs.create({ url: `${state.settings.auraOrigin}/aura/companion/connect` });
    }
    el.append(p, button);
  }

  const REASONS = {
    unsupported: "Aura can't follow this kind of page.",
    paused: "Paused everywhere.",
    not_opted_in: "Not following this site.",
    opted_in: "Following this site. Only this site's pages are kept.",
  };
  const CATEGORIES = { banking: "banking or payments", health: "health", password_manager: "a password manager", private_mail: "private mail", sign_in: "a sign-in page" };
  let decision = null;
  function renderSite(d) {
    decision = d || { allowed: false, reason: "unsupported" };
    $("site-status").textContent = decision.reason === "denied" ? `Blocked: ${decision.host} looks like ${CATEGORIES[decision.category] || "a sensitive site"}, so Aura won't follow it.` : `${decision.host ? decision.host + ": " : ""}${REASONS[decision.reason]}`;
    const opted = decision.host && state.settings.optedIn.includes(decision.host);
    $("follow").hidden = !(decision.reason === "not_opted_in");
    $("unfollow").hidden = !opted;
    $("unblock").hidden = decision.reason !== "denied";
    const usable = Boolean(auth) && (decision.allowed);
    for (const id of ["insight", "ask-send", "plan"]) $(id).disabled = !usable;
  }

  function renderTrail() {
    const list = $("trail");
    list.replaceChildren();
    for (const entry of state.trail) {
      const li = document.createElement("li");
      const span = document.createElement("span");
      span.textContent = `${entry.title || entry.url} · ${entry.host} · ${new Date(entry.at).toLocaleTimeString()}`;
      const del = document.createElement("button");
      del.type = "button"; del.className = "quiet"; del.textContent = "Delete";
      del.onclick = async () => { await send({ type: "delete-entry", id: entry.id }); refresh(); };
      li.append(span, del);
      list.append(li);
    }
    if (!state.trail.length) { const li = document.createElement("li"); li.textContent = "Nothing kept."; list.append(li); }
  }

  // ---- Calling Aura (Hermes: free-only model, a daily per-person cap, nothing saved server-side).
  async function collect(withElements) {
    return chrome.tabs.sendMessage(tab.id, { type: "collect", withElements });
  }
  async function askAura(ask, intent, withElements) {
    if (!auth) throw new Error("Connect to Aura first.");
    const page = await collect(withElements);
    if (!page) throw new Error("Reload the page so Aura can read it.");
    const trail = state.trail.filter((e) => e.url !== AuraRedact.cleanUrl(tab.url)).slice(0, 10).map((e) => ({ title: e.title, host: e.host, at: e.at }));
    const body = {
      messages: [{ role: "user", content: ask }],
      page: { intent, url: AuraRedact.cleanUrl(tab.url), title: page.title.slice(0, 300), excerpt: page.excerpt.slice(0, 4000), ...(page.selection ? { selection: page.selection } : {}), trail, ...(withElements ? { elements: page.elements } : {}) },
    };
    const response = await fetch(`${state.settings.auraOrigin}/api/aura/companion/ask`, {
      method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${auth.token}` }, body: JSON.stringify(body), credentials: "omit",
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401) { await send({ type: "disconnect" }); refresh(); throw new Error("Your connection expired. Connect to Aura again."); }
    if (!response.ok) throw new Error(data.error || `Aura returned ${response.status}.`);
    return { content: String(data.content || ""), page };
  }

  async function runAsk(ask, intent) {
    $("answer").textContent = "Thinking…";
    try { $("answer").textContent = (await askAura(ask, intent, false)).content; }
    catch (error) { $("answer").textContent = error.message; }
  }

  // ---- Take-over.
  function renderSteps(snapshot) {
    const list = $("steps");
    list.replaceChildren();
    if (!plan) return;
    plan.steps.forEach((step, i) => {
      const li = document.createElement("li");
      const what = step.action === "scroll" ? `Scroll ${step.direction}` : step.action === "click" ? `Click “${step.label}”` : `${step.action === "type" ? "Type" : "Choose"} “${step.value}” in “${step.label}”`;
      li.textContent = step.consequential ? `${what} (needs your approval)` : what;
      if (step.consequential) li.className = "consequential";
      if (snapshot && snapshot.index === i && !["done", "stopped", "failed"].includes(snapshot.status)) li.classList.add("current");
      list.append(li);
    });
  }
  function renderRun(snapshot) {
    lastSnapshot = snapshot;
    const status = snapshot ? snapshot.status : null;
    const live = status && !["done", "stopped", "failed"].includes(status);
    $("run").hidden = !plan || Boolean(snapshot);
    $("stop").hidden = !live;
    $("approve").hidden = status !== "awaiting_approval" || Boolean(handoff);
    $("resume").hidden = status !== "waiting_for_user";
    const HANDOFF = { challenge: "There's a CAPTCHA. Aura never solves these: complete it yourself, then tap continue.", verification: "The page wants a verification code. Enter it yourself, then tap continue.", sign_in: "The page wants you to sign in. Do that yourself, then tap continue." };
    const text = !snapshot ? (plan ? plan.summary : "")
      : status === "awaiting_approval" ? `Step ${snapshot.index + 1} would ${plan.steps[snapshot.index].label ? `press “${plan.steps[snapshot.index].label}”` : "do something consequential"}. ${handoff ? "Approve it in your Aura chat, or Stop." : "Approve it to continue, or Stop."}`
      : status === "waiting_for_user" ? HANDOFF[snapshot.handoff] || "Your turn on the page."
      : status === "done" ? "Done." : status === "stopped" ? snapshot.reason || "Stopped." : status === "failed" ? `Stopped: ${snapshot.error}` : `Working on step ${snapshot.index + 1} of ${snapshot.total}…`;
    $("run-status").textContent = text;
    renderSteps(snapshot);
    if (handoff) followHandoff(snapshot);
  }

  // ---- Chat-to-browser handoff (off unless the owner switched it on in Aura).
  function gate(op, body) { return send({ type: "gate", op, body }).catch(() => ({ ok: false })); }
  function showHandoff() {
    $("handoff").hidden = !handoff;
    if (handoff) $("handoff-text").textContent = handoff.instruction;
  }
  async function reportHandoff(ok, summary) {
    if (!handoff || handoff.reported) return;
    handoff.reported = true;
    await gate("handoff-result", { id: handoff.id, ok, summary: String(summary || "").slice(0, 2000) });
    handoff = null;
    showHandoff();
  }
  async function pollHandoff() {
    if (!auth || handoff || plan) return;
    const next = await gate("handoff-next", {});
    if (next && next.ok && next.id) { handoff = { id: next.id, instruction: String(next.instruction || "") }; showHandoff(); }
  }
  function followHandoff(snapshot) {
    const status = snapshot && snapshot.status;
    if (["done", "stopped", "failed"].includes(status)) {
      const outcome = status === "done" ? "Done" : status === "failed" ? `Stopped: ${snapshot.error}` : snapshot.reason || "Stopped";
      reportHandoff(status === "done", `${plan ? plan.summary + " — " : ""}${outcome}. Page: ${tab ? tab.title : ""}`);
      return;
    }
    if (status !== "awaiting_approval" || !snapshot.approvalId || polling === snapshot.approvalId) return;
    polling = snapshot.approvalId;
    const wait = async () => {
      if (!handoff || !lastSnapshot || lastSnapshot.approvalId !== polling) { polling = null; return; }
      const answer = await gate("status", { approval_id: polling });
      if (answer.ok && answer.state === "approved") { polling = null; chrome.tabs.sendMessage(runTabId, { type: "takeover-approve", index: lastSnapshot.index }); return; }
      if (answer.ok && answer.state === "denied") { polling = null; chrome.tabs.sendMessage(runTabId, { type: "takeover-stop" }); return; }
      setTimeout(wait, 2000);
    };
    wait();
  }
  $("handoff-start").onclick = async () => {
    $("instruction").value = handoff.instruction;
    await makePlan();
    if (handoff && !plan) reportHandoff(false, $("run-status").textContent);
  };
  $("handoff-dismiss").onclick = () => reportHandoff(false, "Declined in the browser.");
  setInterval(pollHandoff, 5000);

  async function makePlan() {
    plan = null; runTabId = null; renderRun(null);
    const instruction = $("instruction").value.trim();
    if (!instruction) return;
    $("run-status").textContent = "Planning…";
    try {
      const { content, page } = await askAura(instruction, "takeover", true);
      if (page.handoff) { $("run-status").textContent = "This page needs you first (a sign-in, code or CAPTCHA). Finish that, then plan again."; return; }
      described = page.described;
      const parsed = AuraTakeover.parsePlan(content, described);
      if (!parsed.ok) { $("run-status").textContent = parsed.error; return; }
      plan = parsed.plan;
      renderRun(null);
    } catch (error) { $("run-status").textContent = error.message; }
  }

  $("follow").onclick = async () => {
    // The browser shows its own permission prompt for exactly this site.
    const origins = [`https://${decision.host}/*`, `http://${decision.host}/*`];
    const granted = await chrome.permissions.request({ origins });
    if (!granted) return;
    await send({ type: "opt-in", host: decision.host, tabId: tab.id });
    refresh();
  };
  $("unfollow").onclick = async () => { await send({ type: "opt-out", host: decision.host }); refresh(); };
  $("unblock").onclick = async () => {
    if (!confirm(`${decision.host} is on the blocked list because it looks like ${CATEGORIES[decision.category] || "a sensitive site"}. Remove it from the list? You'd still need to choose Follow.`)) return;
    await send({ type: "unblock", entry: decision.entry });
    refresh();
  };
  $("paused").onchange = async (e) => { await send({ type: "set-paused", value: e.target.checked }); refresh(); };
  $("retention").onchange = async (e) => { await send({ type: "set-retention", value: e.target.value }); refresh(); };
  $("delete-all").onclick = async () => { await send({ type: "delete-all" }); refresh(); };
  $("insight").onclick = () => runAsk("Give me insights on this page.", "insight");
  $("ask-send").onclick = () => { const q = $("ask").value.trim(); if (q) runAsk(q, "ask"); };
  $("plan").onclick = makePlan;
  $("run").onclick = async () => {
    runTabId = tab.id;
    const reply = await chrome.tabs.sendMessage(runTabId, { type: "takeover-start", plan, runId: handoff ? handoff.id : undefined });
    if (!reply || !reply.ok) $("run-status").textContent = (reply && reply.error) || "Couldn't start.";
  };
  $("approve").onclick = async () => {
    if (!runTabId || !lastSnapshot || !lastSnapshot.approvalId) return;
    // Recorded on Aura's server first; the page only continues once the server has the approval.
    const decided = await send({ type: "gate", op: "approve", body: { approval_id: lastSnapshot.approvalId } });
    if (!decided || !decided.ok) { $("answer").textContent = (decided && decided.error) || "Aura's server didn't record the approval."; return; }
    chrome.tabs.sendMessage(runTabId, { type: "takeover-approve", index: lastSnapshot.index });
  };
  $("resume").onclick = async () => {
    const reply = runTabId && await chrome.tabs.sendMessage(runTabId, { type: "takeover-resume" });
    if (reply && !reply.ok) $("run-status").textContent = "The page still needs you. Finish it, then tap continue.";
  };
  $("stop").onclick = () => runTabId && chrome.tabs.sendMessage(runTabId, { type: "takeover-stop" });

  chrome.runtime.onMessage.addListener((message, sender) => {
    if (message.type === "takeover-progress" && sender.tab && sender.tab.id === runTabId) renderRun(message.snapshot);
  });
  // A navigation ends the run: the old page's script is gone, so nothing can keep acting.
  chrome.tabs.onUpdated.addListener((id, info) => {
    if (id === runTabId && info.status === "loading" && plan && lastSnapshot && !["done", "stopped", "failed"].includes(lastSnapshot.status)) { renderRun({ status: "stopped", index: 0, total: plan.steps.length, reason: "The page changed, so Aura stopped. Plan again to continue." }); runTabId = null; }
    if (tab && id === tab.id && info.status === "complete") refresh();
  });
  chrome.tabs.onActivated.addListener(() => { plan = null; runTabId = null; renderRun(null); refresh(); });
  refresh();
})();

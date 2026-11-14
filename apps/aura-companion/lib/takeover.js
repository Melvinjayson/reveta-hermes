/*
 * Take-over: Aura acts in the person's page only after they ask, one validated step at a time.
 * - The model only proposes a plan; parsePlan accepts a small fixed vocabulary that targets elements the page listed.
 * - A consequential click needs its own single-use approval, bound to that step and element.
 * - stop() is terminal: nothing runs after it, whatever arrives later.
 * - A CAPTCHA, MFA or sign-in hands the page to the person (same kinds and the same rule as Aura's browser handoff:
 *   finishing a handoff approves nothing). Resuming needs the page to be clear again.
 * Classic script (see redact.js).
 */
(function () {
  const Policy = typeof module === "object" && module.exports ? require("./policy.js") : globalThis.AuraPolicy;
  const ACTIONS = ["click", "type", "select", "scroll"];
  const MAX_STEPS = 8;

  /** Parses the model's JSON plan. elements: [{ id, tag, type, label, ... }] as listed to the model. */
  function parsePlan(text, elements) {
    const raw = String(text || "");
    const start = raw.indexOf("{");
    const end = raw.lastIndexOf("}");
    if (start < 0 || end <= start) return { ok: false, error: "Aura didn't return a plan it can run." };
    let data;
    try { data = JSON.parse(raw.slice(start, end + 1)); } catch { return { ok: false, error: "Aura's plan wasn't valid." }; }
    if (!data || !Array.isArray(data.steps)) return { ok: false, error: "Aura's plan had no steps." };
    if (data.steps.length === 0) return { ok: false, error: String(data.summary || "Aura found nothing to do on this page.").slice(0, 300) };
    if (data.steps.length > MAX_STEPS) return { ok: false, error: `Plans are limited to ${MAX_STEPS} steps.` };
    const byId = new Map((elements || []).map((e) => [e.id, e]));
    const steps = [];
    for (const s of data.steps) {
      if (!s || !ACTIONS.includes(s.action)) return { ok: false, error: "Aura's plan used an action the companion doesn't allow." };
      if (s.action === "scroll") { steps.push({ action: "scroll", direction: s.direction === "up" ? "up" : "down" }); continue; }
      const el = byId.get(s.target);
      if (!el) return { ok: false, error: "Aura's plan pointed at something that isn't on this page." };
      if (Policy.isProtectedField(el)) return { ok: false, error: "Aura's plan touched a password, payment or code field, so it was refused." };
      const step = { action: s.action, target: el.id };
      if (s.action === "type" || s.action === "select") {
        if (typeof s.value !== "string" || s.value.length > 500) return { ok: false, error: "Aura's plan had an invalid value to enter." };
        step.value = s.value;
      }
      step.consequential = Policy.isConsequential(step, el);
      step.label = String(el.label || el.tag || "element").slice(0, 80);
      steps.push(step);
    }
    return { ok: true, plan: { summary: String(data.summary || "").slice(0, 300), steps } };
  }

  /** Run state. Pure: the content script performs each step it hands out and reports back. */
  function createRun(plan) {
    const steps = plan.steps.slice();
    let index = 0;
    let status = "ready"; // ready | awaiting_approval | waiting_for_user | stopped | done | failed
    let approval = null; // { index, target } single-use
    let handoff = null;
    let error = null;

    function snapshot() { return { status, index, total: steps.length, step: steps[index] || null, handoff, error }; }
    function terminal() { return status === "stopped" || status === "done" || status === "failed"; }

    return {
      snapshot,
      /** The next step to perform, or null when the run must wait (approval, handoff) or has ended. */
      next() {
        if (terminal() || status === "waiting_for_user") return null;
        if (index >= steps.length) { status = "done"; return null; }
        const step = steps[index];
        if (step.consequential) {
          if (!approval || approval.index !== index || approval.target !== step.target) { status = "awaiting_approval"; return null; }
          approval = null; // single use
        }
        status = "ready";
        return { index, ...step };
      },
      /** Only the person's tap in the side panel calls this, for the step currently waiting. */
      approve(stepIndex) {
        if (status !== "awaiting_approval" || stepIndex !== index) return false;
        approval = { index, target: steps[index].target };
        status = "ready";
        return true;
      },
      completed(stepIndex) {
        if (terminal() || stepIndex !== index) return;
        index++;
        if (index >= steps.length) status = "done";
      },
      fail(message) { if (!terminal()) { status = "failed"; error = String(message || "Step failed").slice(0, 200); } },
      /** A challenge, verification or sign-in appeared: the person takes the page. */
      handOff(kind) { if (!terminal()) { status = "waiting_for_user"; handoff = kind; approval = null; } },
      /** The person says they're done; resumes only if the page no longer shows a blocker. Approves nothing. */
      resume(blocker) {
        if (status !== "waiting_for_user") return false;
        if (blocker) { handoff = blocker; return false; }
        status = "ready"; handoff = null;
        return true;
      },
      stop() { if (!terminal()) status = "stopped"; approval = null; },
    };
  }

  const api = { parsePlan, createRun, ACTIONS, MAX_STEPS };
  if (typeof module === "object" && module.exports) module.exports = api;
  else globalThis.AuraTakeover = api;
})();

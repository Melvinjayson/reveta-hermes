import test from "node:test";
import assert from "node:assert/strict";
import redact from "../lib/redact.js";
import policy from "../lib/policy.js";
import takeover from "../lib/takeover.js";

// ---- Redaction

test("redaction removes keys, tokens, card numbers, IBANs and credential pairs", () => {
  const secrets = [
    "sk-ant-api03-abcdefghijklmnopqrstuvwxyz012345",
    "sk_live_51Habcdefghijklmnop",
    "AKIAABCDEFGHIJKLMNOP",
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "re_abc12345_abcdefghijklmnopqrstuv",
    "aura_ext.eyJ2IjoxfQ.c2lnbmF0dXJl",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.abcdefghijklmnop",
    "4111 1111 1111 1111",
    "IE29 AIBK 9311 5212 3456 78",
  ];
  for (const secret of secrets) {
    const { text, count } = redact.redactText(`before ${secret} after`);
    assert.ok(!text.includes(secret), `leaked ${secret}`);
    assert.ok(count >= 1);
    assert.match(text, /^before .*\[redacted\].* after$/);
  }
  assert.equal(redact.redactText("password: hunter2 and api_key=abc123").text, "password: [redacted] and api_key=[redacted]");
  assert.equal(redact.redactText("Authorization: Bearer abcdefghijklmnopqrstu").text.includes("abcdefghijklmnopqrstu"), false);
});

test("redaction keeps ordinary text, including numbers that fail the card checksum", () => {
  const plain = "Order 1234 5678 9012 3456 ships Friday to Dublin 8; call 01 555 0100.";
  assert.deepEqual(redact.redactText(plain), { text: plain, count: 0 });
});

test("URLs keep only origin and path, and token-like path segments are masked", () => {
  assert.equal(redact.cleanUrl("https://example.com/a/b?token=secret#frag"), "https://example.com/a/b");
  assert.equal(redact.cleanUrl("https://x.io/reset/9f8a7b6c5d4e3f2a1b0c9d8e7f6a"), "https://x.io/reset/[redacted]");
  assert.equal(redact.cleanUrl("chrome://settings"), "");
  assert.equal(redact.cleanUrl("not a url"), "");
});

test("default deny list blocks banking, health, password managers, private mail and sign-in pages", () => {
  const s = { optedIn: ["mail.google.com", "www.aib.ie", "vault.bitwarden.com", "www.hse.ie", "accounts.google.com", "mybank.example", "city-hospital.org"] };
  assert.equal(policy.siteDecision("https://mail.google.com/mail/u/0", s).category, "private_mail");
  assert.equal(policy.siteDecision("https://www.aib.ie/login", s).category, "banking");
  assert.equal(policy.siteDecision("https://vault.bitwarden.com/", s).category, "password_manager");
  assert.equal(policy.siteDecision("https://www.hse.ie/", s).category, "health");
  assert.equal(policy.siteDecision("https://accounts.google.com/", s).category, "sign_in");
  assert.equal(policy.siteDecision("https://online.bank.example/", s).category, "banking");
  assert.equal(policy.siteDecision("https://city-hospital.org/", s).category, "health");
  for (const url of ["https://mail.google.com/", "https://www.aib.ie/"]) assert.equal(policy.siteDecision(url, s).allowed, false, "opting in doesn't override the deny list");
});

test("only the person removing an entry unblocks it, and they still have to opt in", () => {
  assert.equal(policy.siteDecision("https://mail.google.com/", { unblocked: ["mail.google.com"] }).reason, "not_opted_in");
  assert.equal(policy.siteDecision("https://mail.google.com/", { unblocked: ["mail.google.com"], optedIn: ["mail.google.com"] }).allowed, true);
});

test("sites are off until opted in, pause overrides everything, and non-web pages are never read", () => {
  assert.equal(policy.siteDecision("https://news.ycombinator.com/", {}).reason, "not_opted_in");
  assert.equal(policy.siteDecision("https://news.ycombinator.com/", { optedIn: ["news.ycombinator.com"] }).allowed, true);
  assert.equal(policy.siteDecision("https://sub.news.ycombinator.com/", { optedIn: ["news.ycombinator.com"] }).allowed, false, "opt-in is per exact host");
  assert.deepEqual(policy.siteDecision("https://news.ycombinator.com/", { optedIn: ["news.ycombinator.com"], paused: true }), { allowed: false, reason: "paused", host: "news.ycombinator.com" });
  for (const url of ["chrome://settings", "file:///etc/passwd", "chrome-extension://abc/x.html", ""]) assert.equal(policy.siteDecision(url, { optedIn: ["settings"] }).reason, "unsupported");
});

test("password, payment and code fields are protected", () => {
  for (const d of [{ type: "password" }, { autocomplete: "cc-number" }, { autocomplete: "one-time-code" }, { label: "Card number" }, { name: "cvv" }, { placeholder: "Enter your PIN" }, { id: "iban" }, { label: "API key" }]) {
    assert.equal(policy.isProtectedField(d), true, JSON.stringify(d));
  }
  for (const d of [{ type: "search", label: "Search" }, { type: "email", label: "Email" }, { tag: "textarea", label: "Message" }]) assert.equal(policy.isProtectedField(d), false);
});

test("clicks that send, submit, post, buy, pay or delete are consequential", () => {
  const click = { action: "click" };
  for (const label of ["Send", "Submit", "Post", "Buy now", "Pay €20", "Delete project", "Place order", "Confirm"]) assert.equal(policy.isConsequential(click, { tag: "a", label }), true, label);
  assert.equal(policy.isConsequential(click, { tag: "input", type: "submit", label: "Go" }), true);
  assert.equal(policy.isConsequential(click, { tag: "button", type: "", inForm: true, label: "Go" }), true);
  for (const label of ["Next page", "Show more", "Pricing"]) assert.equal(policy.isConsequential(click, { tag: "a", label }), false, label);
  assert.equal(policy.isConsequential({ action: "type" }, { tag: "input", label: "Send to" }), false);
});

test("CAPTCHA, MFA and sign-in hand the page to the person", () => {
  assert.equal(policy.detectHandoff({ frames: ["https://www.google.com/recaptcha/api2/anchor"] }), "challenge");
  assert.equal(policy.detectHandoff({ text: "Please verify you are human" }), "challenge");
  assert.equal(policy.detectHandoff({ hasOneTimeCodeField: true }), "verification");
  assert.equal(policy.detectHandoff({ text: "Enter the verification code we sent" }), "verification");
  assert.equal(policy.detectHandoff({ hasPasswordField: true }), "sign_in");
  assert.equal(policy.detectHandoff({ text: "A normal article" }), null);
});

// ---- Take-over plans, approval gating and stop

const elements = [
  { id: "e1", tag: "input", type: "search", label: "Search" },
  { id: "e2", tag: "button", type: "submit", label: "Search", inForm: true },
  { id: "e3", tag: "a", label: "Next page" },
  { id: "e4", tag: "button", label: "Delete" },
  { id: "e5", tag: "input", type: "password", label: "Password" },
];
const plan = (steps: unknown[]) => JSON.stringify({ summary: "s", steps });
type Parsed = { ok: boolean; error?: string; plan: { summary: string; steps: Array<{ index?: number; target?: string; consequential?: boolean }> } };
const parse = (text: string) => takeover.parsePlan(text, elements) as unknown as Parsed;

test("plans accept only the fixed actions on listed elements and refuse protected fields", () => {
  const ok = parse("Here you go: " + plan([{ action: "type", target: "e1", value: "cafes" }, { action: "click", target: "e2" }, { action: "scroll", direction: "down" }]));
  assert.equal(ok.ok, true);
  assert.deepEqual(ok.plan.steps.map((s) => Boolean(s.consequential)), [false, true, false]);
  assert.equal(parse(plan([{ action: "navigate", target: "e1" }])).ok, false);
  assert.equal(parse(plan([{ action: "click", target: "e99" }])).ok, false);
  assert.match(parse(plan([{ action: "type", target: "e5", value: "x" }])).error ?? "", /password/);
  assert.equal(parse(plan(Array(9).fill({ action: "scroll" }))).ok, false);
  assert.equal(parse("no json here").ok, false);
  assert.equal(parse(plan([])).ok, false);
});

function runOf(steps: unknown[]) {
  const parsed = parse(plan(steps));
  assert.equal(parsed.ok, true);
  return takeover.createRun(parsed.plan);
}

test("a consequential step waits for its own approval, and each approval is single use", () => {
  const run = runOf([{ action: "click", target: "e4" }, { action: "click", target: "e2" }]);
  assert.equal(run.next(), null);
  assert.equal(run.snapshot().status, "awaiting_approval");
  assert.equal(run.approve(1), false, "approving a different step is refused");
  assert.equal(run.approve(0), true);
  assert.equal(run.next()?.target, "e4");
  run.completed(0);
  assert.equal(run.next(), null, "the next consequential step needs a fresh approval");
  assert.equal(run.snapshot().status, "awaiting_approval");
  assert.equal(run.approve(1), true);
  assert.equal(run.next()?.target, "e2");
  run.completed(1);
  assert.equal(run.snapshot().status, "done");
});

test("ordinary steps run without approval", () => {
  const run = runOf([{ action: "type", target: "e1", value: "x" }, { action: "click", target: "e3" }]);
  assert.equal(run.next()?.index, 0); run.completed(0);
  assert.equal(run.next()?.index, 1); run.completed(1);
  assert.equal(run.snapshot().status, "done");
});

test("stop is final: nothing runs, completes or gets approved after it", () => {
  const run = runOf([{ action: "type", target: "e1", value: "x" }, { action: "click", target: "e4" }]);
  const step = run.next();
  run.stop();
  run.completed(step!.index);
  assert.equal(run.snapshot().status, "stopped");
  assert.equal(run.snapshot().index, 0);
  assert.equal(run.next(), null);
  assert.equal(run.approve(1), false);
  assert.equal(run.resume(null), false);
  run.fail("late error");
  assert.equal(run.snapshot().status, "stopped");
});

test("stop while awaiting approval discards the pending approval", () => {
  const run = runOf([{ action: "click", target: "e4" }]);
  run.next();
  run.stop();
  assert.equal(run.approve(0), false);
  assert.equal(run.next(), null);
});

test("a handoff pauses the run, resumes only when the page is clear, and approves nothing", () => {
  const run = runOf([{ action: "click", target: "e4" }]);
  run.handOff("challenge");
  assert.equal(run.snapshot().status, "waiting_for_user");
  assert.equal(run.next(), null);
  assert.equal(run.resume("challenge"), false, "still blocked");
  assert.equal(run.resume(null), true);
  assert.equal(run.next(), null, "finishing the handoff did not approve the delete");
  assert.equal(run.snapshot().status, "awaiting_approval");
});

/*
 * Site and action policy for the Aura Companion. Pure functions over plain descriptors so they can be tested in Node
 * and run unchanged in the content script and service worker. Classic script (see redact.js).
 */
(function () {
  // Default deny list: never followed unless the person removes the entry themselves in the side panel.
  const DEFAULT_DENY = {
    banking: ["paypal.com", "revolut.com", "wise.com", "monzo.com", "n26.com", "aib.ie", "bankofireland.com", "ptsb.ie", "boi.com", "chase.com", "wellsfargo.com", "barclays.co.uk", "hsbc.com", "santander.com", "citi.com", "americanexpress.com", "stripe.com", "coinbase.com", "binance.com", "kraken.com", "gtbank.com", "accessbankplc.com", "opayweb.com", "kudabank.com", "paystack.com", "flutterwave.com"],
    health: ["hse.ie", "nhs.uk", "mychart.com", "patient.info", "healthline.com", "webmd.com", "vhi.ie", "laya.ie", "irishlife.ie", "zocdoc.com"],
    password_manager: ["1password.com", "bitwarden.com", "lastpass.com", "dashlane.com", "keepersecurity.com", "nordpass.com", "pass.proton.me", "passwords.google.com"],
    private_mail: ["mail.google.com", "outlook.live.com", "outlook.office.com", "outlook.office365.com", "mail.proton.me", "mail.yahoo.com", "mail.aol.com", "fastmail.com", "hey.com"],
    sign_in: ["accounts.google.com", "login.microsoftonline.com", "login.live.com", "appleid.apple.com", "id.atlassian.com", "auth0.com", "okta.com"],
  };
  const DENY_KEYWORDS = { banking: /(^|[.-])(bank|banking|creditunion)([.-]|$)/, health: /(^|[.-])(health|clinic|hospital|pharmacy|medical)([.-]|$)/ };

  function hostOf(url) {
    try {
      const u = new URL(String(url));
      return u.protocol === "https:" || u.protocol === "http:" ? u.hostname.toLowerCase() : null;
    } catch { return null; }
  }
  function hostMatches(host, entry) { return host === entry || host.endsWith("." + entry); }

  /** Deny-list category for a host, or null. `unblocked` holds entries the person removed from the list themselves. */
  function denyCategory(host, unblocked) {
    const removed = new Set(unblocked || []);
    for (const [category, hosts] of Object.entries(DEFAULT_DENY)) {
      const hit = hosts.find((entry) => hostMatches(host, entry));
      if (hit && !removed.has(hit)) return { category, entry: hit };
    }
    for (const [category, pattern] of Object.entries(DENY_KEYWORDS)) {
      if (pattern.test(host) && !removed.has(host)) return { category, entry: host };
    }
    return null;
  }

  /**
   * Whether the companion may read a page. Order: unsupported scheme -> paused -> deny list -> not opted in -> allowed.
   * settings = { paused, optedIn: string[] (hosts), unblocked: string[] }
   */
  function siteDecision(url, settings) {
    const s = settings || {};
    const host = hostOf(url);
    if (!host) return { allowed: false, reason: "unsupported" };
    if (s.paused) return { allowed: false, reason: "paused", host };
    const denied = denyCategory(host, s.unblocked);
    if (denied) return { allowed: false, reason: "denied", host, category: denied.category, entry: denied.entry };
    if (!(s.optedIn || []).includes(host)) return { allowed: false, reason: "not_opted_in", host };
    return { allowed: true, reason: "opted_in", host };
  }

  const PROTECTED_AUTOCOMPLETE = /^(cc-|current-password|new-password|one-time-code)/;
  const PROTECTED_NAME = /(pass(word|wd|code)?|pwd|\bpin\b|otp|one.?time|cvv|cvc|csc|security.?code|card.?(number|no)|cc.?(num|number)|expir|iban|sort.?code|routing|account.?number|ssn|social.?security|secret|api.?key|token)/i;

  /** Password, payment and credential fields: never read, never listed for the model, never typed into. */
  function isProtectedField(d) {
    if (!d) return false;
    if ((d.type || "").toLowerCase() === "password") return true;
    if (PROTECTED_AUTOCOMPLETE.test((d.autocomplete || "").toLowerCase())) return true;
    return PROTECTED_NAME.test([d.name, d.id, d.domId, d.label, d.placeholder].filter(Boolean).join(" "));
  }

  const CONSEQUENTIAL = /\b(send|submit|post|publish|share|tweet|reply|comment|buy|purchase|order|checkout|check out|pay|payment|donate|tip|delete|remove|erase|discard|archive|transfer|withdraw|confirm|book|reserve|subscribe|unsubscribe|sign up|register|apply|accept|invite|upload|save changes|place)\b/i;

  /** A click that sends, submits, posts, buys, pays, books or deletes needs its own explicit approval. */
  function isConsequential(step, d) {
    if (!step || step.action !== "click" || !d) return false;
    const type = (d.type || "").toLowerCase();
    if (type === "submit" || type === "image") return true;
    if (d.tag === "button" && d.inForm && (type === "" || type === "submit")) return true;
    return CONSEQUENTIAL.test([d.label, d.name, d.domId || d.id].filter(Boolean).join(" "));
  }

  /**
   * What stops Aura and hands the page to the person. Same kinds as Aura's browser handoff (PR #55): a challenge
   * (CAPTCHA), a verification (MFA / one-time code) or a sign-in. Aura never tries to solve or bypass any of them.
   * signals = { frames: string[] (iframe srcs), hasPasswordField, hasOneTimeCodeField, text }
   */
  function detectHandoff(signals) {
    const s = signals || {};
    const frames = (s.frames || []).join(" ").toLowerCase();
    const text = String(s.text || "").slice(0, 4000).toLowerCase();
    if (/recaptcha|hcaptcha|turnstile|challenges\.cloudflare|arkoselabs|funcaptcha|captcha/.test(frames) || /\b(i'?m not a robot|verify you are human|captcha)\b/.test(text)) return "challenge";
    if (s.hasOneTimeCodeField || /\b(verification code|2-step|two-factor|2fa|authenticator app|one-time code)\b/.test(text)) return "verification";
    if (s.hasPasswordField) return "sign_in";
    return null;
  }

  const api = { DEFAULT_DENY, hostOf, denyCategory, siteDecision, isProtectedField, isConsequential, detectHandoff };
  if (typeof module === "object" && module.exports) module.exports = api;
  else globalThis.AuraPolicy = api;
})();

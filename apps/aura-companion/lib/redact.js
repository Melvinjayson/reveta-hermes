/*
 * Redaction shared by the Aura Companion extension and the Aura server (defence in depth: the browser redacts before
 * anything leaves it, the server redacts again before anything reaches a model). Classic script, no dependencies:
 * Chrome loads it with importScripts / content_scripts; Node and Next load it as CommonJS.
 */
(function () {
  const MARK = "[redacted]";
  const PATTERNS = [
    /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)/g,
    /\b(?:sk|pk|rk)-(?:ant-|proj-|live-|test-)?[A-Za-z0-9_-]{16,}/g, // OpenAI / Anthropic / Stripe style keys
    /\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{10,}/g,
    /\bAKIA[0-9A-Z]{16}\b/g, // AWS access key ID
    /\bAIza[0-9A-Za-z_-]{35}\b/g, // Google API key
    /\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b/g, /\bgithub_pat_[A-Za-z0-9_]{30,}\b/g,
    /\bxox[abprs]-[A-Za-z0-9-]{10,}/g, // Slack
    /\bre_[A-Za-z0-9]{8,}_[A-Za-z0-9]{16,}\b/g, // Resend
    /\baura_ext\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g, // our own extension token
    /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/g, // JWT
    /\bBearer\s+[A-Za-z0-9._~+/-]{16,}=*/gi,
    /\b(password|passwd|pwd|passcode|secret|api[_-]?key|access[_-]?token|token|pin|otp|cvv|cvc)(\s*[:=]\s*)\S+/gi,
    /\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,4})?\b/g, // IBAN
    /\b\d{3}-\d{2}-\d{4}\b/g, // US SSN
  ];
  const CARD = /\b\d(?:[ -]?\d){12,18}\b/g;

  function luhn(digits) {
    let sum = 0;
    for (let i = 0; i < digits.length; i++) {
      let d = Number(digits[digits.length - 1 - i]);
      if (i % 2 === 1) { d *= 2; if (d > 9) d -= 9; }
      sum += d;
    }
    return sum % 10 === 0;
  }

  /** Returns the text with secrets, card numbers, IBANs and credential pairs replaced by "[redacted]". */
  function redactText(input) {
    let text = String(input == null ? "" : input);
    let count = 0;
    for (const pattern of PATTERNS) {
      text = text.replace(pattern, (match, label, sep) => {
        count++;
        return typeof label === "string" && typeof sep === "string" ? label + sep + MARK : MARK;
      });
    }
    text = text.replace(CARD, (match) => {
      const digits = match.replace(/\D/g, "");
      if (digits.length < 13 || !luhn(digits)) return match;
      count++;
      return MARK;
    });
    return { text, count };
  }

  /** Origin and path only: query strings and fragments often carry tokens, and token-like path segments are masked. */
  function cleanUrl(input) {
    let url;
    try { url = new URL(String(input)); } catch { return ""; }
    if (url.protocol !== "https:" && url.protocol !== "http:") return "";
    const path = url.pathname.split("/").map((part) => (part.length >= 24 && /[0-9]/.test(part) && /[A-Za-z]/.test(part) ? MARK : part)).join("/");
    return url.origin + redactText(path).text;
  }

  const api = { redactText, cleanUrl, MARK };
  if (typeof module === "object" && module.exports) module.exports = api;
  else globalThis.AuraRedact = api;
})();

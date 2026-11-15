# Aura Companion (browser extension, test build)

Aura goes with you on the sites you switch on, keeps a short redacted trail of what you looked at in your browser,
turns it into insights on request, and acts on a page only when you ask. It talks to Aura on Hermes
(`hermes_cli/web_routers/aura_companion.py`).

Status: canary test build. Off on the server unless `AURA_COMPANION_SECRET` is set, not on the Chrome Web Store.

## Install (Chrome, Edge, Brave or Arc, version 116 or later)

1. Get this folder: unzip `aura-companion-hermes-0.2.0.zip`, or clone the repo and use `apps/aura-companion`.
2. Open `chrome://extensions`, switch on **Developer mode** (top right).
3. Click **Load unpacked** and pick the folder.
4. Pin **Aura Companion (test build)** and click it: the side panel opens.
5. Click **Connect to Aura**. Aura opens `/aura/companion/connect`; sign in to Aura if asked, then **Connect the
   companion**. The side panel shows "Connected as …". The key lasts 12 hours; connect again after that.
6. On a site you want Aura to follow, click **Follow this site** and accept Chrome's prompt for that one site.
   A small "Aura is following" pill appears bottom-right with **Pause**.

The build talks to `https://aura-zero.onrender.com` (the Aura preview). For a local Hermes webapp on
`http://127.0.0.1:9119` behind the sign-in gate, pick it in the side panel's developer setting.

## What it does

- **Follow**: per-site opt-in using Chrome's optional host permissions. Nothing is read on a site until you follow it.
- **Context trail**: title, cleaned URL (no query string or fragment) and the start of the page's main text, redacted,
  kept only in this browser for 1 hour, 1 day (default) or 7 days. Delete one entry or everything from the side panel.
- **Insights / Ask**: sends the current page plus the titles of up to 10 recent pages to Aura. Hermes answers with one
  auxiliary model call under Aura's free-only model policy (`tools/aura_free_only.py`), capped per person per day.
  Nothing runs on a timer and nothing is stored on the server.
- **Take over**: you describe what you want; Aura proposes up to 8 steps (click, type, choose, scroll) on elements it
  can see; you review them and tap **Run**.

## Safety

- **Default deny list**: banking and payments, health, password managers, private mail and sign-in pages are blocked even
  if you follow them. You can remove an entry yourself; you still have to follow the site after that.
- **Never captured**: form field values, password, payment, PIN, one-time-code and credential fields. Keys, tokens, card
  numbers (Luhn-checked), IBANs and `password: …` pairs are redacted in the browser, and again on the server.
- **Untrusted page**: the server fences page text as data, never instructions, and doesn't store it.
- **Pause**: one tap on the pill or the side panel pauses capture everywhere.
- **Approval**: any click that sends, submits, posts, buys, pays, books or deletes waits for **Approve this step** in the
  side panel, and each approval covers that one step.
- **Stop**: the pill's **Stop**, the side panel's **Stop**, Esc, or navigating away ends the run; nothing runs after it.
- **CAPTCHA, verification codes and sign-in** hand the page back to you. Aura never solves or bypasses them, and finishing
  one approves nothing.
- **Auth**: a 12-hour HMAC key minted for your signed-in Hermes session, held in the extension's session storage
  (cleared when the browser closes). Never a password, and never accepted by any other Hermes route. Web pages can't use
  it: the ask route refuses any `Origin` that isn't a Chrome extension.

## Server switches (Hermes environment)

| Variable | Default | Effect |
| --- | --- | --- |
| `AURA_COMPANION_SECRET` | unset | 32+ characters. Unset means the companion is off for everyone |
| `AURA_COMPANION_ADMINS` | empty | Hermes user ids or emails, comma-separated |
| `AURA_COMPANION_TESTERS` | empty | named testers, comma-separated; same effect as admins |
| `AURA_COMPANION_TOKENS_NOT_BEFORE` | `0` | Unix seconds; every key issued earlier stops working (kill switch) |
| `AURA_COMPANION_DAILY_LIMIT` | `40` | model calls per person per UTC day |

The lists are read on every call, so removing a name revokes that person's key at once. Rotating the secret revokes
every key.

## Tests

- `node --test apps/aura-companion/tests/*.mts` (Node 22.6+ strips the types) for redaction, policy and take-over safety.
- `pytest tests/hermes_cli/test_aura_companion.py` for the server routes, gate and key.

## Provenance

Ported from the aura-agent companion (Melvinjayson/aura-agent PR #76). The token bridge pattern (same-window,
same-origin typed `postMessage` from Aura's page to a content script) and the per-site allow/deny idea come from
Melvin's own January Aura extension (`Melvinjayson/aura`, Melvin is the sole author). No third-party code is included.

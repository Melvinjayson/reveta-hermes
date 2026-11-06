#!/usr/bin/env python3
"""Reveta Hermes Preview smoke test: auth, session, WebSocket and PTY gates.

Runs the Phase 1 mandatory checks against a running dashboard (local or the
Render Preview). It never prints credentials, cookies, tickets or hashes.

Usage:
  REVETA_SMOKE_USERNAME=... REVETA_SMOKE_PASSWORD=... \
    python scripts/reveta/preview_smoke.py --base-url https://<preview>.onrender.com

Local emulation of Render's proxy (dashboard bound on 0.0.0.0:10000 with
HERMES_DASHBOARD_PUBLIC_URL set to the public origin):
  python scripts/reveta/preview_smoke.py --base-url http://127.0.0.1:10000 \
    --public-origin https://<preview>.onrender.com

Exit status is non-zero if any non-skipped check fails. A live model turn is
NOT attempted here: it needs provider credentials and is reported as a gate.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from urllib.parse import urlparse

import httpx

try:
    import websockets
except ImportError:  # pragma: no cover - reported as a skipped check
    websockets = None

PROTECTED_GET = ("/api/reveta/overview", "/api/sessions", "/api/config", "/api/auth/me")
RESULTS: list[tuple[str, str, str]] = []


def record(name: str, ok: bool | None, detail: str = "") -> None:
    status = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
    RESULTS.append((status, name, detail))
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""), flush=True)


class Target:
    def __init__(self, base_url: str, public_origin: str | None):
        self.base = base_url.rstrip("/")
        self.origin = (public_origin or self.base).rstrip("/")
        parsed = urlparse(self.origin)
        self.public_host = parsed.netloc
        self.emulated_proxy = public_origin is not None and public_origin != base_url
        headers = {"Origin": self.origin}
        if self.emulated_proxy:
            # What Render's edge forwards to the container.
            headers.update({"Host": self.public_host, "X-Forwarded-Proto": parsed.scheme,
                            "X-Forwarded-Host": self.public_host})
        self.headers = headers
        self.client = httpx.Client(base_url=self.base, headers=headers, timeout=20,
                                   follow_redirects=False)

    def ws_url(self, path: str) -> str:
        p = urlparse(self.base)
        scheme = "wss" if p.scheme == "https" else "ws"
        return f"{scheme}://{p.netloc}{path}"


def cookie_header(resp: httpx.Response) -> tuple[str, list[str]]:
    """Return a Cookie header built from Set-Cookie plus each cookie's attribute list."""
    pairs, attrs = [], []
    for raw in resp.headers.get_list("set-cookie"):
        first, *rest = [part.strip() for part in raw.split(";")]
        if "=" in first and first.split("=", 1)[1]:
            pairs.append(first)
            attrs.append(f"{first.split('=', 1)[0]}: " + ",".join(a.split("=")[0].lower() for a in rest))
    return "; ".join(pairs), attrs


def check_root_and_login_page(t: Target) -> None:
    r = t.client.get("/")
    record("anonymous root redirects to login", r.status_code in (302, 303, 307)
           and "login" in r.headers.get("location", ""), f"status={r.status_code}")
    r = t.client.get("/login")
    record("login page served", r.status_code == 200 and "<form" in r.text.lower(),
           f"status={r.status_code}")


def check_anonymous_api(t: Target) -> None:
    for path in PROTECTED_GET:
        r = t.client.get(path)
        record(f"anonymous GET {path} refused", r.status_code in (401, 403), f"status={r.status_code}")
    r = t.client.post("/api/auth/ws-ticket")
    record("anonymous ws-ticket mint refused", r.status_code in (401, 403), f"status={r.status_code}")


def check_bad_login(t: Target, username: str, password: str) -> None:
    wrong = password + "-wrong"
    r = t.client.post("/auth/password-login", json={"provider": "basic", "username": username,
                                                    "password": wrong, "next": "/"})
    leaked = wrong in r.text or password in r.text or "scrypt$" in r.text
    record("invalid login rejected", r.status_code in (400, 401, 403), f"status={r.status_code}")
    record("invalid login discloses no credential material", not leaked)
    record("invalid login sets no session cookie", not cookie_header(r)[0] or r.status_code >= 400)


def login(t: Target, username: str, password: str) -> str | None:
    r = t.client.post("/auth/password-login", json={"provider": "basic", "username": username,
                                                    "password": password, "next": "/"})
    cookies, attrs = cookie_header(r)
    record("valid login succeeds", r.status_code == 200 and bool(cookies), f"status={r.status_code}")
    if not cookies:
        return None
    secure_all = all("secure" in a for a in attrs)
    httponly_all = all("httponly" in a for a in attrs)
    expect_secure = urlparse(t.origin).scheme == "https"
    record("session cookies are HttpOnly", httponly_all, "; ".join(attrs))
    record("session cookies are Secure behind HTTPS", secure_all if expect_secure else None,
           "origin is https" if expect_secure else "origin is http; not applicable")
    return cookies


def check_authenticated(t: Target, cookies: str) -> str | None:
    h = {"Cookie": cookies}
    r = t.client.get("/api/auth/me", headers=h)
    record("session accepted on /api/auth/me", r.status_code == 200, f"status={r.status_code}")
    r = t.client.get("/", headers=h)
    is_spa = r.status_code == 200 and ('id="root"' in r.text or "<script" in r.text)
    record("authenticated root serves the real dashboard bundle", is_spa, f"status={r.status_code}")
    r = t.client.get("/api/reveta/overview", headers=h)
    ok = r.status_code == 200
    detail = f"status={r.status_code}"
    if ok:
        body = r.json()
        ok = body.get("mode") == "read_only" and body.get("brain", {}).get("state") == "not_connected"
        detail += f" registry_state={body.get('registry_state')}"
    record("Reveta overview is read-only and honest about Brain state", ok, detail)
    r = t.client.post("/api/auth/ws-ticket", headers=h)
    record("authenticated ws-ticket mint", r.status_code == 200, f"status={r.status_code}")
    return r.json().get("ticket") if r.status_code == 200 else None


async def _ws_try(t: Target, path: str, origin: str, read_seconds: float = 0.0) -> tuple[bool, int, str]:
    """Return (accepted, bytes_received, first_text_received)."""
    headers = {}
    if t.emulated_proxy:
        headers = {"Host": t.public_host, "X-Forwarded-Proto": urlparse(t.origin).scheme}
    try:
        async with websockets.connect(t.ws_url(path), origin=origin, additional_headers=headers,
                                      open_timeout=15, max_size=None) as ws:
            received, first = 0, ""
            deadline = time.monotonic() + read_seconds
            while time.monotonic() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.monotonic()))
                    received += len(msg)
                    if not first and isinstance(msg, str):
                        first = msg
                except (TimeoutError, websockets.ConnectionClosed):
                    break
            return True, received, first
    except Exception:
        return False, 0, ""


def check_websockets(t: Target, cookies: str, ticket: str | None) -> None:
    if websockets is None:
        record("WebSocket checks", None, "websockets package not installed")
        return
    accepted, *_ = asyncio.run(_ws_try(t, "/api/pty", t.origin))
    record("PTY WebSocket without ticket refused", not accepted)
    accepted, *_ = asyncio.run(_ws_try(t, "/api/pty?ticket=not-a-real-ticket", t.origin))
    record("PTY WebSocket with forged ticket refused", not accepted)

    h = {"Cookie": cookies}
    foreign = t.client.post("/api/auth/ws-ticket", headers=h).json().get("ticket")
    accepted, *_ = asyncio.run(_ws_try(t, f"/api/pty?ticket={foreign}", "https://attacker.invalid"))
    record("PTY WebSocket from foreign Origin refused (valid ticket)", not accepted)

    if not ticket:
        record("PTY WebSocket with valid ticket", None, "no ticket minted")
        return
    accepted, nbytes, first = asyncio.run(_ws_try(t, f"/api/pty?ticket={ticket}", t.origin, read_seconds=12))
    record("PTY WebSocket with valid ticket accepted", accepted)
    start_failed = "could not start" in first.lower() or "unavailable" in first.lower()
    detail = f"bytes={nbytes}" + (" — server reported the terminal child failed to start" if start_failed else "")
    record("PTY terminal child starts and streams output", accepted and nbytes > 0 and not start_failed, detail)
    accepted, *_ = asyncio.run(_ws_try(t, f"/api/pty?ticket={ticket}", t.origin))
    record("PTY ticket is single-use (replay refused)", not accepted)


def _read_token() -> str:
    """The deployment session token, read from a 0600 file so it never appears in argv or env dumps."""
    path = os.environ.get("REVETA_SMOKE_SESSION_TOKEN_FILE", "")
    if not path:
        return ""
    with open(path, encoding="utf-8") as fh:
        return fh.read().strip()


def check_auth_providers(t: Target) -> None:
    r = t.client.get("/api/auth/providers")
    names = []
    if r.status_code == 200:
        body = r.json()
        rows = body.get("providers", body) if isinstance(body, dict) else body
        names = sorted(str(p.get("name")) for p in rows if isinstance(p, dict))
    record("password login provider registered", "basic" in names, f"interactive providers={names}")


def check_token_api(t: Target, token: str) -> None:
    h = {"Authorization": "Bearer " + token}
    r = t.client.get("/api/auth/me", headers=h)
    record("session token accepted on /api/auth/me", r.status_code == 200, f"status={r.status_code}")
    r = t.client.get("/api/auth/me", headers={"Authorization": "Bearer " + token[:-4] + "xxxx"})
    record("altered session token refused", r.status_code in (401, 403), f"status={r.status_code}")
    for attempt in range(3):  # the state DB can answer 503 while it opens on a cold start
        r = t.client.get("/api/sessions", headers=h)
        if r.status_code != 503:
            break
        time.sleep(3)
    record("authenticated session list", r.status_code == 200, f"status={r.status_code}")


async def _rpc(ws, req_id: int, method: str, params: dict, timeout: float = 60) -> dict:
    await ws.send(json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=deadline - time.monotonic()))
        if msg.get("id") == req_id:
            return msg
    raise TimeoutError(method)


async def check_agent_session(t: Target, token: str, do_turn: bool) -> None:
    """Drive the same JSON-RPC gateway the dashboard chat uses: create a session, optionally run
    one turn whose correct answer (1729 + 2026 = 3755) cannot be produced by echoing the prompt."""
    headers = {"Host": t.public_host, "X-Forwarded-Proto": urlparse(t.origin).scheme} if t.emulated_proxy else {}
    try:
        async with websockets.connect(t.ws_url(f"/api/ws?token={token}"), origin=t.origin,
                                      additional_headers=headers, open_timeout=20, max_size=None) as ws:
            record("gateway WebSocket accepts session token", True)
            created = await _rpc(ws, 1, "session.create", {"title": "reveta-preview-smoke"})
            result = created.get("result") or {}
            sid = result.get("session_id")
            model = (result.get("info") or {}).get("model")
            record("agent session created", bool(sid), f"model={model}")
            if not sid:
                return
            if not do_turn:
                record("live model turn", None, "not requested (pass --agent-turn)")
                return
            submitted = await _rpc(ws, 2, "prompt.submit", {
                "session_id": sid, "text": "Reply with the word REVETA followed by the sum of 1729 and 2026."})
            status = (submitted.get("result") or {}).get("status")
            record("prompt accepted for streaming", status == "streaming", f"status={status}")
            provider, deltas, final, error_text = None, 0, "", ""
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=deadline - time.monotonic()))
                params = msg.get("params") or {}
                kind, payload = params.get("type"), params.get("payload") or {}
                if kind == "session.info":
                    provider = payload.get("provider")
                elif kind == "message.delta":
                    deltas += 1
                elif kind == "status.update" and str(payload.get("text", "")).startswith("❌"):
                    error_text = str(payload.get("text"))[:160]
                elif kind == "message.complete":
                    final = str(payload.get("text", ""))
                    break
            record("model streamed output tokens", deltas > 0, f"provider={provider} deltas={deltas}")
            ok = "3755" in final and not error_text
            record("live model turn produced a correct answer", ok,
                   error_text or ("answer contained 3755" if ok else f"final={final[:120]!r}"))
            # Hermes lists a session once it holds a message, so retrieval is checked after the turn.
            listed = t.client.get("/api/sessions", headers={"Authorization": "Bearer " + token})
            found = listed.status_code == 200 and str(result.get("stored_session_id")) in listed.text
            record("session with a turn is retrievable via REST", found, f"status={listed.status_code}")
    except Exception as exc:  # report the real failure, never a silent pass
        record("agent session checks", False, f"{type(exc).__name__}: {str(exc)[:160]}")


def check_logout(t: Target, cookies: str) -> None:
    h = {"Cookie": cookies}
    r = t.client.post("/auth/logout", headers=h)
    record("logout succeeds", r.status_code in (200, 204, 302, 303), f"status={r.status_code}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--public-origin", help="Emulate a proxy: send this Host/Origin to base-url")
    ap.add_argument("--skip-pty", action="store_true")
    ap.add_argument("--agent-turn", action="store_true",
                    help="Submit one real prompt through /api/ws (spends a few provider tokens)")
    args = ap.parse_args()
    username = os.environ.get("REVETA_SMOKE_USERNAME", "")
    password = os.environ.get("REVETA_SMOKE_PASSWORD", "")
    token = _read_token()
    t = Target(args.base_url, args.public_origin)

    check_root_and_login_page(t)
    check_auth_providers(t)
    check_anonymous_api(t)
    if not (username and password):
        record("password-login checks", None, "REVETA_SMOKE_USERNAME/PASSWORD not set")
    else:
        check_bad_login(t, username, password)
        cookies = login(t, username, password)
        if cookies:
            ticket = check_authenticated(t, cookies)
            if not args.skip_pty:
                check_websockets(t, cookies, ticket)
            check_logout(t, cookies)
    if not token:
        record("session-token checks", None, "REVETA_SMOKE_SESSION_TOKEN_FILE not set")
    else:
        check_token_api(t, token)
        if websockets is None:
            record("agent checks", None, "websockets package not installed")
        else:
            asyncio.run(check_agent_session(t, token, args.agent_turn))

    failed = [r for r in RESULTS if r[0] == "FAIL"]
    print(json.dumps({"pass": sum(r[0] == "PASS" for r in RESULTS), "fail": len(failed),
                      "skip": sum(r[0] == "SKIP" for r in RESULTS)}))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

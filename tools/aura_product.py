"""Opt-in Aura tool adapters. Capability stays at the edge of Hermes's tool loop.

These wrappers constrain inputs; execution belongs to the existing browser,
terminal and file adapters. Local workspace scoping is not OS containment.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import uuid

from hermes_constants import get_hermes_home
from tools.registry import registry

NAMES = frozenset({'aura_fetch', 'aura_browser', 'aura_file', 'aura_computer', 'aura_complex'})


def available():
    from tools.aura_dispatch_policy import _config
    return _config().get('aura', {}).get('enabled') is True


def owned_tool(name):
    return available() and name in NAMES | {'todo', 'todo_list'}


def workspace():
    from tools.approval_context import get_current_session_key
    key = get_current_session_key(default='')
    if not key:
        raise PermissionError('Aura needs an interactive conversation')
    name = hashlib.sha256(key.encode()).hexdigest()[:24]
    root = get_hermes_home().resolve() / 'aura-workspace' / name
    if root.parent.is_symlink() or root.is_symlink():
        raise PermissionError('Workspace symlinks are not allowed')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or not root.resolve().is_relative_to(get_hermes_home().resolve()):
        raise PermissionError('Workspace must remain inside HERMES_HOME')
    return root


def file_path(name):
    # A basename is enough for a brief; do not admit traversal, symlinks or hidden credentials.
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,119}', name):
        raise ValueError('Use a plain filename inside this conversation workspace')
    path = workspace() / name
    if path.is_symlink():
        raise PermissionError('Symlink targets are not allowed')
    return path


def classification(name, args):
    if name in {'aura_fetch', 'aura_browser', 'aura_complex'}:
        return 'read'  # complex has its own cost-bound, single-use approval below
    if name == 'aura_file':
        path = file_path(args.get('name'))
        return 'read' if args.get('action') == 'read' or not path.exists() else 'consequential'
    return 'consequential'


@contextmanager
def local_workspace():
    from tools.terminal_scope import get_terminal_scope, set_terminal_scope, reset_terminal_scope
    root = workspace()
    token = set_terminal_scope({**(get_terminal_scope() or {}), 'TERMINAL_ENV': 'local',
                                'TERMINAL_CWD': str(root)})
    try:
        yield root, 'aura-' + root.name
    finally:
        reset_terminal_scope(token)


def outcome(raw, **display):
    from agent.redact import redact_sensitive_text
    result = json.loads(raw) if isinstance(raw, str) else raw
    # Only server-redacted data is projected into progress cards.
    result['aura_display'] = json.loads(redact_sensitive_text(json.dumps(display), force=True))
    return json.dumps(result)


def file_tool(args, **_kw):
    from tools.file_tools import read_file_tool, write_file_tool
    path = file_path(args['name'])
    if args['action'] not in {'read', 'write'}:
        raise ValueError('Choose read or write')
    with local_workspace() as (_, task):
        if args['action'] == 'read':
            return read_file_tool(str(path), task_id=task)
        content = args.get('content', '')
        if len(content.encode()) > 100_000:
            raise ValueError('Keep chat files under 100 KB')
        raw = write_file_tool(str(path), content, task_id=task)
    result = json.loads(raw)
    if not result.get('error') and path.is_file():
        result.update(success=True, file={'path': str(path), 'name': path.name, 'bytes': path.stat().st_size})
    return outcome(result, summary=f"{args['action']}: {path.name}")


def computer_tool(args, **_kw):
    from tools.terminal_tool import terminal_tool
    with local_workspace() as (root, task):
        raw = terminal_tool(args['command'], task_id=task, workdir=str(root), timeout=60)
    result = json.loads(raw)
    return outcome(result, command=args['command'], summary=str(result.get('output', result.get('error', '')))[:3000])


def safe_url(url):
    from tools.url_safety import normalize_url_for_request, is_safe_url, sensitive_query_param_name
    from tools.browser_url_policy import evaluate_url_safety
    url = normalize_url_for_request(url)
    if sensitive_query_param_name(url) or not is_safe_url(url) or evaluate_url_safety(url):
        raise PermissionError('URL is private, sensitive or blocked by website policy')
    return url


def fetch_tool(args, **_kw):
    from tools.url_safety import create_ssrf_safe_client
    url = safe_url(args['url'])
    # No third-party extract service, credentials, redirects or paid add-ons.
    with create_ssrf_safe_client(timeout=25, follow_redirects=False, trust_env=False) as client:
        with client.stream('GET', url) as response:
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > 200_000:
                    break
            text = data[:200_000].decode('utf-8', errors='replace')
    parser = PageText()
    parser.feed(text)
    content = ' '.join(parser.parts)[:14000]
    return outcome({'success': True, 'url': url, 'content': content},
                   url=url, summary=content[:1800])


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'noscript'}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'noscript'}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


def browser_tool(args, **_kw):
    from tools.browser_use_cli import browser_exec
    from tools.browser_session_cloud import get_cloud_provider, use_real_profile
    from tools.browser_session_cdp import get_cdp_override_raw
    url = safe_url(args['url'])
    if get_cloud_provider() is not None or get_cdp_override_raw() or use_real_profile():
        raise PermissionError('Aura read-only browsing requires its isolated local Chromium')
    root = workspace()
    shot = root / ('page-' + uuid.uuid4().hex[:10] + '.png')
    # The model controls only a URL. No click, submit, arbitrary JS or Python surface.
    code = (f'new_tab({url!r})\nwait_for_load()\n'
            "print(js('JSON.stringify({url:location.href,title:document.title,text:document.body.innerText.slice(0,14000)})'))\n"
            + (f'capture_screenshot({str(shot)!r})\n' if args.get('screenshot', False) else ''))
    raw = browser_exec(code, session='aura-' + root.name, timeout_s=60, task_id='aura-' + root.name)
    if isinstance(raw, dict) and raw.get('_multimodal'):
        raw = raw['text_summary']
    result = json.loads(raw) if isinstance(raw, str) else raw
    output = str(result.get('output', ''))
    if shot.is_file() and not result.get('error'):
        result['file'] = {'path': str(shot), 'name': shot.name, 'bytes': shot.stat().st_size}
    return outcome(result, url=url, summary=output[:2400])


def complex_tool(args, **_kw):
    from tools.aura_spend import complex_workflow
    return complex_workflow(args)


def _register(name, description, properties, required, handler):
    registry.register(name=name, toolset='aura', check_fn=available, handler=handler,
                      schema={'name': name, 'description': description,
                              'parameters': {'type': 'object', 'properties': properties,
                                             'required': required, 'additionalProperties': False}})


_register('aura_fetch', 'Fetch a public URL as read-only text. No paid extraction service. Cite the returned URL.',
          {'url': {'type': 'string'}}, ['url'], fetch_tool)
_register('aura_browser', 'Navigate/read a public page with real isolated headless Chromium; optionally capture a screenshot. Read only. Cite sources; report failures honestly.',
          {'url': {'type': 'string'}, 'screenshot': {'type': 'boolean'}}, ['url'], browser_tool)
_register('aura_file', 'Read or create a file in this conversation workspace using Hermes file tools. Creation is direct; overwrites ask. Return the File card. For research write brief.md with real citations.',
          {'name': {'type': 'string'}, 'action': {'type': 'string', 'enum': ['read', 'write']},
           'content': {'type': 'string'}}, ['name', 'action'], file_tool)
_register('aura_computer', 'Run a terminal command or code on the cloud host in this conversation workspace using Hermes terminal. Every command requires single-use approval, including installs, network writes and deletes. Prefer aura_file for direct reads/creation.',
          {'command': {'type': 'string'}}, ['command'], computer_tool)
_register('aura_complex', 'Opt-in Anthropic reasoning for a complex task, NEVER an automatic fallback. Only request when the user asks for Anthropic. Disabled without positive per-chat/day caps and an approval card showing estimated cost. Include all relevant conversation context in task.',
          {'task': {'type': 'string'}, 'max_output_tokens': {'type': 'integer', 'minimum': 1, 'maximum': 4096}},
          ['task'], complex_tool)

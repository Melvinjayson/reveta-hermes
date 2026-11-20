# Hermes capabilities available to Aura Zero — inventory

Branch `claude/aura-redesign-v1` (draft PR #17), based on `e7882138`. Written
18 Nov 2026 from the repository itself; every row names the file that proves it.
"Aura today" means the Aura webapp on the base commit. This is an inventory, not a
claim that anything below works in Aura yet; build status is tracked in the PR.

## The one fact that shapes everything

Hermes has a large capability set, but **Aura's runtime offers the model almost
none of it.** `scripts/reveta/aura_config.py` sets
`platform_toolsets = ["aura", "todo", *mcp]`, and
`tools/aura_free_only.py::advertised_tools` hides every tool that is not an
Aura-owned adapter (`tools/aura_product.py`: `aura_fetch`, `aura_browser`,
`aura_file`, `aura_computer`, `aura_complex`), `todo`, or an `mcp_*` tool from a
configured MCP server. Memory, skills, scheduled jobs, subagents, conversation
search, vision and the rest exist in this repo but are switched off for Aura.

Approvals are unaffected by unlocking: `tools/aura_dispatch_policy.py` treats any
tool not on its explicit read list (`read_file`, `search_files`, `skills_list`,
`skill_view`, `session_search`, `web_extract`, …) or internal list (`todo`) as
**consequential**, which needs a single-use manual approval. There is no YOLO,
mode or missing-config bypass. `approvals.cron_mode`, `unattended_mode` and
`single_query_mode` are all `deny`.

## Persistence on Render free (applies to every stateful row)

`docs/aura/HANDOFF.md` § Persistence: Render free storage is ephemeral. A restart
or redeploy can lose `$HERMES_HOME`: `state.db` (chats and search index),
`memories/`, `skills/`, `cron/`, `projects.db`, `uploads/`, conversation
workspaces, saved provider keys (`.env`) and the spend ledger. Rows marked
**Ephemeral on free host** depend on Melvin's hosting decision.

## Inventory

| # | Capability | Evidence (files) | Backend API the webapp can call | Aura today | Needs a key / cost | Ephemeral on free host |
|---|---|---|---|---|---|---|
| 1 | **Core toolsets** (60 toolsets in `TOOLSETS`; `_HERMES_CORE_TOOLS` lists 40 tools) | `toolsets.py`, `model_tools.py`, `tools/registry.py` | `GET /api/tools/toolsets`, `GET /api/tools/toolsets/{name}/config` (`hermes_cli/web_routers/tools.py`) | Only `aura` + `todo` + MCP | Varies by tool | n/a (config) |
| 2 | **Aura adapters**: fetch, read-only headless browser, conversation files, workspace commands, Anthropic complex workflow | `tools/aura_product.py`, `tools/aura_spend.py` | via chat | **On** | `aura_complex` needs an Anthropic key and caps | Workspace files: yes |
| 3 | **Full browser tool** (navigate, click, type, CDP, dialogs, vault) | `tools/browser_tool.py`, `tools/browser_use_cli.py`, `tools/browser_cdp_tool.py`, `tools/browser_dialog_tool.py`, `tools/browser_vault_tool.py` | via chat | Off (Aura's browser is read-only by design) | Free (local Chromium); memory fit on 512 MB not measured | Profile cache: yes |
| 4 | **Terminal, processes, code execution** | `tools/terminal_tool.py`, `tools/process_registry.py`, `tools/code_execution_tool.py` | via chat | `aura_computer` only (approval each time) | Free | Workspace: yes |
| 5 | **Files: read / write / patch / search** | `tools/file_tools.py` | `GET /api/files`, `/api/files/read`, `/api/files/download`, `/api/files/stream` (`hermes_cli/web_routers/files.py`, `hermes_cli/web_server_files.py`) | `aura_file` only | Free | yes |
| 6 | **Uploads** (files, images, PDFs) | `hermes_cli/web_routers/uploads.py` (`/api/chat/file-upload`, `/api/chat/image-upload`), `tools/read_extract.py` (PDF/text extraction) | as listed | **On** via the composer + menu | Free | `uploads/`: yes |
| 7 | **File and PDF preview** | `apps/desktop/src/app/chat/right-rail/preview-file.tsx`, `apps/desktop/src/store/preview.ts`, `apps/desktop/src/app/right-sidebar/` | `/api/files/read`, `/api/fs/read-data-url` | Not surfaced in Aura (desktop right rail only) | Free | — |
| 8 | **Artifacts list** | `apps/desktop/src/app/artifacts/index.tsx` | session messages | Not surfaced | Free | yes |
| 9 | **Memory** (personal notes + user profile; pluggable providers) | `tools/memory_tool.py`, `agent/memory*.py`, `plugins/memory/` | `GET /api/memory`, `POST /api/memory/reset`, `PUT /api/memory/provider` (`hermes_cli/web_routers/memory_providers.py`) | Off | Built-in provider free; external providers need keys | **yes** |
| 10 | **Skills** (45 bundled under `skills/`, 142 optional under `optional-skills/`; create/edit) | `tools/skills_tool.py`, `tools/skill_manager_tool.py`, `skills/`, `agent/curator.py` | `GET /api/skills`, `GET /api/skills/content`, `POST /api/skills`, `/api/curator` (`hermes_cli/web_routers/skills.py`) | Off | Free | Created skills: **yes** |
| 11 | **Scheduled jobs (cron)** | `cron/jobs.py`, `cron/scheduler.py`, `tools/cronjob_tools.py`, `gateway/session_cron.py` (ticker inside the gateway) | `GET/POST /api/cron/jobs`, `PUT/DELETE /api/cron/jobs/{id}`, pause / resume / trigger / runs (`hermes_cli/web_routers/cron.py`) | Off | Model cost per run; `cron_mode: deny` refuses consequential tools unattended | **yes** |
| 12 | **MCP servers** (+ catalog of optional servers in `optional-mcps/`) | `tools/mcp_tool.py`, `tools/mcp_oauth.py`, `optional-mcps/` | `GET/POST/PUT /api/mcp/servers`, `/api/mcp/catalog`, `/api/mcp/servers/{name}/test`, OAuth flows (`hermes_cli/web_routers/mcp.py`) | Composio only, when its key is set | Server-dependent | Config: **yes** |
| 13 | **Composio Connect** | `scripts/reveta/aura_config.py` (`COMPOSIO_MCP_URL`, `mcp_settings`, workbench/bash tools excluded) | as MCP | On only with `COMPOSIO_API_KEY` | **Needs key → BLOCKED here** | Key: **yes** |
| 14 | **Connectors / connections** (account status, authorization links) | `tools/connectors/` (`catalog.py`, `dispatch.py`, `account.py`), `tools/managed_tool_gateway.py` (`manage_connections`) | via chat; desktop UI `apps/desktop/src/app/capabilities/connectors/` | Off | Provider accounts | yes |
| 15 | **Subagents** (delegate a subtask with isolated context; async workers) | `tools/delegate_tool.py` (+ `delegate_tool_*.py`), `tools/async_delegation.py`, `apps/desktop/src/store/subagents.ts`, `apps/desktop/src/app/agents/index.tsx` | `GET /api/delegation/routing`, `PUT /api/delegation/backend` (`hermes_cli/web_routers/delegation.py`); progress via chat events | Off | Each subagent is extra model usage | In-flight work: not durable |
| 16 | **Background processes** | `tools/process_registry.py` (`process_manage`) | via chat | Off | Free | not durable |
| 17 | **Todo / plan tracking** | `tools/todo_tool.py` | via chat | **On** | Free | yes |
| 18 | **Kanban multi-agent board** | `tools/kanban_*`, `hermes_cli/kanban_db.py` | — | Off (only for spawned board agents) | Model usage | yes |
| 19 | **Model and provider switching** | `hermes_cli/web_routers/models.py` (`/api/model/options`, `/api/model/set`, `/api/model/info`), `tools/aura_provider.py`, `hermes_cli/web_routers/aura.py` (`/api/aura/provider`) | as listed | Aura Settings → Model (OpenAI / Anthropic key + daily and per-chat caps; Gemini free tier) | Paid routes need keys | Saved keys: **yes** |
| 20 | **Search across message text** | `hermes_state_search.py`, `hermes_state_fts.py` (SQLite FTS), `hermes_cli/web_routers/sessions.py` (`GET /api/sessions/search`), `tools/session_search_tool.py` | as listed | Not surfaced (Aura search filters titles) | Free | Index lives in `state.db`: **yes** |
| 21 | **Projects** (named workspaces with folders) | `hermes_cli/projects_db.py` (`$HERMES_HOME/projects.db`), `tui_gateway/methods_projects.py` (`projects.list/create/archive/…`), `hermes_cli/web_routers/chat_workspaces.py` | JSON-RPC `projects.*`; `GET /api/chat/workspaces` | Not surfaced; every Aura chat gets its own workspace under `aura-workspace/` (`tools/aura_product.py::workspace`) | Free | **yes** |
| 22 | **Web search** | `tools/web_tools.py` | via chat | Off | Every backend needs a key (Tavily, Exa, Brave, Firecrawl, Perplexity…); `ddgs` is free but not in the `[all]` extra the image installs → **BLOCKED** | — |
| 23 | **Vision (image understanding)** | `tools/vision_tools.py` | via chat | Off | Uses the main model if it supports images | — |
| 24 | **Image generation** | `tools/image_generation_tool.py` | via chat | Off | Needs FAL or another paid key → **BLOCKED** | — |
| 25 | **Text-to-speech / voice** | `tools/tts_tool.py`, `tools/aura_voice_call.py`, `apps/desktop/src/app/aura/voice-call.tsx`, `browser-voice.tsx` | `/api/aura/voice`, `/api/audio/*` | **On** (current voice stays default) | Gemini free tier; OpenAI speech metered | — |
| 26 | **Clarifying questions** | `tools/clarify_tool.py` | via chat | Off | Free | — |
| 27 | **Computer use** (desktop control via cua-driver) | `tools/computer_use_tool.py` | `/api/tools/computer-use/status` | Off | Needs a desktop; not applicable on a headless server | — |
| 28 | **Checkpoints / rewind, backup and import** | `hermes_state_rewind.py`, `hermes_cli/web_routers/ops.py` (`/api/ops/checkpoints`, `/api/ops/backup`, `/api/ops/import`) | as listed | Not surfaced | Free | Backup is the manual mitigation for the free host |
| 29 | **Usage and analytics** | `hermes_cli/web_routers/analytics.py` (`/api/analytics/usage`, `/api/analytics/models`), `tools/aura_spend.py` | as listed | Spend shown in Settings → Model | Free | Ledger: **yes** |
| 30 | **Profiles** (separate identities) | `hermes_cli/web_routers/profiles.py` | `/api/profiles*` | Not surfaced | Free | yes |
| 31 | **Messaging gateways** (Telegram, Slack, Discord, WhatsApp, email …) | `gateway/platforms/`, `hermes_cli/web_routers/messaging.py` | `/api/messaging/*` | Not surfaced | Platform credentials | yes |
| 32 | **Learning graph** | `hermes_cli/web_routers/status.py` (`/api/learning/graph`) | as listed | Not surfaced | Free | yes |

## What the build steps will surface (and what they will not)

In scope for steps 4–7, in line with Melvin's instruction:

- **Composer + menu**: Attach (existing), plus tool and mode toggles that map to the real
  toolsets above. Each toggle changes the toolsets for the *next* conversation, not the
  current one: changing tools mid-chat breaks the cached prompt prefix (root `AGENTS.md`
  invariant).
- **Projects view**: backed by `projects.db`, with conversations started inside a project's
  own workspace folder.
- **Side panel**: conversation files and artifacts, with text and PDF preview from the
  existing file-read endpoints.
- **Work view**: steps, subagents and background processes from the existing chat events.
- **Settings**: Model and provider (existing), Memory, Skills, Scheduled jobs, Connectors (MCP).
- **Search**: message-text search through `/api/sessions/search`.

Deliberately not surfaced: messaging gateways, profiles, kanban, computer use (headless
server), auth and sign-in. Capabilities that need a key (web search, image generation,
Composio, external memory providers, paid models) are built switched off and labelled
BLOCKED until Melvin adds a key himself.

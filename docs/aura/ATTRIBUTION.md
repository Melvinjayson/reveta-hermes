# Attribution

Aura Zero is Reveta's voice-first operator. It is built on **Hermes Agent** by Nous Research
(https://github.com/NousResearch/hermes-agent), used under the MIT License.

- The upstream licence and copyright notice ("Copyright (c) 2025 Nous Research") are kept unchanged in
  [`LICENSE`](../../LICENSE) at the repository root, and must ship with any copy or substantial portion of this code.
- Aura's own identity (`scripts/reveta/aura_config.py`, `AURA_SOUL`) replaces the stock Hermes persona in the
  running product only. It does not remove or alter the upstream notice. When a user asks what Aura runs on, Aura
  says it is built on the open-source Hermes Agent by Nous Research.
- Third-party packages keep their own licences (see `pyproject.toml`, `uv.lock` and `apps/desktop/package.json`).

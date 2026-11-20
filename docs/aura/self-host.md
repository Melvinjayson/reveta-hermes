# Aura on an always-on host (decision E: option B on Oracle Always Free, Arm)

Status: **instructions only. Nothing is provisioned, deployed or bought.** Melvin creates the Oracle
account, verifies the card and creates the VM himself; every command below runs on that VM, by him or
with his approval. Written 19 Nov 2026 on `claude/aura-self-host` (stacked on #23). Vendor limits
quoted are from `docs/aura/persistence-options.md` (Oracle pages read 18 Nov 2026); recheck them first.

Labels: **PASSED** (ran here), **UNVERIFIED** (not run), **BLOCKED** (needs something this session may not have).

## 1. What was and was not verified

| Claim | Status | Evidence |
|---|---|---|
| The Dockerfile supports arm64 | **PASSED (static)** | `ARG TARGETARCH` with an explicit `arm64` branch for s6-overlay (`Dockerfile` ~l.135–145); Chromium resolved per arch (~l.201) |
| Every pinned PM tool has a linux-arm64 artifact | **PASSED (static)** | `pm/lock.json`: 15 of 15 Linux tools; the only x64-only entry is `llamacpp-hip` (AMD GPU, unused by Aura) |
| An arm64 image builds | **BLOCKED here** | no Docker daemon in this container and no binfmt/QEMU for emulation. This repo's CI skips its image-build jobs. **Building on the A1 VM is native arm64 and needs no emulation**, so step 4 is the first real test |
| The image runs Aura on arm64 | **UNVERIFIED** | first run on the VM; step 6 is the acceptance check |
| Data survives a restart | Design: `$HERMES_HOME=/opt/data` is the image's `VOLUME`; with a host folder mounted there nothing is restored, it is simply still there. #20 keeps owner settings across the boot step |
| Full-duplex voice on the VM | **Not possible with the current image** | the voice runtime (`.voice-runtime`) is not baked in (PR #16 reverted PR #11's Dockerfile hunks). Needs Melvin's approval for a Dockerfile change. Browser voice works without it |

## 2. Size the VM (Melvin)

Always Free on Ampere A1 allows 2 OCPU / 12 GB in total and 200 GB of block storage.

| Choice | Value | Why |
|---|---|---|
| Shape | `VM.Standard.A1.Flex`, **1 OCPU, 6 GB** | leaves headroom in the free pool; 6 GB covers the server (~480 MiB on Render), the browser tool and, later, full duplex (~273 MiB measured by PR #16) |
| Image | Ubuntu 24.04 (aarch64) or Oracle Linux 9 (aarch64) | Docker's official packages exist for both |
| Boot volume | 50 GB | the image build needs room (layers, Node, Chromium) |
| Data | the boot volume is enough to start; a separate block volume (e.g. 50 GB) mounted at `/srv/aura-data` makes the data independent of the VM | within the 200 GB free |
| Network | public subnet, **ingress 22 only** at first | 80/443 are opened in step 5 only if Melvin picks a public address |

**Idle reclamation.** Oracle may reclaim an Always Free instance whose CPU, network *and* memory all
stay under 20% (95th percentile) for 7 days. A small VM makes the memory threshold easier to stay
above. Do not run synthetic load to dodge the rule; if Aura is quiet for a week, accept the risk (the
data volume survives a reclaimed instance if it is a separate block volume) or keep the weekly backup (§7).

## 3. Prepare the VM (Melvin, by SSH)

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl git
```

```bash
curl -fsSL https://get.docker.com -o get-docker.sh && less get-docker.sh   # read it, then:
sudo sh get-docker.sh && sudo usermod -aG docker "$USER"
```

```bash
sudo mkdir -p /srv/aura-data /srv/aura-secrets && sudo chmod 700 /srv/aura-secrets
```

## 4. Build the image natively (arm64)

The repository is private, so clone with Melvin's own GitHub credential (a deploy key or `gh auth login`).
Build the exact commit that was tested and approved, never a moving branch:

```bash
git clone https://github.com/Melvinjayson/reveta-hermes.git ~/reveta-hermes
```

```bash
cd ~/reveta-hermes && git checkout <approved-commit-sha>
```

```bash
docker build -t aura:<approved-commit-sha> .
```

Expect tens of minutes on 1 OCPU (the Dockerfile notes a frontend step takes ~222 s on arm64). If the
build fails, keep the log and stop: that is the arm64 finding this step exists to produce.

## 5. Secrets and the public address

**Secrets** go in a root-only file outside the repository and are never pasted into chat:

```bash
sudo install -m 600 /dev/null /srv/aura-secrets/aura.env && sudo nano /srv/aura-secrets/aura.env
```

Contents, the same names Render uses (`docs/aura/HANDOFF.md` § Render):

```text
HERMES_DASHBOARD_BASIC_AUTH_USERNAME=<as on Render>
HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=<Melvin enters it>
GEMINI_API_KEY=<optional, free-tier project>
COMPOSIO_API_KEY=<optional>
```

**Public address** (an access change, so Melvin decides). Either:

- **A. Cloudflare Tunnel** (no inbound port opened; free): `cloudflared` on the VM forwards
  `https://<name>.<domain>` to `http://127.0.0.1:10000`. Needs a Cloudflare account and a domain.
- **B. Domain + Caddy** (automatic TLS): open 80/443 in the Oracle security list and the VM firewall,
  and run Caddy with `reverse_proxy 127.0.0.1:10000`.

Either way the address must be set in **`AURA_PUBLIC_URL`** (#20). It pins the webapp's Origin check
and sign-in callback; a malformed value stops the boot on purpose. Also set
`HERMES_DASHBOARD_PUBLIC_URL` to the same value, as on Render.

## 6. Run

```bash
docker run -d --name aura --restart unless-stopped \
  -p 127.0.0.1:10000:10000 \
  -v /srv/aura-data:/opt/data \
  --env-file /srv/aura-secrets/aura.env \
  -e HERMES_HOME=/opt/data -e PORT=10000 -e HERMES_YOLO_MODE=0 \
  -e AURA_PUBLIC_URL=https://<your-address> -e HERMES_DASHBOARD_PUBLIC_URL=https://<your-address> \
  aura:<approved-commit-sha> \
  /bin/sh -c '/opt/hermes/.venv/bin/python /opt/hermes/scripts/reveta/aura_config.py --write "$HERMES_HOME/config.yaml" && exec /opt/hermes/docker/entrypoint-dispatch.sh gateway run'
```

The command is the Render start command, unchanged. Port 10000 is bound to loopback only; the tunnel
or Caddy is the only way in.

**Acceptance** on the VM, in order:

1. `docker logs aura` shows the gateway listening and no traceback.
2. `curl -sS http://127.0.0.1:10000/api/health` answers without sign-in (it is in `PUBLIC_API_PATHS`).
3. From a phone: the sign-in gate appears at the public address; sign in; one chat with the free model.
4. Restart test: in Settings set a Tools switch and Settings → Voice, write one chat, then
   `docker restart aura`. The chat, the switches and `aura.clarify_without_approval` must still be there.
5. Optional, from a laptop: `scripts/reveta/aura_browser.py` against the public address (fake-model
   scenarios need a local gateway, so this is a manual pass of the same steps).

## 7. Upgrade, rollback, backup

- **Upgrade:** build the next approved commit as a new tag, `docker stop aura && docker rm aura`,
  run step 6 with the new tag. The data folder is untouched.
- **Rollback:** the same with the previous tag (keep the last two images).
- **Backup (weekly, plus before every upgrade):** stop briefly so SQLite files are consistent:

  ```bash
  docker stop aura && sudo tar -C /srv -czf ~/aura-data-$(date +%F).tgz aura-data && docker start aura
  ```

  The archive contains `.env` (provider keys) and chats. Keep it encrypted and off the VM (for
  example `gpg -c` before copying). Oracle block-volume backups are an alternative; check their free allowance.

## 8. Migration in (Render → Oracle)

1. Freeze: announce a short window; nothing new is written on Render.
2. On Render's Aura, signed in: download a backup with the existing ops route
   (`/api/ops/backup`; see `hermes_cli/web_routers/ops.py`). On Render free a spin-down wipes the disk,
   so do this while the service is up and right after use.
3. On the VM, after step 6: import it (`/api/ops/import`), then repeat acceptance check 4.
4. Provider keys are not copied by hand through chat; Melvin re-enters them in Settings or in `aura.env`.
5. Leave Render running as a demo or retire it (Melvin's call); its address is no longer `AURA_PUBLIC_URL`.

What does not migrate: running turns, pending approvals, background processes (same as any restart).

## 9. Exit plan (leaving Oracle)

Everything Aura needs is one image (rebuildable from the repo) plus one folder.

1. Final backup (§7) and copy it off the VM.
2. On any Docker host with ≥1 GB RAM (any architecture: rebuild there), run step 6 with that folder
   restored to its data path, and the new `AURA_PUBLIC_URL`.
3. Point the tunnel or DNS at the new host; then terminate the Oracle VM and its volumes.

If Oracle reclaims or suspends the instance unexpectedly: a separate block volume can be attached to a
new VM; without one, restore the latest backup. Data written since the last backup is lost; that is the
real loss window of this design.

## 10. Full-duplex voice on this host (optional, needs approval)

Needs, on the server: the `.voice-runtime` venv
(`python -m pm.build_env --source hermes_cli/aura_voice_runtime --out .voice-runtime --no-install-project`)
and an ffmpeg **with the `flite` filter** (Debian's has it; the PM-managed ffmpeg 9.0.1 does not, and
#23 now reports the runtime unavailable in that case rather than starting silently). Baking both into
the image is a Dockerfile change, outside the current rules. Until Melvin approves one, leave
Settings → Voice → Full-duplex off; the browser voice is the default either way.

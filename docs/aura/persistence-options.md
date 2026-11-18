# Making Aura survive a restart — options at €0

Decision memo, no code. Branch `claude/aura-persistence-notes`, stacked on
`claude/aura-redesign-v1` (#17). Researched 18 Nov 2026 from the vendors' own pages (links at the
end). Prices and limits change; recheck them on those pages before acting.

## Recommendation

**Choose B (the same image on an always-on host with a mounted `$HERMES_HOME`), on a host Melvin
controls. Keep Render free only as a demo that is allowed to forget.** A is possible at €0 but is
fragile on Render free, for one reason the original framing missed: Render free does not lose
files only on redeploys. **It wipes the local filesystem every time the service spins down after
15 minutes without traffic.** A would have to restore everything on almost every visit, which runs
into Supabase's free egress, file-size and pause limits.

Whichever option is chosen, one #17 fix is needed first (see "Applies to both").

## What has to survive

Everything Aura stores lives under `$HERMES_HOME` (`/opt/data` in the image; `Dockerfile`
`ENV HERMES_HOME=/opt/data`):

| Data | Where | Kind |
|---|---|---|
| Chats, message search index, sessions | `state.db` (+ `-wal`, `-shm`) | SQLite, FTS5 |
| Projects and Aura project membership | `projects.db` | SQLite |
| Kanban (unused by Aura) | `kanban.db` | SQLite |
| Memory | `memories/MEMORY.md`, `memories/USER.md` | files |
| Created and edited skills | `skills/` | folders |
| Scheduled jobs | `cron/jobs.json` (+ run output) | files |
| Settings, owner tool switches, paid route | `config.yaml` | file |
| Saved provider keys | `.env` | **secrets** |
| Spend ledger | `aura-spend.db` (`tools/aura_spend.py`) | SQLite |
| Conversation files, uploads | `aura-workspace/`, `uploads/` | files |

## Facts that decide this (vendor pages, 18 Nov 2026)

**Render free web service** (render.com/docs/free, render.com/docs/disks):
- Spins down after 15 minutes without inbound traffic. Spinning back up takes about a minute.
- "Whenever a service spins down, any changes to its local filesystem are lost." The same happens on every redeploy and restart, and "Render might restart a Free web service at any time".
- Persistent disks are paid-only: "Free web services cannot" attach one.
- Render may suspend a free service that "initiates an uncommonly high volume of traffic", for example "transferring data to or from external object storage".
- Free Render Postgres expires 30 days after creation.

**Supabase Free** (supabase.com/pricing, docs/guides/platform/free-project-pausing, docs/guides/storage/s3/compatibility):
- Limits: 1 GB file storage; 5 GB egress plus 5 GB cached egress a month; **50 MB maximum file upload size**; no automatic backups; 2 active projects.
- Pausing: "A Free plan project is considered inactive if it does not receive sufficient **user database activity** over the past week … Typically a few user requests to the database each day … is enough." Storage-only traffic is not said to count. A paused project can be restored from the dashboard for up to 1 year.
- S3 protocol: PutObject, GetObject, ListObjectsV2, DeleteObject(s), CopyObject and multipart uploads are implemented. **No object versioning** ("Deleted objects are permanently removed"). No Content-MD5.

**Litestream** (litestream.io/guides/s3-compatible): continuous SQLite replication to S3. From v0.5.9 it auto-detects Supabase Storage (`<ref>.supabase.co/storage/v1/s3`, path-style, signed payloads). Documented as supported; **not tested here**.

**Oracle Cloud Always Free** (docs.oracle.com, Always Free Resources and Free Tier):
- Compute: 1,500 OCPU-hours and 9,000 GB-hours a month on Ampere A1 (Arm). That is 2 OCPUs and 12 GB of memory running all month.
- Storage: 200 GB of block volume.
- Reclamation: "Idle Always Free compute instances may be reclaimed". Idle means that over 7 days, 95th-percentile CPU, network *and* memory use are all under 20%.
- Instances are deleted only if the tenancy is over 2 OCPUs / 12 GB when the trial ends.

## Option A — continuous SQLite replication plus periodic file backup to S3-compatible storage

**How it would work:**
- On boot, before the gateway starts: `litestream restore` for `state.db` and `projects.db`, then download and unpack a tarball of the other files.
- While running: `litestream replicate` streams each SQLite change about once a second. A timer re-uploads the file tarball (for example every 5 minutes) and on shutdown.

**Supabase Storage as the target: possible, with five problems on the free plan:**
1. **Pausing.** Backup traffic is storage, not "user database activity", so the project can pause after a week. Restore would then fail at boot. Keeping it awake needs a daily database query, which means a second credential and a scheduled call.
2. **Egress versus spin-downs.** Every spin-up restores the whole state. At, say, 30 MB per restore and 20 cold starts a day, that is about 18 GB a month, over the 5 GB free egress. This is an estimate; the real number depends on usage.
3. **50 MB per object.** Litestream snapshots of `state.db` grow with chat history, and could pass 50 MB. Not tested.
4. **No versioning.** A bad or empty replica can overwrite good data with no undo. A boot that fails to restore must refuse to start, not start empty and replicate the emptiness.
5. **Render's outbound-traffic suspension.** Constant replication traffic is the pattern Render says may get a free service suspended.

| | |
|---|---|
| **Survives a restart** | SQLite data up to about the last second. Files up to the last tarball. Running turns, live approvals and background processes are lost either way. |
| **Data-loss window** | About 1 s for SQLite (if Litestream gets to flush at shutdown; a hard kill loses the unsynced tail). Up to one tarball interval for files (for example 5 minutes). Anything since the last successful sync if Supabase is paused or unreachable. |
| **Monthly cost** | €0 within Supabase Free limits, which item 2 above suggests normal use would exceed. Supabase Pro is $25 a month (above the ~€20 ceiling). Another S3 provider would mean a new account and new pricing to check. |
| **Cold start** | Render's ~1 minute spin-up plus the restore time on every visit after idle. |
| **Secrets** | `.env` holds provider keys, so it must not go into the tarball in plain form. Either set keys as Render environment variables (Melvin, in the Render dashboard), or encrypt the tarball with a key that also lives only in Render. |
| **Repo changes (currently forbidden files marked ⛔)** | ⛔ `Dockerfile` (install a pinned Litestream binary; add an s6 service). ⛔ `docker/s6-rc.d/` (new long-running `litestream replicate` service plus a backup timer). ⛔ `docker/stage2-hook.sh` or a new `docker/cont-init.d/` script (restore before the gateway, refuse to start on a failed restore). ⛔ **Render start command** (dashboard setting, `docs/aura/HANDOFF.md` §Render: `aura_config.py --write … && exec entrypoint-dispatch.sh gateway run`), if restore must run before `aura_config.py`. New `litestream.yml` and a backup script (new files, not forbidden). Tests: a restore/replicate round trip against a local S3 (for example MinIO in a test), plus a "refuse to boot on failed restore" test. |
| **Melvin decides** | (1) Lift the Dockerfile / startup / Render rule for this change. (2) Create a Supabase project (or other S3 provider), make a bucket and S3 keys, and put them in Render's environment himself. (3) Accept the pause risk or add a keep-alive query. (4) Where provider keys live (Render env vs encrypted backup). (5) Accept the egress risk, or keep the service warm (which uses free instance hours and is itself traffic). |

## Option B — the same image on an always-on host with a mounted `$HERMES_HOME`

**How it would work:** `docker build` the existing image on the host, then
`docker run -v /srv/aura-data:/opt/data -p 443…`. The image already treats `/opt/data` as its
mutable volume (`Dockerfile` comments; `docker/stage2-hook.sh` already chowns it on every boot).
Nothing has to be restored: the files are simply still there.

**Host at €0:** Oracle Cloud Always Free, Ampere A1 (Arm). For example 1–2 OCPUs and 6–12 GB of
memory on a 50–100 GB block volume, within the 200 GB free. The `Dockerfile` is multi-arch
(`TARGETARCH` arm64 handled; `pm/lock.json` lists arm64 artifacts). **An arm64 build has not been
tried here.** The alternative €0 host is a machine Melvin already keeps on, reached through a free
tunnel.

| | |
|---|---|
| **Survives a restart** | Everything under `/opt/data`: chats and search, projects, memory, skills, jobs, settings, keys, ledger, files. Running turns, live approvals and background processes are still lost, as in A. |
| **Data-loss window** | None for a restart, redeploy or reboot (the disk persists). Loss only if the disk or VM is lost. Mitigation: Oracle block-volume backups (check their free allowance) or a nightly copy, which can be added later. |
| **Monthly cost** | €0 within Always Free. Oracle sign-up needs a card for identity, and there is no charge if you stay within Always Free shapes. A domain is optional (free tunnel URLs exist). |
| **Main risks** | (1) **Idle reclamation:** a quiet Aura could fall under 20% CPU, network and memory for 7 days. Sizing the VM small (for example 1 OCPU / 6 GB) makes the memory threshold easier to stay above, but this is unverified. (2) Arm build untested. (3) The host's OS updates and TLS become ours to maintain. (4) A tunnel or public IP is an access change. |
| **Repo changes (⛔ = currently forbidden)** | **None required for persistence itself.** For a new host: `scripts/reveta/aura_config.py` hard-codes `public_url: https://aura-zero.onrender.com`, which feeds the webapp's Origin checks. It needs to come from an environment variable, or the new host's URL. ⛔ Borderline: this script runs in the Render start command and touches a security input (the Origin allowlist value, not its logic). Plus a new `docs/aura/self-host.md` with the exact `docker build`/`docker run` commands. Not touched: `Dockerfile`, `docker/*`, auth. The Render service can stay as is, or be retired; Melvin's call. |
| **Melvin decides** | (1) Which host: Oracle Always Free, or his own always-on machine. (2) Creating the account and VM (a card for identity) — his action, not mine. (3) The public address: a free tunnel or a domain, and therefore an access change. (4) Whether Aura on Render keeps running as a demo, and whether its data should be copied over once (manual export/import, see `/api/ops/backup` and `/api/ops/import`). (5) OK to make `public_url` configurable. |

## Applies to both: a #17 gap found while writing this

On every boot, `scripts/reveta/aura_config.py --write` replaces `config.yaml` keys with its
generated settings. It carries over only the paid model route (`aura.paid_route`, `model`).
**The owner's Tools switches from #17 (`platform_toolsets`) are therefore reset on every restart,
even on a persistent disk.** The fix is to carry `platform_toolsets` over the same way, plus a test.
It edits the script the Render start command runs, so it is listed here for Melvin's OK and not
yet made. MCP servers are already handled: Composio is re-added from the environment.

## Side by side

| | A: replicate to Supabase Storage, stay on Render free | B: same image, mounted `$HERMES_HOME`, always-on host |
|---|---|---|
| Survives restart / redeploy / spin-down | Yes, if every restore succeeds | Yes, nothing to restore |
| Data-loss window | ~1 s (SQLite) to one tarball interval (files); longer if Supabase is paused | None on restart; only on disk/VM loss |
| €0? | Only within 1 GB storage / 5 GB egress / 50 MB per object, with a pause workaround | Yes, within Oracle Always Free |
| Cold start | ~1 min spin-up + restore, after every 15 idle minutes | None (always on) |
| Forbidden files touched | Dockerfile, s6 services, stage2 or cont-init, Render start command | None for persistence; `aura_config.py` `public_url` (borderline) |
| New secrets | Supabase S3 keys (+ a database credential for keep-alive) in Render env | None (provider keys stay in `.env` on the disk) |
| Biggest risk | Paused or over-quota replica, so a boot with no data | Idle reclamation; Arm build untested |
| Who acts | Melvin: Supabase project, keys, Render env, rule change | Melvin: Oracle account and VM, address; Claude: docs + `public_url` |

## If Melvin chooses B, the next build steps

1. Make `public_url` come from configuration, and carry `platform_toolsets` across `--write` (both in `aura_config.py`, with tests). Needs his OK for that file.
2. Write `docs/aura/self-host.md`: arm64 `docker build`, `docker run` with the volume, TLS or tunnel, upgrade and rollback.
3. Melvin creates the VM; we run the browser acceptance against it once it is up; then a one-time data copy from Render via the backup/import endpoints.

## Sources

- Render free limits: https://render.com/docs/free — Render disks: https://render.com/docs/disks
- Supabase pricing: https://supabase.com/pricing — pausing: https://supabase.com/docs/guides/platform/free-project-pausing — S3 compatibility: https://supabase.com/docs/guides/storage/s3/compatibility
- Litestream S3-compatible providers: https://litestream.io/guides/s3-compatible/
- Oracle Always Free: https://docs.oracle.com/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm — Free Tier: https://docs.oracle.com/iaas/Content/FreeTier/freetier.htm

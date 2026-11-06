#!/bin/sh
# Render Preview-only, fail-closed direct dashboard boot.
#
# Render may wrap the image entrypoint and has no need for a supervisor tree
# in this single-process Preview. Keep the upstream default s6 boot unchanged
# for Docker, desktop bundling, gateways and every other deployment.
#
# No model-provider config or private data is bundled here.
set -eu

echo '[reveta-preview] Starting authenticated single-process dashboard (no s6 supervisor).'

# Public exposure must fail closed if any credential material is missing.
: "${HERMES_DASHBOARD_BASIC_AUTH_USERNAME:?Preview username is required}"
: "${HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH:?Preview password hash is required}"
: "${HERMES_DASHBOARD_BASIC_AUTH_SECRET:?Preview signing secret is required}"

if [ "${#HERMES_DASHBOARD_BASIC_AUTH_SECRET}" -lt 32 ]; then
  echo '[reveta-preview] Session-signing secret is too short.' >&2
  exit 78
fi

PORT="${PORT:-10000}"
case "$PORT" in
  ''|*[!0-9]*) echo '[reveta-preview] Invalid PORT.' >&2; exit 78 ;;
esac
if [ "$PORT" -lt 1024 ] || [ "$PORT" -gt 65535 ]; then
  echo '[reveta-preview] PORT must be 1024..65535.' >&2
  exit 78
fi

if [ "$(id -u)" != 0 ]; then
  echo '[reveta-preview] The image must start as root to prepare the Hermes home.' >&2
  exit 78
fi

HERMES_HOME=/opt/data
export HERMES_HOME
export HOME=/opt/data
export HERMES_WEB_DIST=/opt/hermes/hermes_cli/web_dist

# The shipped Vite assets are served by the Python app on the SAME origin.
if [ ! -f "$HERMES_WEB_DIST/index.html" ]; then
  echo '[reveta-preview] Dashboard bundle is missing; refusing partial startup.' >&2
  exit 78
fi

# Minimal first-boot state for the single-process preview. Do not recursively
# chown an operator-controlled volume or overwrite an existing config.
chown hermes:hermes "$HERMES_HOME"
for d in cron sessions logs memories skills workspace home pairing; do
  install -d -m 0700 -o hermes -g hermes "$HERMES_HOME/$d"
done
if [ ! -e "$HERMES_HOME/config.yaml" ]; then
  install -m 0600 -o hermes -g hermes /opt/hermes/cli-config.yaml.example "$HERMES_HOME/config.yaml"
fi

echo "[reveta-preview] Authentication required; binding Python dashboard on port $PORT."
exec /command/s6-setuidgid hermes /opt/hermes/.venv/bin/hermes dashboard \
  --host 0.0.0.0 --port "$PORT" --no-open --skip-build

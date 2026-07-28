#!/usr/bin/env bash
# Polled by the discord-deploy systemd timer. Pulls new code on a new commit and
# restarts the daemon. data/ is gitignored, so tokens/presence.json are never touched.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
git fetch --quiet origin main
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
[ "$LOCAL" = "$REMOTE" ] && exit 0            # nothing new
BEFORE=$LOCAL
git pull --ff-only origin main
# Reinstall only if dependencies actually changed
if ! git diff --quiet "$BEFORE" HEAD -- pyproject.toml; then
    .venv/bin/pip install -e . --quiet
fi
systemctl --user restart discord-daemon
logger -t discord-deploy "updated $BEFORE -> $REMOTE, daemon restarted"

# Auto-deploy setup (server, one-time)

Every `git push origin main` makes the server pull the new code and restart the daemon
within ~1 minute. Tokens (encrypted vault) and the passphrase (env file) are never
re-entered. `data/` is gitignored, so pulls never touch tokens or `presence.json`.

Run once on the server, **from inside the clone** (works at any path — the `sed` rewrites the
placeholder `%h/discord-tui-acc-manager` in the shipped units to your real checkout):

```bash
# 0. Point REPO at this checkout (path relative to your home dir)
cd /path/to/your/clone          # e.g. cd ~/discord/discord-tui-account-manager
REPO=${PWD#$HOME/}              # -> discord/discord-tui-account-manager

# 1. Passphrase in a 600 file (lets the daemon unlock the vault unattended)
printf 'DISCORD_VAULT_PASS=%s\n' 'YOUR_VAULT_PASSPHRASE' > ~/.discord-tui.env
chmod 600 ~/.discord-tui.env

# 2. Stop any manual tmux daemon first (avoid a duplicate gateway connection): Ctrl-C it.

# 3. Install the units, rewriting the placeholder path to YOUR clone
mkdir -p ~/.config/systemd/user
for f in discord-daemon.service discord-deploy.service discord-deploy.timer; do
  sed "s#%h/discord-tui-acc-manager#%h/$REPO#g" deploy/$f > ~/.config/systemd/user/$f
done
chmod +x deploy-check.sh

# 4. Enable everything; enable-linger keeps it running after you log out
loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now discord-daemon
systemctl --user enable --now discord-deploy.timer
```

Watch it work:

```bash
journalctl --user -u discord-daemon -f      # daemon logs (accounts reconnecting)
journalctl --user -t discord-deploy         # "updated ... daemon restarted" lines
```

**Security:** `~/.discord-tui.env` holds the master passphrase in plaintext. Keep it `600`.
Anyone who can read it plus the repo can unlock every token. This is the cost of hands-off
restart. Keep the server checkout read-only — never edit code directly on it, or
`git pull --ff-only` will refuse.

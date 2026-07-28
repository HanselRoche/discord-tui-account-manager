# Discord Account Manager (TUI)

Terminal UI to manage multiple Discord accounts by user token: keep them **always
online**, and change **presence / custom status / bio / display name / username /
avatar / banner** — per-account, all-at-once, or a selected subset. Runs on a headless
VPS over SSH.

> ⚠️ **Read this.** Automating **user** accounts via raw tokens is self-botting and
> violates Discord's Terms of Service. Mass identical edits are fingerprintable and can
> get accounts **locked or banned**. Use only on accounts you own and are willing to
> lose. The tool edits sequentially with jittered delays and honors rate limits to
> reduce (not eliminate) that risk.

## How it works

- **Always online:** one persistent gateway WebSocket per account (IDENTIFY +
  heartbeat + auto-reconnect). The online dot only shows while that socket is open, so
  the process must keep running (see *VPS* below).
- **Live presence** (online/idle/dnd/invisible + custom status) is pushed over the
  gateway. **Profile edits** (bio, name, avatar, banner) go over HTTPS.
- **Tokens** live in `data/tokens.enc`, encrypted with a passphrase (PBKDF2 + Fernet).
  The passphrase is never stored. `data/` is gitignored.

## Install

```bash
python -m venv .venv
.venv/bin/pip install -e .
```

## Run

```bash
.venv/bin/python main.py
```

On first launch you set a vault passphrase. Then:

| Key      | Action                                             |
|----------|----------------------------------------------------|
| `t`      | Add a token (validated via `GET /users/@me`)       |
| `d`      | Delete the token under the cursor                  |
| `space`  | Toggle selection on the cursor row                 |
| `a` / `n`| Select all / none                                  |
| `e`      | Edit op → choose operation, value, and scope       |
| `r`      | Refresh identity for selected accounts             |
| `q`      | Quit (closes all gateway connections)              |

**Scope** in the edit dialog: *Selected* (checked rows, or cursor if none checked),
*All*, or *Current row*.

### Operation value formats

| Operation        | Value you type                                  |
|------------------|-------------------------------------------------|
| Custom status    | `text` or `🔥 text` (optional leading emoji)     |
| Presence (dot)   | `online` \| `idle` \| `dnd` \| `invisible`       |
| Bio (About Me)   | free text                                        |
| Display name     | new global display name                          |
| Username         | `new_username\|account_password` (password req.) |
| Avatar           | path to an image file                            |
| Banner (Nitro)   | path to an image file                            |

## Two ways to run

- **TUI** (`main.py`) — interactive. Run it when you want to *change* things: add/remove
  tokens, edit bio/status/presence/avatar. Needs a terminal.
- **Daemon** (`daemon.py`) — no UI. Its only job is to keep accounts online with the
  right presence, 24/7. Built for systemd.

Presence edits you make in the TUI are saved to `data/presence.json`, and the daemon
restores that status/custom-status on start — so the two stay in sync.

### Daemon (24/7 presence)

Reads the same encrypted vault. Passphrase comes from env `DISCORD_VAULT_PASS`, else a
one-time prompt.

```bash
DISCORD_VAULT_PASS=yourpass .venv/bin/python daemon.py
```

`data/presence.json` (auto-created; gitignored) controls per-account presence. An entry
with an explicit `"status"` is enforced. A **missing** entry (or `"status": null`) is
**preserved** — the account keeps whatever it already shows (e.g. a custom status/dot set
from the phone) instead of being forced `online`:
```json
{
  "alt-1": { "status": "dnd",  "custom": "grinding" },
  "alt-2": { "status": "idle", "custom": null }
}
```

### Run in the background on a VPS (systemd)

Runs 24/7, restarts on crash, and — with lingering enabled — **survives you closing SSH /
logging out**. No tmux needed. The unit files are shipped in `deploy/`.

The shipped units are templated with the placeholder path `%h/discord-tui-acc-manager`. The
`sed` in the install rewrites it to **wherever you actually cloned the repo**, so this works
regardless of the directory name (`%h` = your home; for root that's `/root`). Run from
inside the repo:

```bash
# 0. Point REPO at this checkout (path relative to your home dir)
cd /path/to/your/clone          # e.g. cd ~/discord/discord-tui-account-manager
REPO=${PWD#$HOME/}              # -> discord/discord-tui-account-manager

# 1. Passphrase in a 600 file, so the daemon can unlock the vault non-interactively
printf 'DISCORD_VAULT_PASS=%s\n' 'YOUR_PASSPHRASE' > ~/.discord-tui.env
chmod 600 ~/.discord-tui.env

# 2. Install all units, rewriting the placeholder path to YOUR clone
mkdir -p ~/.config/systemd/user
for f in discord-daemon.service discord-deploy.service discord-deploy.timer; do
  sed "s#%h/discord-tui-acc-manager#%h/$REPO#g" deploy/$f > ~/.config/systemd/user/$f
done
chmod +x deploy-check.sh

# 3. Keep it running after logout, then start it
loginctl enable-linger "$USER"          # <-- without this, systemd --user stops when you disconnect
systemctl --user daemon-reload
systemctl --user enable --now discord-daemon
```

Manage it:
```bash
systemctl --user status  discord-daemon    # is it up?
systemctl --user restart discord-daemon    # apply new code / config
systemctl --user stop    discord-daemon    # take accounts offline
journalctl --user -u discord-daemon -f     # live logs
```

The unit (`deploy/discord-daemon.service`) pulls the passphrase from `~/.discord-tui.env`,
runs `daemon.py` from `WorkingDirectory`, and `Restart=on-failure`.

### Auto-deploy on push

So you never SSH in to update code: the server polls `origin/main` every ~1 min and, on a
new commit, `git pull --ff-only` + restarts the daemon. Tokens (`data/tokens.enc`) and the
passphrase (env file) are **never** re-entered — `data/` is gitignored, so pulls never touch
it. Poller + units live in `deploy/` (`deploy-check.sh`, `discord-deploy.service`,
`discord-deploy.timer`).

The systemd step above already installed the deploy timer's units (the `sed` loop covers all
three) and made `deploy-check.sh` executable — so there's nothing to re-copy. Just enable the
timer:
```bash
systemctl --user enable --now discord-deploy.timer
journalctl --user -t discord-deploy        # "updated ... daemon restarted" (empty until first push)
```
Full standalone copy-paste is in [`deploy/README.md`](deploy/README.md).

After that, the everyday flow is just:
```bash
git push origin main       # from your laptop; the VPS updates itself within ~1 min
```

> **Security:** `~/.discord-tui.env` stores the master passphrase in plaintext (keep it
> `600`). Anyone who can read it plus the repo can unlock every token — the cost of
> unattended restart. Keep the server checkout read-only; never edit code on it directly, or
> `git pull --ff-only` will refuse.

### TUI on a VPS (tmux)

The TUI needs a terminal, so detach it with tmux when editing over SSH:
```bash
tmux new -s discord
.venv/bin/python main.py
# detach: Ctrl-b then d   |   reattach: tmux attach -t discord
```

### Editing while the daemon runs

The daemon has no UI — it just holds accounts online. To *change* anything, run the **TUI**
(`main.py`) over SSH (in tmux, above); it shares the same vault and `presence.json`, so
there's no conflict. What takes effect depends on the edit:

| Edit | Applies to the running daemon |
|------|-------------------------------|
| Bio / display name / username / avatar / banner | **Instantly** — one-shot HTTPS, daemon-independent. |
| Add / delete token | **After a daemon restart** — the account list is read once at startup. |
| Presence / custom status | **After a daemon restart** — presence is read once at startup. (The TUI pushes it live *while open*, but that connection closes on quit.) |

So after adding a token or changing presence, apply it to the 24/7 process:
```bash
systemctl --user restart discord-daemon
```

Caveat: while the TUI is open it holds a **second** gateway connection per account (alongside
the daemon) — Discord allows it (multi-device) but it's extra fingerprint. Normal flow:
daemon runs 24/7; launch the TUI briefly to edit, restart the daemon if needed, then close it.

## Layout

```
main.py                     TUI entry point
daemon.py                   headless 24/7 presence daemon
src/vault.py                encrypted token store
src/presence_config.py      plain-JSON per-account presence (shared TUI <-> daemon)
src/discord_api.py          async HTTP client (rate-limit aware)
src/gateway.py              persistent gateway WebSocket per account
src/presence_manager.py     owns all gateway connections
src/ops.py                  operation registry + HTTP dispatch
src/batch.py                run an op across accounts (sequential + jitter)
src/tui/                    Textual UI (app, accounts, edit, log, modals)
deploy/                     systemd units + git-poll auto-deploy (deploy-check.sh)
```

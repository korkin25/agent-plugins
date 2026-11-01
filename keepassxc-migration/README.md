# keepassxc-migration

Makes KeePassXC the one place a Linux desktop keeps its secrets — and gets there without losing
a single browser session on the way.

On a normal KDE or GNOME desktop the secrets are spread across gnome-keyring, KWallet and
whatever each application decided to do. Chromium-family applications keep a *Safe Storage* key
in one of those stores and encrypt every cookie and saved password with it. That key is why
copying a browser profile to another machine leaves every site logged out, and why the first
launch there quietly **deletes** the sessions it cannot decrypt.

This plugin moves the values — not the store files, which do not travel — into KeePassXC, hands
`org.freedesktop.secrets` over to it, points the applications at libsecret, brings the SSH keys
into the database, and switches the old stores off.

## Requirements

`python3`, `keepassxc` with `keepassxc-cli`, `busctl` (systemd), and `kwallet-query` where
KWallet is involved. Reading gnome-keyring also needs the Python `secretstorage` module
(`apt install python3-secretstorage`, `dnf install python3-secretstorage`, or
`pip install --user secretstorage`). `kpxc-inventory` says which of these are missing.

Everything the plugin touches is per-user — `~/.config`, `~/.local/share`, systemd *user* units.
A second user account on the same machine is therefore a clean, isolated place to try it.

## Install

```
/plugin marketplace add korkin25/agent-plugins
/plugin install keepassxc-migration@korkin25
```

Then just say what you want: *"move my secrets into KeePassXC"*, *"disable gnome-keyring"*,
*"my browser is logged out after copying the profile"*. The skill carries the procedure and the
traps; the executables do the work.

## What it ships

| Command | What it does | Changes the system |
|---|---|---|
| `kpxc-inventory` | Reports who owns the secret service, what each store holds, cookie encryption stats, SSH keys, launcher flags | no |
| `kpxc-migrate` | Reads every entry out of gnome-keyring and KWallet and writes it into KeePassXC, verifying each by fingerprint | yes |
| `kpxc-switch` | `--launchers` patches app launchers, `--disable-legacy` turns the old stores off, `--undo` reverses both | yes |
| `kpxc-ssh-import` | Imports SSH keys into the database so KeePassXC loads them into ssh-agent on unlock | database only |
| `kpxc-verify` | Checks the end state, non-zero exit if a required check fails | no |
| `kpxc-env` | Moves `export` lines out of shell dotfiles into the database and loads them while it is unlocked; `list` shows what KeePassXC actually hands over | yes |
| `kpxc-run` | Runs a single command with selected secrets in its environment and nowhere else | no |

`kpxc-env list`, `kpxc-env export` and `kpxc-run` can also read a `.kdbx` file directly through
`keepassxc-cli`, with no GUI and no Secret Service: `--db path/to.kdbx`, or `$KEEPPASSXC_DB`, or
`~/Documents/<user>.kdbx` when that file exists and `keepassxc-cli` is installed; without any of
them, or with `KEEPPASSXC_DB` set to an empty string, they use the Secret Service. The password
comes from `$XDG_RUNTIME_DIR/kpxc-auth` (two lines: the database's real path, then its password;
keep it `0600`, the plugin never writes it) when it names the same file, else from a prompt or
stdin — except for `kpxc-env export` without `--db`, which never asks and treats a missing cache as
a locked database. In this mode an entry is a variable through its `kpxc-env` attribute or, without
one, through a title that is a valid variable name; the recycle bin is skipped. Every
`keepassxc-cli` call runs the database's key derivation again, which takes seconds on purpose, so
the file is decrypted once per command: one `keepassxc-cli export` into a pipe, never to disk.
Placeholders and field references (`{REF:…}`, `{USERNAME}`, `{S:…}` and the like) are resolved by
the same rules `keepassxc-cli show` follows; only `{TOTP}`, `{DT_…}`, `{URL:…}`, `{DB_DIR}` and a
`{REF:…@I:…}` that is not 32 hex digits cost one extra `show` for that entry alone, and only when
its value is needed.

`kpxc-env install` symlinks every `kpxc-*` tool into `~/.local/bin`, replacing only symlinks — a
regular file of the same name is left alone and reported; run it again from a new version's
`bin/` after an update to move the links there.

On Claude Code `bin/` is on `PATH`, so the commands work by name. In Codex or a plain shell, call
them by path — they are ordinary Python 3 executables with no dependencies beyond an optional
`secretstorage`, and they work the same either way.

## What it sends where

Nothing leaves the machine. No network calls, no telemetry, nothing written outside the user's own
home directory. Secret values are read through the D-Bus and KWallet APIs (and, for a `.kdbx` read
directly, from `keepassxc-cli` over a pipe), held in one process's memory for the length of a
migration, and written straight into KeePassXC. What reaches the terminal — and therefore an
agent's context — is only entry labels, attributes and truncated SHA-256 fingerprints, which are
enough to prove two stores agree and useless for anything else.

`kpxc-switch` writes only user-level files: `~/.local/share/applications`, `~/.config/autostart`,
`~/.config/kwalletrc`, a user D-Bus service file and systemd *user* unit masks. Nothing under
`/usr` or `/etc` is touched, and `--undo` reverses all of it. The old stores are never emptied:
migration copies, so they stay as a fallback until you delete them yourself.

## The one thing to read before starting

A Chromium-family browser started without its Safe Storage key **permanently deletes** every
cookie it cannot decrypt. Take a copy of `Default/Cookies` and `Default/Login Data` for each
profile before anything else — restoring those two files is the entire recovery path — and keep
browsers closed until `kpxc-verify` is happy. `kpxc-migrate` makes its own backup of the stores
unless told not to.

The lasting cost of this migration is a new rule: **unlock KeePassXC before starting browsers,
VS Code or anything else that wants a secret.** Started against a locked database, they fall back
to the built-in key and take their sessions with them.

## Rollback

```
kpxc-switch --undo
systemctl --user start gnome-keyring-daemon.service
```

That unmasks the units, removes the D-Bus activation override, restores `kwalletrc` and removes
the patched launchers. The entries migrated into KeePassXC stay where they are.

## Licence

MIT.

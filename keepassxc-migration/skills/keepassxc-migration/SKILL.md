---
name: keepassxc-migration
description: Move a Linux desktop's secrets into KeePassXC and switch gnome-keyring and KWallet off. Use when the user wants KeePassXC to be the system secret store, asks to disable gnome-keyring or KWallet, wants KeePassXC to serve org.freedesktop.secrets or to hold their SSH keys, or when a browser profile copied from another machine shows every site logged out. Also triggers on "перенести секреты в keepassxc", "отключить gnome-keyring", "keepassxc вместо kwallet", "куки не расшифровываются после переноса профиля", "ssh-ключи в keepassxc".
---

# Moving a Linux desktop's secrets into KeePassXC

Exactly one process on a session bus can own `org.freedesktop.secrets`. Everything here follows
from that: the migration is a handover of that name from gnome-keyring to KeePassXC, and the
secrets have to be read out through the old owner before it lets go.

The plugin ships seven executables. On Claude Code `bin/` is on `PATH`, so they can be called by
name; anywhere else (Codex, a plain shell) call them by path from the plugin directory.

| Command | What it does | Changes the system |
|---|---|---|
| `kpxc-inventory` | Reports what is installed, who owns the name, what is in each store, cookie encryption stats, SSH keys | no |
| `kpxc-migrate` | Reads every entry out of gnome-keyring and KWallet and writes it into KeePassXC | yes |
| `kpxc-switch` | Patches app launchers, disables the legacy stores, `--undo` reverses both | yes |
| `kpxc-ssh-import` | Imports SSH private keys into the database as agent-loadable entries | yes (database) |
| `kpxc-verify` | Checks the end state, exit code 1 if a required check fails | no |
| `kpxc-env` | Moves shell environment secrets out of dotfiles and loads them while unlocked | yes |
| `kpxc-run` | Runs one command with selected secrets in its environment and nowhere else | no |

## Running it

Every piece of state involved lives under the user's own home — `~/.config`, `~/.local/share`,
systemd **user** units, one user D-Bus service file. Nothing under `/usr` or `/etc` is touched.
That makes a second user account on the same machine a clean and completely isolated test bed:
what happens there cannot affect the first account.

What has to be installed: `python3`, `keepassxc` and `keepassxc-cli`, `busctl` (part of systemd),
and `kwallet-query` if KWallet is in play. Reading gnome-keyring additionally needs the Python
`secretstorage` module — `apt install python3-secretstorage`, `dnf install python3-secretstorage`,
or `pip install --user secretstorage`. Without it the keyring cannot be read and the migration
will collect nothing from it. `kpxc-inventory` reports which of these are missing.

Invocation, in order, with the database open in KeePassXC:

```sh
kpxc-inventory                      # read-only, safe to run at any time
kpxc-migrate --run                  # interactive: it waits for GUI toggles
kpxc-switch --launchers --dry-run   # check the plan, then drop --dry-run
kpxc-verify                         # exit code 1 while anything required is missing
kpxc-switch --disable-legacy        # only once a browser has been proven to work
kpxc-ssh-import --db path/to.kdbx   # last, and close the database in the GUI first
```

Outside Claude Code, call the same commands by path: `<plugin>/bin/kpxc-inventory`. They are
plain Python 3 executables and behave identically. `kpxc-migrate` needs a real terminal — it
holds the secrets in memory while the user toggles the integration in KeePassXC — so it refuses
to run when stdin is not a TTY, and it does nothing at all without `--run`.

## Shell environment secrets

Tokens exported from `~/.bashrc` are the other half of the problem: plain text in a file that
gets backed up, synced and read over shoulders. `kpxc-env import --from ~/.bashrc` lists what it
would move (names only), and with `--apply` stores the values, cuts the lines and leaves a single
loader in their place:

```sh
command -v kpxc-env >/dev/null && eval "$(kpxc-env export)"
```

Six things decide whether this works, and all six have already gone wrong once:

**The loader needs `kpxc-env` on `PATH`.** Inside Claude Code the plugin's `bin/` is on `PATH`,
but an ordinary login shell knows nothing about it, so the line silently does nothing and every
variable is empty. `kpxc-env install` symlinks the tools into `~/.local/bin`; the import warns
when this is missing.

**Position matters.** The loader replaces the first line it removed, not the end of the file: a
later line may compute something from a variable that has just been moved, and appending would
leave it empty.

**Quoting decides what is a literal.** A value in single quotes is literal even when it contains
`$` or a backtick — treating those as computed leaves a live password sitting in the file. Only
unquoted and double-quoted values expand.

**KeePassXC must hand entries over without a dialog.** With "Confirm when passwords are
retrieved by clients" ticked (Settings > Secret Service Integration, on by default), an open
database still reports every entry as locked to a client that has not clicked Allow — and the
"Remember" in that dialog lives only as long as the D-Bus connection, so each shell start would
be a new client with a new dialog. The loader cannot answer one, so it gets nothing and the shell
stays empty. `kpxc-env list` marks such entries `withheld`, `kpxc-env export` says so once on
stderr, and `kpxc-verify` warns. Untick the option.

**The loader runs under whichever `python3` is first on `PATH` at that line.** `kpxc-env` needs
the `secretstorage` module; if it lives only in a venv that `~/.bashrc` activates *later*, the
loader runs on the system interpreter, finds no module and exports nothing. Install it system-wide
(`apt install python3-secretstorage`) rather than moving the line.

**A locked database must not break shells.** `kpxc-env export` prints nothing and exits 0 when
the service is unavailable, so shells start clean and silent rather than prompting or failing.
The two cases above are not a locked database, and they are not silent: a missing module or a
withheld entry gets one line on stderr, which `eval "$(...)"` does not capture.

The import leaves a `.kpxc-bak` copy of the dotfile beside it, and that copy still holds every
secret in plain text. It exists so a broken shell can be undone; **delete it** — along with any
other dotfile backup — as soon as a fresh shell proves the loader works. A backup that outlives
its purpose is just the original problem with a different name.

For a secret that should not be in the ambient environment at all, mark it `kpxc-env hot NAME`
and give the tool that needs it a wrapper: `kpxc-env shim terraform` writes `~/.local/bin/terraform`,
which injects the variables through `kpxc-run` and executes the real binary. Nothing else has to
know the mechanism exists — not the user, not an agent, not a script — which is exactly why this
is more reliable than telling every caller to remember a wrapper.

## Before touching anything: the trap that eats data

Chromium-family applications (Chrome, Opera, Brave, Vivaldi, Electron apps such as VS Code)
encrypt cookies and saved passwords with a "Safe Storage" key kept in the secret store. Cookie
values carry a prefix: `v10` means the built-in fallback password, which works on any machine,
and `v11` means the key from the store.

**A browser started without the right key deletes every `v11` cookie it cannot decrypt, permanently.**
Not "fails to read" — deletes. On a real profile that is thousands of live sessions gone in the
time it takes the browser to reach its start page.

So: run `kpxc-inventory` first, and until the key is verifiably in place, do not start a browser,
and take a copy of `Default/Cookies` and `Default/Login Data` for every profile. Restoring those
two files back over a purged profile is the whole recovery path, and it works.

## The order that works

1. **Inventory.** `kpxc-inventory`. It answers the only questions that matter: who owns the name
   now, which entry names exist in which store, and how many `v11` cookies are at stake.
2. **Back up.** The two files per browser profile above, plus `~/.local/share/keyrings/`,
   `~/.local/share/kwalletd/` and a copy of the `.kdbx`. `kpxc-migrate` refuses to run without a
   backup directory and makes one itself unless told otherwise.
3. **Prepare KeePassXC.** Any KeePassXC from 2.5 on can serve the Secret Service; 2.7 is what
   this was built against. Create a dedicated group for exposed entries — never expose the root
   group: everything in an exposed group is readable over D-Bus by any process running as that
   user, browsers and random scripts included. The setting lives in Database Settings → Secret
   Service Integration and only becomes available once the integration is enabled globally in
   Tools → Settings.
4. **Migrate.** `kpxc-migrate`. It walks the user through the handover and verifies every entry
   by fingerprint afterwards.
5. **Point the applications at libsecret.** `kpxc-switch --launchers`. On KDE, Chromium's
   auto-detection picks KWallet, so the flag has to be explicit.
6. **Verify with a real browser.** Start one browser, count cookies before and after. Same count
   (minus natural expiry) means the key resolved. A collapse to near zero means it did not —
   restore the cookie backup before doing anything else.
7. **Turn the old stores off.** `kpxc-switch --disable-legacy`.
8. **SSH keys, last.** `kpxc-ssh-import`, then enable Tools → Settings → SSH Agent, lock and
   unlock the database, confirm with `ssh-add -l`, confirm a real connection, and only then
   delete the key files.
9. **Shell secrets.** `kpxc-env import --from ~/.bashrc` to see the list, `--apply` to move it,
   `kpxc-env install` so ordinary shells can find the loader, then a fresh shell to confirm and
   the `.kpxc-bak` copy deleted.
10. **Verify the end state.** `kpxc-verify`.

## Traps, each of which has already cost a session

**Copying the store files between machines does not move the key.** A wallet file and a keyring
file copied byte-for-byte still resolve to different values through the local daemon, because
each daemon derives them against its own password and salt. Migrate the values, never the files.
The same goes for a browser profile: the profile travels, the key does not.

**KeePassXC refuses to enable the integration while another service holds the name**, and
gnome-keyring is D-Bus-activatable, so the first client that asks brings it straight back. Free
the name *and* override the activation file before expecting KeePassXC to take it. The override
is a user-level `org.freedesktop.secrets.service` in `$XDG_DATA_HOME/dbus-1/services/`, which
takes precedence over `/usr/share/dbus-1/services/`.

**`systemctl --user stop gnome-keyring-daemon.service` does not stop a D-Bus-activated
instance.** It stops the unit; the activated process survives and keeps the name. Kill the
remaining PIDs explicitly — and match them with a pattern that cannot match your own command
line, or the script kills its own shell.

**KeePassXC overwrites the database file with its in-memory copy.** Any external write —
`keepassxc-cli`, a Python library — must happen with the database closed in the GUI, or the work
silently disappears on the next save.

**Do not drive the database from Python.** A database with a high AES-KDF round count takes
minutes per open in pure Python and seconds in `keepassxc-cli`, which is C++ and gets the same
job done. Read the KDF settings out of the KDBX header if the cause of a slow open is unclear —
the header is not encrypted.

**Hard-killing a secret daemon can take the desktop shell with it.** On KDE Plasma, killing
`kwalletd` or `gnome-keyring-daemon` has twice been enough to drop `plasmashell`, panel and all;
it comes back with `systemctl --user restart plasma-plasmashell.service`. Prefer
`systemctl --user restart`, and expect the shell to need a restart when a kill is unavoidable.

**Some ssh agents ignore `ssh-add -D`.** `gcr-ssh-agent`, which is what `SSH_AUTH_SOCK` points at
on a GNOME-flavoured session, keeps its keys regardless — and after the key files are deleted,
its stale entries make signing fail with `agent refused operation` until the server gives up on
too many failures. Restart the agent's own unit rather than clearing it, then reload the keys by
locking and unlocking the database; `kpxc-ssh-import` prints the right command for whichever
agent is actually in use.

**KeePassXC must be unlocked before any consumer starts.** A browser or VS Code started against
a locked or absent service falls back to the built-in key and takes its cookies with it. Put
KeePassXC in autostart and treat "unlock first, then everything else" as the new rule of the
machine — that cost is the real price of this migration and the user should hear it before the
work starts, not after.

## Reading secrets without leaking them

Every script here prints labels, attributes and truncated SHA-256 fingerprints, never a value.
Fingerprints are enough to prove that a migrated entry matches its source, and to prove that two
stores disagree, which is the usual diagnosis. When a value must be moved, it goes from one API
straight into the other inside one process — never through a file, an environment variable, a
log line or the agent's own transcript.

The scripts are only half of it: the commands used to *check* their work are where a secret
actually escapes. Verifying an edited dotfile with `grep -A2`, `sed -n '130p'` or a bare `cat`
prints neighbouring lines, and one of them is a password — that is precisely how a live
credential ended up in a terminal and a transcript during this plugin's own development. Check
by name and line number, never by content: `grep -oE '^\s*export\s+[A-Za-z_]+'` lists names,
`kpxc-env list` lists what is stored, and `kpxc-verify` answers the rest. Treat anything that
did reach a terminal as burnt: rotate that credential, and clear the shell history and scrollback
that captured it.

To identify which key a browser actually used, decrypt one cookie with each candidate: derive
with PBKDF2-HMAC-SHA1, salt `saltysalt`, 1 iteration, 16 bytes, then AES-128-CBC with an IV of
16 spaces, strip the 3-byte prefix, and check the padding and that the plaintext after the first
32 bytes (a domain hash) is printable text. The script prints which candidate won, nothing else.

## Rollback

`kpxc-switch --undo` unmasks the units, removes the D-Bus override, restores `kwalletrc` and the
patched launchers. The migrated entries stay in KeePassXC — they are copies, nothing was deleted
from the old stores, which is deliberate: the old stores keep working as a fallback until the
user removes them by hand.

If a browser did purge its cookies, close it first, copy the backed-up `Cookies` and
`Login Data` back into the profile, and only then start it again with the key in place.

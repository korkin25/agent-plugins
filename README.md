# agent-plugins

A small marketplace of plugins for [Claude Code](https://claude.com/claude-code).

## Use it

```
/plugin marketplace add korkin25/agent-plugins
```

then browse with `/plugin`, or install directly:

```
/plugin install calendar-agenda@korkin25
```

## Plugins

| Plugin | What it does |
|---|---|
| [**calendar-agenda**](calendar-agenda/) | Your agenda from any number of Google Calendars at the start of every session, and scheduling that respects all of them |
| [**keepassxc-migration**](keepassxc-migration/) | Moves a Linux desktop's secrets into KeePassXC — out of gnome-keyring, KWallet and shell dotfiles, with the browser sessions surviving the move |
| [**plugin-factory**](plugin-factory/) | Scaffold, check and release plugins in this repository, with the same validation Anthropic's review pipeline runs |

## How releases work

Every push runs [`validate.yml`](.github/workflows/validate.yml), which simply invokes
[`plugin-check`](plugin-factory/bin/plugin-check) — the same tool you run locally, so CI and your
machine cannot disagree. It verifies that the manifests parse, that names and versions agree
between each plugin and the marketplace, that nothing which belongs at the plugin root ended up
inside `.claude-plugin/`, that executables carry a shebang and parse, that no absolute home path
or credential printing slipped in, and then runs `claude plugin validate --strict`.

This repository **is** the marketplace: merging to `main` is the release. There is no publish
step to run, and nothing to wait for.

### About the official directories

Getting into the first-party directories is not something CI can do, in either ecosystem:

- **Anthropic's** [`claude-plugins-official`](https://github.com/anthropics/claude-plugins-official)
  accepts third-party plugins into `external_plugins` through a
  [submission form](https://clau.de/plugin-directory-submission), followed by a human review
  against their quality and security bar. A pipeline can prepare and validate the plugin — it
  cannot submit it.
- **OpenAI's Codex** plugin directory has no self-serve publishing yet; their documentation
  still lists it as coming. Until it opens, a Codex user installs from a marketplace like this
  one rather than from the directory.

So the workflow here validates and releases; submission stays a deliberate, human step. When
self-serve publishing opens on either side, that step becomes a job in the same workflow.

## Licence

MIT.

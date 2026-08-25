# claude-plugins

A small marketplace of plugins for [Claude Code](https://claude.com/claude-code).

## Use it

```
/plugin marketplace add korkin25/claude-plugins
```

then browse with `/plugin`, or install directly:

```
/plugin install calendar-agenda@korkin25
```

## Plugins

| Plugin | What it does |
|---|---|
| [**calendar-agenda**](calendar-agenda/) | Your agenda from any number of Google Calendars at the start of every session, and scheduling that respects all of them |

## How releases work

Every push runs [`validate.yml`](.github/workflows/validate.yml), which checks that the
manifests parse, that each marketplace entry points at a real plugin whose `plugin.json` name
matches, that versions agree between the two manifests, that the bundled executable parses and
is executable, that every skill carries a `name` and `description`, and that no personal
identifiers or credential-printing slipped into the tree.

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

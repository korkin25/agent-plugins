---
name: plugin-factory
description: Create a new Claude Code plugin, add it to the user's marketplace, validate it and publish it. Use when they ask to make a plugin, turn an existing skill or hook into a plugin, add something to their marketplace, cut a release of a plugin, or submit one to the community directory.
---

# Making a plugin

The user's marketplace is **`~/work/github/agent-plugins`** → `github.com/korkin25/agent-plugins`.
The repository *is* the marketplace, so merging to `main` releases it: there is no publish step.

Read `.claude-plugin/marketplace.json` first — it lists what already exists.

## Before writing anything

**The plugin name is an immutable slug.** Once anyone installs it, renaming breaks their install
with `plugin-not-found`. Agree the name with the user explicitly and say that it is permanent.
`displayName` in `plugin.json` is what changes freely later.

Ask what the plugin actually ships, because the layout follows from it: skills, an agent, hooks,
an MCP server, an executable, background monitors.

## Layout

Everything except `plugin.json` lives at the **plugin root**, never inside `.claude-plugin/` —
that is the single most common mistake and the validator does not always catch it.

```
<repo>/<plugin-name>/
├── .claude-plugin/plugin.json    # manifest — only this file goes in here
├── skills/<name>/SKILL.md        # model-invoked skills
├── commands/<name>.md            # slash commands
├── agents/<name>.md              # subagents
├── hooks/hooks.json              # event handlers
├── monitors/monitors.json        # background watchers
├── .mcp.json                     # MCP servers
├── .lsp.json                     # language servers
├── bin/                          # executables added to PATH
├── settings.json                 # only `agent` / `subagentStatusLine` are honoured
└── README.md
```

`plugin.json` requires `name` and `description`; `version`, `author`, `homepage`, `repository`,
`license` and `keywords` are optional but worth setting. **Users receive updates only when
`version` is bumped**, so treat it as the release trigger, not decoration.

Note on `bin/`: it works everywhere except plugins distributed through claude.ai organization
settings, which reject a top-level `bin/`. If the plugin is meant for org distribution, ship the
executable elsewhere and call it by path.

## Writing the parts

**Skills.** Frontmatter needs `name` and `description`; the description is the whole trigger
mechanism, so write it as the situations it applies to, in the user's own words, including the
languages they actually type in. Add `disable-model-invocation: true` for a skill that should
only ever run when typed as a slash command.

**Hooks.** Same schema as `settings.json`. Use `${CLAUDE_PLUGIN_ROOT}` for any path inside the
plugin — absolute paths from the author's machine are the second most common mistake. A hook
must never be able to fail a session: give it a `timeout` and end the command with `; true`.

**MCP servers.** Pin the version (`pkg@1.2.3`), never float on latest — an unpinned server is a
supply-chain hole in something the user runs on every session.

**Executables.** `chmod +x`, and no absolute paths to the author's home.

## Tools that come with this plugin

```bash
plugin-new <name> "<description>"    # scaffold and register it in the marketplace
plugin-check [<name>]                # static checks: manifests, layout, hygiene, validator
plugin-test [<name>]                 # behavioural checks in a throwaway HOME
plugin-release <name> patch|minor|major|X.Y.Z
```

**`plugin-test` is the one that saves the four-way manual hunt.** It runs everything in a
clean room — a temporary `HOME` and `XDG_*` — so a plugin that only works because the author's
machine is already set up fails here rather than for the first person who installs it. It
asserts what actually broke in practice: that each hook **exits cleanly with nothing
configured** (a hook that fails takes the session with it), that its stdout is **valid JSON of
the right shape**, that the output carries **no ANSI escapes** (surfaces that render markdown
show them literally), that every executable **explains itself instead of crashing** when
unconfigured, that MCP servers are **pinned**, and that skill descriptions are long enough to
trigger at all.

What it deliberately does not cover is **rendering** — whether a particular client displays
`systemMessage`, or draws colour. That differs between a terminal TUI and a desktop app even
within one product, and can only be established by looking. Test behaviour automatically; check
rendering once, by eye, and write down what you found.

`plugin-check` is the one to run before every push: it verifies the manifests parse, that names
and versions agree between them, that nothing that belongs at the plugin root ended up inside
`.claude-plugin/`, that executables are executable and parse, that no absolute home path or
credential printing slipped in, and finally runs Anthropic's own validator.

## Validate — the same check Anthropic runs

```bash
claude plugin validate ./<plugin-name> --strict
```

The review pipeline runs exactly this, so a failure here is a rejection that has not happened
yet. Then load it for real before committing:

```bash
claude --plugin-dir ./<plugin-name>
```

Trigger each part: invoke the skills, check agents appear in `/context`, cause the event each
hook matches. A plugin that validates but was never loaded is untested.

## Add it to the marketplace

Append to `.claude-plugin/marketplace.json`:

```json
{ "name": "<plugin-name>", "source": "./<plugin-name>", "description": "…", "version": "0.1.0" }
```

The `version` here and in `plugin.json` must agree — CI fails on a mismatch. Then commit and
push; CI validates on every push, and `main` is the release.

## Releasing an update

1. Bump `version` in **both** manifests — without it nobody gets the update.
2. Commit, push, confirm CI is green.
3. `release.yml` tags and publishes a GitHub release when the version changes.

## Submitting to Anthropic's directory

Two different things, and only one has a submission path:

- **`claude-community`** — the public community marketplace, where third-party plugins land
  after review. Submit through the in-app form: individual authors use
  [platform.claude.com/plugins/submit](https://platform.claude.com/plugins/submit); a Team or
  Enterprise organization can use
  [claude.ai/admin-settings/directory/submissions/plugins/new](https://claude.ai/admin-settings/directory/submissions/plugins/new).
- **`claude-plugins-official`** — curated by Anthropic at their discretion. **No application
  process exists**; the submission form does not add anything to it. Do not promise the user a
  route into it.

**The form is a human step and cannot be automated** — do not build or suggest a pipeline that
claims to. What *is* automatic: once a plugin is approved, it is pinned to a commit SHA in the
community catalog and CI bumps that pin as new commits are pushed, so after the one-time
submission, publishing really is just pushing. The public catalog syncs nightly, so expect a
delay before it appears.

Before pointing the user at the form, make sure `claude plugin validate --strict` passes and the
README states what the plugin sends where — the review includes automated safety screening.

## Things worth checking before publishing anything

- No personal identifiers, absolute home paths or internal hostnames anywhere in the tree.
- No credential value can reach stdout — paths in error messages are fine, contents are not.
- Least privilege in any scope the plugin requests.
- If the plugin puts user data into the model's context, the README says so plainly. That is
  the user's decision to make, and they can only make it if it is written down.

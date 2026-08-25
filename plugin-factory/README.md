# Plugin Factory

Scaffolding, checking and releasing plugins in your own marketplace repository — with the same
validation Anthropic's review pipeline runs, so a rejection surfaces before you submit rather
than after.

## Install

```
/plugin marketplace add korkin25/agent-plugins
/plugin install plugin-factory@korkin25
```

## Tools

```bash
plugin-new <name> "<description>"                 # scaffold, and register in marketplace.json
plugin-check [<name>]                             # static checks: manifests, layout, hygiene
plugin-test  [<name>]                             # behavioural checks in a throwaway HOME
plugin-release <name> patch|minor|major|X.Y.Z     # bump the version everywhere it appears
```

`plugin-check` verifies that the manifests parse, that names and versions agree between the
plugin and the marketplace, that nothing which belongs at the plugin root ended up inside
`.claude-plugin/`, that executables carry a shebang, are executable and parse, that no absolute
home path or credential printing slipped into the tree, and then runs
`claude plugin validate --strict`.

`plugin-test` is the one that removes the manual hunt across terminal and desktop builds of two
products. It runs in a **clean room** — a temporary `HOME` and `XDG_*` — so a plugin that works
only because your own machine is already configured fails here instead of for your first user.
It asserts what actually goes wrong: hooks must exit cleanly with nothing configured, their
stdout must be valid JSON of the expected shape and free of ANSI escapes, executables must
explain themselves rather than crash, MCP servers must be version-pinned, and skill descriptions
must be substantial enough to trigger.

It does **not** test rendering — whether a client shows `systemMessage`, or draws colour. That
differs between a terminal TUI and a desktop app within the same product, and only looking can
settle it. Automate behaviour; check appearance once and write down the answer.

Run both before every push. CI runs exactly the same two tools, so a green CI cannot mean
something different from a green machine.

## The skill

The bundled `plugin-factory` skill carries what the tools cannot: the layout rules and the two
mistakes people actually make, the warning that a plugin's name is an **immutable slug**, how
versioning decides whether users receive an update at all, and an honest account of what
submitting to Anthropic's directories does and does not involve.

## What this sends where

Nothing. These are local tools that read and write files in your own repository.

## Licence

MIT.

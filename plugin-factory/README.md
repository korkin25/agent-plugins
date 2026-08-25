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
plugin-check [<name>]                             # every check CI runs, locally
plugin-release <name> patch|minor|major|X.Y.Z     # bump the version everywhere it appears
```

`plugin-check` verifies that the manifests parse, that names and versions agree between the
plugin and the marketplace, that nothing which belongs at the plugin root ended up inside
`.claude-plugin/`, that executables carry a shebang, are executable and parse, that no absolute
home path or credential printing slipped into the tree, and then runs
`claude plugin validate --strict`.

Run it before every push. CI runs the same checks, but finding a problem locally costs seconds
instead of a round trip.

## The skill

The bundled `plugin-factory` skill carries what the tools cannot: the layout rules and the two
mistakes people actually make, the warning that a plugin's name is an **immutable slug**, how
versioning decides whether users receive an update at all, and an honest account of what
submitting to Anthropic's directories does and does not involve.

## What this sends where

Nothing. These are local tools that read and write files in your own repository.

## Licence

MIT.

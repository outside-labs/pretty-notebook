# CLI commands

The unreleased command tree uses `expose_interface`. Installed `pnbp` command
names and options remain supported, including notebook/profile selection,
repeated search tags, JSON reports and `--file -` for standard input. Invalid
arguments exit 2; expected operation failures exit 1. Editor commands use
`VISUAL`, then `EDITOR`, then the platform editor; closing an unchanged document
leaves the note untouched.

Python callers can use `pretty_notebook.cli.app.invoke([...])` for native
invocation or `pretty_notebook.cli.cli([...])` for the console exit boundary.
The command registry and exceptions now follow `expose_interface`. The core
installation no longer requires Click; the optional web server still includes
it as a dependency of Uvicorn.

`pnbp --help` lists the current command registry. Use `pnbp COMMAND --help`
for a command's exact options; the [API and CLI reference](reference.md) renders
that same help without opening or changing a notebook.

Select an existing notebook before the command:

```bash
pnbp --notebook ~/notes note show guides/overview
pnbp --profile work search 'recipe' --field any --tag food --json
```

Only one of `--notebook` and `--profile` may be supplied. Environment-based
selection continues to work. [Settings](settings.md) documents profile registration
and configuration; [versions and support](versions.md) distinguishes the published
0.9.0 package from the current 0.10 commands.

## Everyday workflow

| Command | Purpose and canonical guide |
| --- | --- |
| `init PATH [--dry-run]` | Explicit settings/identity initialization; [settings](settings.md) |
| `note add NAME`, `note edit NAME`, `note show NAME` | [Source editing](editing.md); `--content`, `--file` and explicit empty bodies |
| `note rename SOURCE NAME`, `note move SOURCE PATH` | Checked [rename/move](links.md#rename-and-move), including `--dry-run` |
| `identity status`, `identity reconcile`, `identity fork` | Deliberate [identity operations](identities.md) |
| `search QUERY` | Current local [search](local-search.md), field/tag filters and `--json` |
| `status --json` | Bounded local pending-edit/status report |
| `commit-stage [--json]` | Remote read-only [publication plan](checked-publishing.md#local-plans) |
| `commit-remote`, `commit-local` | Explicit checked/legacy [publication](checked-publishing.md#execution-and-recovery) |
| `commit-html` | Local rendered HTML export to `HTML_PATH` |
| `commit-settings [--local]`, `favicon PATH [--local]` | [Site presentation and favicon](web.md#site-titles-and-favicon) |
| `note operations`, `note recover ID` | [Interrupted move recovery](links.md#interrupted-operations) |

## Reports and source-transforming commands

Collectors such as `collect-all-public`, `collect-all-tags` and `collect-all`
write generated Markdown reports into the notebook. Their `#pnbp` control tag
keeps reports outside ordinary content collections. Inspect command help and
review source changes after applying a collector or correction command.

`delete-all-pnbp` deletes generated `#pnbp` notes. `delete-all-empty` deletes
only generated-report candidates that are still empty. Other correction
commands can replace source text; select an exact note or explicitly accept
`--fuzzy` when offered, and preserve a checkpoint before destructive edits.

Code extraction preserves language/source bytes and refuses unsafe destinations.
Existing outputs are retained unless `--overwrite` is selected. Git commands
scope work to the notebook root or an explicitly supplied `--repo-root`, refuse
an already staged index, and exclude credentials, recovery drafts and journals.
See command help and [settings](settings.md#credentials-and-sharing).

The built-in command list is registered explicitly in `src/pnbp/cli.py`.
Adding a helper function does not automatically add a CLI command. New commands
must be deliberately registered and document their source/network effects.

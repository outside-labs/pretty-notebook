# Notebook settings (0.10)

These APIs and commands are available in the development checkout. The released
0.9 package still uses the legacy configuration described in its release docs.

## Open without initialization

```python
from pretty_notebook import Notebook, NotebookSettings

nb = Notebook(path="~/notes")
nb = Notebook.open("~/notes", settings={"NOTE_NESTED": "recurs"})
nb = Notebook("~/notes", settings=NotebookSettings(note_nested="recurs", title="Notes"))
```

The directory must already exist. Construction only reads files: it never asks
questions, creates settings, or initializes Git. `Notebook()` still uses
`NOTE_PATH`. `nb.open()` retains its existing reload behavior; `nb.reload()` is
an explicit equivalent. Both refuse to discard pending edits unless passed
`discard_unsaved=True`.

`nb.settings` is the typed settings model. Its Python field names are lowercase;
JSON and mapping arguments retain the established keys such as `NOTE_NESTED`
and `TITLE`. Theme keys retain their existing lowercase spelling. `nb.config`
contains resolved supplied settings and the discovery default; credentials are
excluded. Existing path, tag, publishing, and task configuration keys remain
supported. Unknown extension keys are preserved, but credential keys are refused
in portable configuration.

## Precedence and validation

Settings use **explicit arguments > environment > selected file > defaults**.
A mapping overrides only its supplied keys; a `NotebookSettings` instance
supplies every model field, including its defaults. A path argument overrides
`NOTE_PATH`. A `profile` argument selects its registered path and overrides
`NOTE_PATH`; passing both a path and profile is an error.

Environment setting names match JSON keys. Boolean values accept `true`, `false`,
`1`, and `0`; `NAV_PAGES` accepts JSON. Known types, discovery modes, publication
tags, navigation structure, and the HTTP(S) API URL are validated. Invalid values
raise `SettingsError` without printing their contents. Missing settings use
defaults quietly; the default discovery mode is `flat`, and no remote API is
selected until configured.

Without an explicit file selection, `.pnbp/settings.json` or legacy
`pnbp_settings.json` is loaded. Having both is ambiguous and raises an error.
Select a file deliberately with `settings_file="relative/or/absolute.json"`
or `PNBP_SETTINGS`. An explicitly selected missing file is an error.

`PNBP_SETTINGS=off` ignores all settings and credential files, while allowing
explicit model/mapping arguments and environment values. An explicit
`settings_file` argument takes precedence over that environment switch.

`IMG_PATH`, `HTML_PATH`, and `VENV_PATH` accept absolute paths or paths relative
to the notebook. `NOTE_NESTED` accepts `flat`, `single`, `recurs`, or `all`.
Every mode excludes `.pnbp/`, `.git/`, `.obsidian/`, and `__pycache__/`.

## Markdown backend

The 0.11 release defaults to `MARKDOWN_BACKEND="typed"`.
`NotebookSettings(markdown_backend="python-markdown")` or the corresponding JSON,
environment, or mapping key selects the optional compatibility backend. Install
its `legacy-markdown` extra from the checkout before selecting it. Invalid
backend names fail validation. See [renderer migration](markdown-migration.md)
for output differences, limits, and publication-plan invalidation.

## Explicit initialization and local profiles

```bash
pnbp init ~/notes --dry-run
pnbp init ~/notes
pnbp init ~/notes --profile work
```

Initialization creates the notebook directory if needed, writes portable
`.pnbp/settings.json` with useful defaults, and explicitly initializes
[stable notebook/note identities](identities.md). It does not move or create a Git
repository. Repeating initialization preserves existing settings. Dry runs
validate and return a JSON plan without creating directories or writing state.

Profiles map names to absolute local notebook paths in
`$XDG_CONFIG_HOME/pnbp/profiles.json` (default `~/.config/pnbp/profiles.json`).
`PNBP_PROFILES` selects another registry location. Profiles never contain
credentials. Reusing a name for another path fails rather than rebinding it.

```python
nb = Notebook.open(profile="work")
```

Use `pnbp --profile work ...` or `pnbp --notebook ~/notes ...` to select a notebook
for CLI commands. See [note editing and reports](editing.md).

`PNBP_PROFILE=work` selects a profile when no explicit path or `NOTE_PATH` is
provided. Profile names accept 1–64 letters, digits, underscores, or hyphens,
starting with a letter or digit.

## Preview and migrate legacy settings

```bash
pnbp init ~/notes --migrate --dry-run
pnbp init ~/notes --migrate
```

Migration validates the legacy object, writes portable settings and any separate
credential file, and verifies their contents before removing the root legacy
file. The original bytes remain in `.pnbp/legacy-settings.json`, with private
permissions. Extension settings survive migration. Repeating migration after
success reports `unchanged` and preserves the original backup.

Handled write or verification failures remove newly created migration outputs
and retain the original file. A detected external edit aborts migration. If a
process is terminated between writes, keep the original and backup, move partial
new outputs aside, and preview the migration again. Simultaneous old/new settings
are never silently chosen or overwritten. Backup removal is an explicit user
choice after verifying the migrated notebook.

## Credentials and sharing

Use `api_token="..."` for explicit in-memory credentials, `API_TOKEN` in the
environment, or a local `.pnbp/secrets.json` object containing only `API_TOKEN`.
Credential precedence is explicit token > environment > separate secret file >
legacy token. Legacy tokens remain readable for compatibility. Token refresh
writes only the separate secret file using atomic replacement and mode `0600`;
it leaves portable and legacy settings unchanged. With settings disabled,
refresh updates only the current instance.

Initialization and migration output paths and actions, never setting or token
values. Do not share the secret file or the legacy backup. Notebook Git commands
exclude root legacy settings, the new secret file, credential temporary files,
the legacy backup, and recovery drafts even without `.gitignore` setup. `pnbp init-git-ignore`
adds matching rules. Portable `.pnbp/settings.json` can be committed deliberately;
review its local paths and site settings before sharing it.

For an independent server notebook, configure matching `SERVER_NOTEBOOK` and
`NOTEBOOK_SLUG` values and `ROUTE_MODE="namespaced"`. The default server scope is
`default`; see [independent notebooks](web.md#independent-notebooks).

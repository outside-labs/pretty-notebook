# A notebook from first note to published reading

These examples use the **0.10 checkout**. Install it as described in
the [package guide](pnbp.md); use the published release's documentation when
working with its wheel. Local Python examples below run in a temporary notebook
during the strict documentation build. Remote steps require a separately
configured site and owner/editor credentials.

```{testsetup} workflow
import os
from unittest.mock import patch
_environment = patch.dict(os.environ, {"PNBP_SETTINGS": "off"}, clear=True)
_environment.start()
```

## 1. Open and initialize deliberately

Opening an existing directory is read-only. For a scratch notebook, create a
temporary directory; substitute your own existing path when keeping the notes:

```{doctest} workflow
>>> from pathlib import Path
>>> from tempfile import TemporaryDirectory
>>> from pretty_notebook import Notebook
>>> workspace = TemporaryDirectory()
>>> root = Path(workspace.name)
>>> nb = Notebook.open(root, settings={"NOTE_NESTED": "recurs"})
>>> assert list(root.iterdir()) == []
```

For a persistent notebook, the CLI initializes settings and identities together:

```bash
pnbp init ~/notes --dry-run
pnbp init ~/notes
```

The equivalent Python steps are explicit settings initialization followed by
identity initialization. A dry run leaves the scratch directory untouched:

```{doctest} workflow
>>> from pnbp.settings import initialize_notebook
>>> plan = initialize_notebook(root, dry_run=True)
>>> assert list(root.iterdir()) == []
>>> _ = initialize_notebook(root)
>>> nb = Notebook(root, settings={"NOTE_NESTED": "recurs"})
>>> _ = nb.initialize_identities()
>>> assert (root / ".pnbp/settings.json").is_file()
>>> assert nb.notebook_id is not None
```

Profiles, precedence, legacy migration and credential storage are described in
[settings](settings.md). Initialization does not create a Git repository.

## 2. Add a note, stage text and save

Create an initial note and a linked index. These writes register their note IDs
because identities were deliberately initialized:

```{doctest} workflow
>>> _ = nb.generate_note("guides/first", "# Overview\n\nA first idea. #public #work\n")
>>> _ = nb.generate_note("index", "# Index\n\nRead [[guides/first#overview]]. #public #work\n")
>>> note = nb.get("guides/first", fuzzy=False)
>>> original_id = note.note_id
>>> note.md_out = note.current_md + "\nA café example.\n"
>>> assert note.is_unsaved
>>> assert "café" not in (root / "guides/first.md").read_text()
>>> rendered = nb.convert_to_html(note)
>>> assert "café" in rendered and note.is_unsaved
>>> note = note.save(nb)
>>> assert note.note_id == original_id and not note.is_unsaved
>>> assert "café" in (root / "guides/first.md").read_text()
```

Keep the returned note after save. `md` remains a loaded snapshot, while
`current_md` selects pending text. An empty string is an intentional empty body;
discarding it returns to the loaded source:

```{doctest} workflow
>>> note.md_out = ""
>>> assert note.current_md == "" and note.is_unsaved
>>> _ = note.discard_changes()
>>> assert "café" in note.current_md and not note.is_unsaved
```

CLI alternatives are `note add`, `note edit --content`, `note edit --file` and
interactive `note edit`. See [editing](editing.md) for source-change checks,
reload rules and retained drafts on failure.

## 3. Resolve a link and preview a rename

Resolve explicitly, then preview the identity-preserving rename before writing:

```{doctest} workflow
>>> resolution = nb.resolve_link("guides/first#overview", source="index.md")
>>> assert resolution.state == "resolved" and resolution.path == "guides/first.md"
>>> preview = nb.rename_note("guides/first", "overview", dry_run=True)
>>> assert preview["dry_run"] and (root / "guides/first.md").exists()
>>> applied = nb.rename_note("guides/first", "overview")
>>> renamed = nb.get("guides/overview", fuzzy=False)
>>> assert renamed.note_id == original_id
>>> assert not (root / "guides/first.md").exists()
>>> assert "[[guides/overview#overview]]" in nb.get("index", fuzzy=False).current_md
```

The same workflow is available with `note rename SOURCE NAME --dry-run`, followed
by the command without `--dry-run`. Source paths, stable IDs, titles and public
URLs remain separate. [Links and moves](links.md) explain backlink repair and
journal recovery; [identities](identities.md) explains clones, forks and external
moves.

## 4. Search the current local notebook

Search is literal by default and sees pending text. Select a field and exact tag
filters deliberately:

```{doctest} workflow
>>> hits = nb.search("café", tags=("work",))
>>> assert [hit.name for hit in hits] == ["guides/overview"]
>>> assert hits[0].field == "content"
>>> titles = nb.search("overview", field="title")
>>> assert [hit.name for hit in titles] == ["guides/overview"]
>>> renamed.md_out = renamed.current_md + "\nAn unsaved discovery.\n"
>>> assert nb.search("unsaved discovery")[0].name == "guides/overview"
>>> _ = renamed.discard_changes()
>>> assert nb.search("unsaved discovery") == []
```

```bash
pnbp --notebook ~/notes search 'café' --tag work --json
pnbp --notebook ~/notes search 'overview' --field title
```

Local search includes private notes. It does not publish them or record visits.
See [local search](local-search.md) for bounds, offsets and the optional local regex.

## 5. Browse a snapshot and record visits explicitly

Navigation derives directories, heading outlines and backlinks without writing
generated notes. Use a public-only snapshot to omit local private notes:

```{doctest} workflow
>>> index = nb.navigation_index(public_only=True)
>>> assert index.directory().directories == ("guides",)
>>> assert index.directory("guides").notes[0].path == "guides/overview.md"
>>> assert index.outline("guides/overview")[0].anchor == "overview"
>>> assert [entry.path for entry in index.backlinks("guides/overview")] == ["index.md"]
>>> assert index.breadcrumbs("guides/overview")[-1].is_note
>>> assert index.neighbors("guides/overview").next.path == "index.md"
>>> assert index.related("guides/overview")[0].note.path == "index.md"
```

Ordinary lookup and search do not record visits. Each traversal object has its
own bounded in-memory history, including deliberate Back and Forward:

```{doctest} workflow
>>> history = nb.traversal(public_only=True)
>>> assert history.current is None
>>> _ = nb.get("guides/overview", fuzzy=False)
>>> assert history.current is None
>>> _ = history.visit("guides/overview")
>>> _ = history.visit("index")
>>> assert history.back().name == "guides/overview"
>>> assert history.forward().name == "index"
```

Rebuild snapshots after changes. [Navigation](navigation.md) explains related
ranking, title selection, visibility and traversal through managed renames.

## 6. Preview routes before publishing

Choose hierarchical routes explicitly. The preview produces URLs without
creating HTML, contacting the server or mutating identity state:

```{doctest} workflow
>>> publishing = Notebook(root, settings={"NOTE_NESTED": "recurs", "ROUTE_MODE": "hierarchical"})
>>> routes = publishing.publication_routes()
>>> assert {route["route"] for route in routes["routes"]} == {"/guides/overview", "/index"}
>>> assert not (root / "html").exists()
```

The [routes guide](routes.md) covers aliases, collision review, namespaced paths
and URL prefixes. Set the notebook's `URL_PREFIX` and server's `PNBP_URL_PREFIX`
to the same value, and include that prefix in `API_BASE`.

## 7. Review a checked publication plan

First configure the [supported web deployment](web.md), bootstrap its owner,
and store a bearer token using the [credential rules](settings.md#credentials-and-sharing).
Save the reviewed `API_BASE`, discovery mode and route settings in the portable
notebook settings before using CLI publication; keep tokens in the separate
credential file or `API_TOKEN` environment variable. Then preview:

```bash
pnbp --notebook ~/notes commit-stage --json --mode checked
```

For Python, reopen the publication notebook with the same hierarchical route
mode and the reviewed site configuration. This example uses a site mounted at
`/notes` and an owner/editor token supplied through `API_TOKEN`; substitute your
site's actual URL and matching prefix. It exposes an immutable plan and bounded
preview:

```python
import os

publishing = Notebook(
    root,
    settings={
        "NOTE_NESTED": "recurs",
        "ROUTE_MODE": "hierarchical",
        "API_BASE": "https://notebook.example/notes",
        "URL_PREFIX": "/notes",
    },
    api_token=os.environ["API_TOKEN"],
)
plan = publishing.prepare_publication(mode="checked")
preview = plan.preview(limit=100)
# Review creates, updates, preserved pages and conflicts before proceeding.
result = publishing.execute_publication(plan)
```

Preview reads remote capabilities/inventory; it writes no publication or local
sync receipts. Execute only after reviewing that concrete plan. The client
revalidates source and remote revisions, stops on conflict, and records successful
receipts. Retry partial success by preparing a fresh plan. The CLI equivalent
for a fresh reviewed run is `commit-remote --mode checked`.

Remote pages are preserved by default. Use `--prune` only after reviewing a
pruning plan and establishing that this notebook owns the selected remote
page namespace. [Checked publishing](checked-publishing.md) is the canonical
protocol and recovery guide.

## 8. Configure presentation and read the published result

Use [reviewed local assets](assets.md) for production; diagrams and code copying
load their assets only when the page needs them. After installing the web app's
declared requirements and configuring private storage and signing settings from
the deployment guide, verify the reviewed assets and start the four-worker server:

```bash
cd apps/web
python install_assets.py --check
PNBP_ASSET_MODE=local gunicorn main:api --no-control-socket --workers 4 \
  --worker-class uvicorn_worker.UvicornWorker --bind 127.0.0.1:8000
```

Keep the production TLS proxy and Host allowlist from the deployment contract.
Set the site `TITLE` and
navigation settings, then send `commit-settings`. The owner can replace the
PNG favicon with `pnbp favicon ./site.png`; [site identity](web.md#site-titles-and-favicon)
documents PNG validation, durable storage and content-versioned browser URLs.

Visit a canonical publication URL, use `/n/search` for [public literal search](public-search.md),
and `/n` for the [published directory index and reading navigation](public-navigation.md).
A deployment prefix applies to all
of those routes. Local private notes are absent from public results and reading
navigation. Reader roles and multi-notebook ownership remain deferred.

The [web deployment guide](web.md) owns startup, local-host worker coordination, TLS,
bootstrap, backup and restore instructions. Package releases and hosted
documentation publication remain separate from notebook publishing.

```{testcode} workflow
:hide:

import json
from contextlib import redirect_stdout
from io import StringIO
from pnbp.cli import app

def run_cli(args):
    output = StringIO()
    with redirect_stdout(output):
        app.invoke(args)
    return output.getvalue()

cli_workspace = TemporaryDirectory()
try:
    cli_root = Path(cli_workspace.name) / "notes"
    run_cli(["init", str(cli_root), "--dry-run"])
    assert not cli_root.exists()
    run_cli(["init", str(cli_root)])
    commands = (
        ["note", "add", "first", "--content", "#public #work\nA café example.\n"],
        ["note", "edit", "first", "--content", ""],
        ["note", "edit", "first", "--content", "#public #work\nA café example.\n"],
        ["note", "rename", "first", "overview", "--dry-run"],
        ["note", "rename", "first", "overview"],
        ["note", "show", "overview"],
        ["identity", "status", "--json"],
        ["status", "--json"],
    )
    for command in commands:
        run_cli(["--notebook", str(cli_root), *command])
    result = run_cli(["--notebook", str(cli_root), "search", "café", "--tag", "work", "--json"])
    assert json.loads(result)["hits"][0]["name"] == "overview"
finally:
    cli_workspace.cleanup()
```

```{testcleanup} workflow
workspace.cleanup()
_environment.stop()
```

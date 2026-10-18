# Pretty Notebook package

Pretty Notebook is a Python library and command-line interface for interconnected
Markdown notebooks. A notebook is an existing directory of Markdown files;
a note is one source file. Wiki links, tags, code blocks and URLs have explicit
models, while ordinary Markdown remains the authoritative content.

## Choose a version

The 0.11 release is `pretty-notebook==0.11.0` on Python 3.11 or newer.
It supplies canonical `pretty_notebook` imports, compatible `pnbp` imports,
and the `pnbp` executable.

```sh
python -m pip uninstall pnbp
python -m pip install pretty-notebook==0.11.0
pnbp --help
```

Uninstall the old distribution before installing the release to preserve the
compatibility modules. See [package migration](https://github.com/outside-labs/pretty-notebook/blob/v0.11.0/docs/package-migration.md) and
[0.11 release notes](https://github.com/outside-labs/pretty-notebook/blob/v0.11.0/docs/release-0.11.0.md). The historical package is
`pnbp==0.9.0`; its versioned [release notes](https://github.com/outside-labs/pretty-notebook/blob/v0.11.0/docs/release-0.9.0.md) retain that contract.

For source development, install the checkout with
`python -m pip install --editable .`.

## First notebook and existing notebooks

Follow the [notebook workflow tutorial](https://github.com/outside-labs/pretty-notebook/blob/v0.11.0/docs/tutorials.md) for a temporary notebook,
initialization, pending edits, checked renames, search and navigation. Its local
examples are executed by the documentation build.

```python
from pretty_notebook import Notebook

nb = Notebook.open("~/notes", settings={"NOTE_NESTED": "recurs"})
note = nb.get("guides/overview", fuzzy=False)
```

The path must already exist. Opening reads files without prompting or creating
configuration. Initialize deliberately with `pnbp init PATH`; see the canonical
[settings and profile guide](https://github.com/outside-labs/pretty-notebook/blob/v0.11.0/docs/settings.md) for precedence, migration and credentials.
`Notebook()` continues to use `NOTE_PATH` for existing environment-based setups.

## Continue by topic

- [Note commands and pending edits](https://github.com/outside-labs/pretty-notebook/blob/v0.11.0/docs/editing.md): add/edit, empty bodies, saves and recovery drafts.
- [Models and methods](https://github.com/outside-labs/pretty-notebook/blob/v0.11.0/docs/pnbp_models.md) and [generated API reference](https://github.com/outside-labs/pretty-notebook/blob/v0.11.0/docs/reference.md): public imports and signatures.
- [Local search](https://github.com/outside-labs/pretty-notebook/blob/v0.11.0/docs/local-search.md), [navigation](https://github.com/outside-labs/pretty-notebook/blob/v0.11.0/docs/navigation.md) and [links](https://github.com/outside-labs/pretty-notebook/blob/v0.11.0/docs/links.md): read-only projections and explicit traversal.
- [Stable identities](https://github.com/outside-labs/pretty-notebook/blob/v0.11.0/docs/identities.md) and [publication routes](https://github.com/outside-labs/pretty-notebook/blob/v0.11.0/docs/routes.md): identity, source paths and URLs remain separate.
- [Checked publishing](https://github.com/outside-labs/pretty-notebook/blob/v0.11.0/docs/checked-publishing.md): dry-run plans, ETags, retries and explicit pruning.
- [Web deployment](https://github.com/outside-labs/pretty-notebook/blob/v0.11.0/docs/web.md): separate application, bootstrap, durable state and the supported local-host worker profile.

The macOS URL handlers are [unsupported](https://github.com/outside-labs/pretty-notebook/blob/v0.11.0/docs/pnano.md). The FastAPI app and its
optional dependencies are absent from the canonical wheel; `pnbp` is metadata only.

# Pretty-Notebook

A Python toolkit for interconnected Markdown notebooks. The repository also
contains a FastAPI publisher with a constrained public-deployment profile.

The `0.11.0` release supports the `pretty_notebook` Python package and its `pnbp`
command-line interface on Python 3.11 or newer:

```bash
python -m pip install --upgrade pip
python -m pip install pretty-notebook==0.11.0
```

The repository supports the `apps/web` publisher as one Gunicorn instance with up to four workers,
one local SQLite database and explicitly owned public notebooks behind a TLS reverse proxy. Read the
deployment contract and security boundaries before exposing it publicly. The
macOS URL handlers remain unsupported.

[Documentation index](docs/index.md) · [Workflow tutorial](docs/tutorials.md) · [0.11.0 release notes](docs/release-0.11.0.md) · [Web deployment](docs/web.md) · [Development roadmap](docs/roadmap.md)

The current release is `pretty-notebook==0.11.0`. It includes settings/profiles,
identities, checked publication, search/navigation, reference-style appearance
preferences, a typed Markdown parser, the expose-interface CLI, deployment and
backup tools, scoped notebook ownership and durable redacted operation logs. Upgrade an old installation:

```sh
python -m pip uninstall pnbp
python -m pip install pretty-notebook==0.11.0
```

The final `pnbp==0.11.0` distribution installs the canonical package and contains
no implementation modules. [0.11 release notes](docs/release-0.11.0.md) and
[versions/support](docs/versions.md) define the supported scope. Tagged GitHub
documentation is the release reference; hosted documentation remains separate.

New code uses `from pretty_notebook import Notebook, Note`; existing `pnbp`
imports and the `pnbp` executable remain compatible. See the
[package migration](docs/package-migration.md) before upgrading old installations.

```mermaid
graph BT
	id1[(Notebook)]
	id2[(Note)] --> id1
	Link --> id2
	Url --> id2
	CodeBlock --> id2
	Tag --> id2
```

<p align=center>
  <img src=https://raw.githubusercontent.com/outside-labs/pretty-notebook/main/docs/IMG_pnbp.png alt=Pretty-Notebook width=200>
</p>

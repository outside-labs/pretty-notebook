# Package naming and upgrades

Since 0.10, the canonical distribution is `pretty-notebook`, with the import
package `pretty_notebook`. The executable remains `pnbp`:

```python
from pretty_notebook import Notebook, Note
```

The release version is `0.11.0`. Remove an old `pnbp` installation
before installing it:

```sh
python -m pip uninstall pnbp
python -m pip install pretty-notebook==0.11.0
```

The final `pnbp==0.11.0` is a metadata-only compatibility distribution
that depends on `pretty-notebook==0.11.0`. It does not contain implementation
modules or its own executable. The canonical package owns all imports and CLI
files. New installations should request `pretty-notebook` directly.

The 0.10 compatibility package pins the 0.10 canonical version. When retaining
that metadata-only package, upgrade both names together so dependency checks
remain consistent:

```sh
python -m pip install --upgrade pretty-notebook==0.11.0 pnbp==0.11.0
```

The uninstall-first instructions above remain required for pre-0.10 packages
that own implementation files.

The new distribution includes compatibility wrappers for `pnbp`, its models,
helpers, commands, CLI and former private modules. Existing imports resolve to
the same classes, exceptions and leaf modules, so a notebook is not maintained
twice. Prefer the canonical import in new code. No import initializes notebook
settings, identities, Git or server state.

Private implementation helpers now live in `pretty_notebook._internal`, with
ordinary descriptive module names. The underscore marks a private package;
applications should use the documented public API. The compatibility package
retains old private module spellings for the transition.

Distribution names and import names are independent. Upgrading directly from
an old `pnbp` wheel can install the canonical dependency before removing the old
wheel's shared files. Always uninstall the old distribution first; notebooks
and settings remain outside the package installation. If the new package was
installed before that removal, reinstall `pretty-notebook` afterward to restore
its recorded compatibility files.

Both release distributions use `release.yaml` and the `pypi` environment.
Candidate releases upload only `pretty-notebook`. Final releases upload the
canonical package first and the metadata-only `pnbp` package afterward.

`uv.lock` is committed for reproducible development installations. It pins
development resolution without constraining downstream library users beyond
`pyproject.toml`. Update the lock when metadata or dependencies change; use
`uv lock --check` to detect drift. The web app retains its separate hashed
`apps/web/requirements.lock`.

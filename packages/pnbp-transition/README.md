# pnbp: package-name compatibility

The `pnbp` distribution installs the matching `pretty-notebook` release.
The implementation, `pretty_notebook` and compatible `pnbp` imports, and the
`pnbp` command-line executable all belong to `pretty-notebook`.
This distribution contains metadata only, with no competing Python modules.

When upgrading from `pnbp==0.9.0` or earlier, remove that old distribution
**before** installing the new one. Its recorded files overlap the compatibility
imports now owned by `pretty-notebook`; installing dependencies before removing
the old wheel can remove those newly installed files.

```sh
python -m pip uninstall pnbp
python -m pip install pretty-notebook==0.11.0
```

Notebook Markdown and settings are data outside the package installation.
Back them up before upgrading and follow the
[migration guide](https://github.com/outside-labs/pretty-notebook/blob/v0.11.0/docs/package-migration.md).
New installations should request `pretty-notebook` directly.

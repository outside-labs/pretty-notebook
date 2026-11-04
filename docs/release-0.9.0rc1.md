# pnbp 0.9.0rc1

`0.9.0rc1` is the release candidate for the Pretty Notebook `pnbp` package. It focuses on data safety, deterministic lookup and matching, publication failure handling, CLI correctness, configuration behavior, and regression coverage before the final `0.9.0` release.

## Installation

The release candidate is published on [PyPI](https://pypi.org/project/pnbp/0.9.0rc1/). Install this exact pre-release build with:

```sh
python -m pip install pnbp==0.9.0rc1
```

Python 3.11 or newer is required.

## Migration notes

- The supported command-line entry point is `pnbp` with subcommands. Older `nb-*` / `nbn-*` command entry points are not the 0.9 interface.
- Exact note lookup is preferred. Approximate mutation targets require explicit fuzzy acceptance where the command supports it.
- `PNBP_SETTINGS=off` disables `pnbp_settings.json` loading even when that file exists.
- `pnbp commit-settings` targets the configured remote by default; use `--local` explicitly for the local service.
- Cleanup commands revalidate destructive targets at execution time and refuse destructive cleanup while notes have unsaved changes.

## Candidate safety and correctness work

The RC incorporates regression-backed work for:

- non-publishing pull-request CI and package smoke checks;
- non-mutating note inspection/rendering and failure-safe persistence;
- transactional task settlement;
- exact public-note eligibility, publication preflight, and failure-aware synchronization;
- contained code extraction and notebook-scoped Git automation;
- literal-code-safe rendering;
- exact-first lookup, stable component semantics, and correct multi-value query behavior;
- non-recursive collection dispatch, restored collection commands, and safer cleanup/empty-note operations;
- configuration-off behavior, generated defaults, explicit local/remote selection, and redacted token refresh output.

## Known unsupported surfaces

The installable `pnbp` package is the scope of this release candidate. These repository surfaces are **not** supported production features in `0.9.0rc1`:

- `apps/web` is experimental and is not supported for public deployment until the separate web deployment safety gate is completed.
- `pnano.app` and `ppnbp.app` protocol handlers are experimental/unsupported.
- For 0.9, one notebook must own the complete publication namespace to use `--prune`. Publication ownership across multiple independent notebooks/users is not yet supported; do not share one destructive prune namespace between them.

## Candidate publication and verification

The [v0.9.0rc1 GitHub Release](https://github.com/wispsy/pretty-notebook/releases/tag/v0.9.0rc1) triggered a [successful release workflow](https://github.com/wispsy/pretty-notebook/actions/runs/36261592281). Its build job checks the tag against the package version, compiles Python with warnings as errors, runs the release-blocking Ruff rules and regression suite, builds the source and wheel distributions, checks metadata with Twine, and smoke-tests an installed wheel with `pip check`, `import pnbp`, `pnbp --help`, and a Notebook load. A separate protected-environment job publishes to PyPI through trusted publishing.

The subsequent [final-release readiness exercise](release-0.9.0-readiness.md)
validated the candidate on Python 3.11 and 3.14 and recorded a GO decision for
final `0.9.0` preparation. Web deployment safety remained a separate decision;
it was later approved only for the constrained topology in the
[web deployment contract](web.md).

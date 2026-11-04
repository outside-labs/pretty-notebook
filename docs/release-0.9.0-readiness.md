# pnbp 0.9.0 final-release readiness

## Decision

**GO** to prepare the final `pnbp 0.9.0` release.

The published `0.9.0rc1` wheel passed representative library, CLI, local
publication, and authenticated remote-publication exercises on both supported
Python versions. No release-blocking package defect or unresolved candidate
report was found. Publication remains a separate REL-03 action with its own
version, build, tag, and installed-wheel gates.

Validation was completed on 2026-10-01 in America/Los_Angeles
(2026-10-02 UTC).

## Candidate and environment

| Item | Value |
| --- | --- |
| Candidate | `pnbp==0.9.0rc1` from PyPI |
| GitHub Release | [`v0.9.0rc1`](https://github.com/wispsy/pretty-notebook/releases/tag/v0.9.0rc1) |
| Release target | `4497b81c0c2a7be38b35009473745aaf27876b65` |
| Wheel | `pnbp-0.9.0rc1-py3-none-any.whl` |
| Wheel SHA-256 | `67cbceb81865e34be89f5f798e557b9aa318dbb9ae716725c2aeb0b838d6efcf` |
| Platform | Linux x86_64 |
| Python | CPython 3.11.16 and 3.14.7 |
| Install | Clean virtual environments, exact version, wheel-only, no pip cache |

Both environments reported `pnbp 0.9.0rc1` from their isolated
`site-packages`, and `pip check` reported no broken requirements.

## Representative notebook

The same fresh fixture was exercised independently on Python 3.11 and 3.14.
It contained:

- two `#public` notes with reciprocal wiki links;
- one `#private` note;
- an embedded PNG;
- an external URL, an inline-code wiki link, and a fenced-code wiki link;
- a Mermaid block and a Markdown table; and
- strikethrough and highlight syntax.

## Results

| Surface | Exercise | Python 3.11 | Python 3.14 |
| --- | --- | --- | --- |
| Install | Exact PyPI wheel, version check, dependency check | Pass | Pass |
| Loading | Load all three Markdown notes from a fresh notebook | Pass | Pass |
| Lookup | Exact terminal-extension lookup, disabled fuzzy miss, explicit fuzzy match, regex search | Pass | Pass |
| Editing | Set pending text, save atomically, reload, and confirm clean state | Pass | Pass |
| Rendering | Internal/external links, literal code, Mermaid, image, table, strikethrough, and highlight | Pass | Pass |
| CLI | Root help, `pprint`, and `collect-all-public` | Pass | Pass |
| Local publication | `commit-html` emitted only the two public pages | Pass | Pass |
| Staging | `commit-stage` reported both new pages without changing the server | Pass | Pass |
| Local endpoint | `commit-local` uploaded pages and the referenced image | Pass | Pass |
| Configured endpoint | `commit-remote` completed against the configured API base | Pass | Pass |
| Layout | `commit-settings` updated the rendered site title and navigation | Pass | Pass |
| Public reads | Both public pages and the image loaded; the private slug returned `404` | Pass | Pass |
| Default synchronization | A remote-only stale page remained without `--prune` | Pass | Pass |
| Explicit pruning | `commit-remote --prune` removed only the staged stale page | Pass | Pass |
| Final inventory | Remote pages were exactly `alpha.html` and `beta.html` | Pass | Pass |

The remote exercises used the separately approved WEB-05 topology: one
Gunicorn worker, one local SQLite database, one persistent data root, and one
notebook owning the publication namespace.

## Dependency and repository checks

The installed candidate dependency graph had no known vulnerabilities after
bringing the virtual environment's installer packages current. The stock
Python 3.11 environment initially supplied old `pip` and `setuptools` versions;
the findings were confined to those installers, not `pnbp` or its runtime
dependencies. Upgrading to `pip 26.2.1` and `setuptools 84.0.0` cleared the
audit, and `pip check` remained clean.

The post-WEB-05 [`main` workflow](https://github.com/wispsy/pretty-notebook/actions/runs/36947023433)
also passed all five jobs at commit
`6ca9b53956f18bf0b732b2a3a74cceae91d5b11d`: Python 3.11, Python 3.14,
distribution build and installed-wheel smoke, Web API 3.11, and Web API 3.14.
The web jobs exercised the supported production process command.

## Feedback and triage

No open repository issue reports a defect in the release candidate. Work found
after RC publication was triaged and completed through focused changes for web
integration coverage, bootstrap safety, public routes and local inbox storage,
atomic writes, dependency locking and advisories, release boundaries, and the
public-deployment safety gate.

The remaining open feature items are explicitly post-0.9:

- PUB-04: shared multi-notebook publication ownership; and
- APP-01: macOS URL-handler support.

Neither changes the supported final package contract.

## Final supported scope

The GO decision covers the `pnbp` library and CLI on Python 3.11 or newer. It
also permits the repository web application only in the separately documented
single-worker, single-SQLite, single-notebook deployment profile.

The decision does not cover shared multi-notebook pruning, horizontally scaled
web deployments, untrusted web editors, or the macOS URL handlers.

## REL-03 gates

Before publication, REL-03 must still:

1. change the package version to `0.9.0` and finalize release notes and scope
   documentation;
2. pass the tag/version guard, Python matrix, source and wheel builds, strict
   metadata checks, installed-wheel smoke test, and dependency checks;
3. identify the exact release commit and create `v0.9.0` from that commit; and
4. verify the GitHub Release, trusted PyPI publication, and a fresh install from
   PyPI.

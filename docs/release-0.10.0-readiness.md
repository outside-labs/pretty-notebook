# Pretty Notebook 0.10 readiness

The candidate is `pretty-notebook==0.10.0rc2`, selected by `v0.10.0rc2`.
The `pnbp` compatibility distribution is built and checked alongside it but is
uploaded only for the final release.

Before final publication:

1. Verify passing library, web/coverage, JavaScript, deployment and strict docs CI.
2. Install the actual candidate from PyPI in fresh Python 3.11 and 3.14 environments.
3. Verify canonical/legacy import identity, CLI/deployment resources and dependency consistency.
4. Run `scripts/exercise_release.py 0.10.0rc2` against fresh synthetic notes.
5. Save synthetic notes with the published 0.9 wheel, uninstall it, install the
   candidate, then exercise legacy settings migration, identity-preserving rename,
   backlink repair, pending save, routes, search/navigation and local publication.
6. Check old-server state restore, legacy-client behavior, hash/image updates and
   worker coordination using the existing web integration and deployment checks.

Preserve source and data backups. A final GO requires no unresolved data-loss,
migration or publication-conflict defect. Hosted documentation and actual VPS
activation are deferred; tagged GitHub documentation provides the release reference.

## Candidate evidence and final publication gate

- Candidate source: `b66c671730cd20a4b5f0994c95651dffe6263496`, tag `v0.10.0rc2`.
- Library, web/coverage, JavaScript, packaging, deployment and strict docs CI
  passed before candidate publication.
- The [rc2 release build](https://github.com/wispsy/pretty-notebook/actions/runs/38091094329)
  passed on supported Python 3.14, including both distribution builds, strict
  metadata/ownership checks and the installed-wheel notebook exercise.
- The earlier rc1 build stopped on the inherited Python 3.12 deployment check;
  [the correction](https://github.com/wispsy/pretty-notebook/pull/165)
  moved release builds to supported Python 3.14. No rc1 packages were uploaded.
- The repository was renamed to `wispsy/pretty-notebook` to match the
  pending publisher registration. Rerunning the failed upload succeeded;
  [the actual PyPI candidate](https://pypi.org/project/pretty-notebook/0.10.0rc2/)
  is available. Publisher fields are owner `wispsy`, repository
  `pretty-notebook`, workflow `release.yaml`, and environment `pypi`.
- The actual PyPI wheel passed the library suite on Python 3.11.16 and 3.14.7:
  427 tests passed on each interpreter. Two Linux-only unit/nginx checks were
  skipped locally and passed in the Linux CI job.
- Both interpreters passed the fresh synthetic notebook exercise and the
  documented upgrade from the actual published `pnbp==0.9.0` wheel. The old
  package was uninstalled before installing the candidate. Settings dry-run and
  private backup, pending saves, identity-preserving rename/backlinks, flat to
  hierarchical routes, search/navigation and local HTML publication passed.
- Canonical/legacy imports resolve to the installed PyPI wheel and share the
  same `Notebook` class. Dependency checks, CLI help and deployment-plan resource
  loading passed on both interpreters.
- Both prepared final `0.10.0` wheel/source distributions pass strict metadata
  and ownership checks. The local notebook migration/edit/route/search exercise
  passes for the prepared final library.

**Candidate GO.** No data-loss, migration or publication-conflict defect remains
from the representative exercise. The final source changes the version to
`0.10.0` and uses the lowercase repository URLs. Final tagging follows passing
final-version CI. Publication uploads the canonical package before the
metadata-only compatibility package; completion requires both actual PyPI
distributions and fresh-install checks. Hosted docs and live VPS activation
remain separate operations.

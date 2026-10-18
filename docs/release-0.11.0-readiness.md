# Pretty Notebook 0.11 readiness

The selected foundation scope is recorded in
[REL-05](https://github.com/outside-labs/pretty-notebook/issues/105).
The release is `pretty-notebook==0.11.0` plus metadata-only `pnbp==0.11.0`.

## Implementation evidence

- Scoped roles/grants/credentials: [PR #181](https://github.com/outside-labs/pretty-notebook/pull/181).
- Independent public notebook ownership: [PR #182](https://github.com/outside-labs/pretty-notebook/pull/182).
- Durable redacted operation logs: [PR #183](https://github.com/outside-labs/pretty-notebook/pull/183).
- Typed Markdown, CLI and operations changes retain their focused PR/check
  history in the Project. The complete foundation preserves the Python 3.11+
  library contract and existing coordinated worker/SQLite deployment.

Local feature verification passed 1,456 core tests (two platform validators run
in Linux CI), 381 web tests and 98% branch coverage. Focused scenarios cover two
owners using identical note/image names, grants and script credentials,
cross-notebook write/prune denial, a populated catalog upgrade, restart and
partial publication recovery, and bounded redacted operation receipts.

## Final publication gate

1. Require fresh passing checks for each reconciled PR and final main: Python
   3.11/3.14, distribution metadata/ownership, web integration/branch coverage,
   JavaScript, strict documentation/examples, Linux configuration and container
   startup/restart/restore.
2. Exercise complete stopped-site backup/restore with independent notebooks,
   retained grants, revoked credentials, images and durable operation logs.
3. Build matching wheel/source distributions; run strict Twine and ownership
   checks. Fresh installs must preserve canonical/compatibility import identity,
   `pnbp` help/resources and the synthetic migration/edit/route/search exercise.
4. Exercise an actual 0.10 PyPI installation upgraded to the prepared wheel on
   Python 3.11 and 3.14. Keep base installs free of Python-Markdown and Click.
5. Tag only the reviewed passing final source. Publish the canonical package
   first and compatibility package second using `release.yaml` and the `pypi`
   trusted-publisher environment.
6. Verify both actual PyPI versions, artifact hashes and fresh installations
   after publication. Keep release receipts in REL-05 and the release PR.

No unresolved data-loss, permission-isolation or migration defect can pass this
gate. Browser/private/source-sync/editor features remain deferred in full.
Hosted documentation activation and live deployment are outside this release.

## Prepared release verification

Both 0.11.0 wheel/source distribution pairs pass strict Twine metadata checks
and the implementation-file ownership checks. The compatibility package pins
the canonical version exactly and owns no import modules or executable.

Actual PyPI 0.10.0 installations were upgraded to the prepared wheels on Python
3.11.16 and 3.14.7. Existing initialized notebooks retained settings, identity,
source, pending saves, rename/backlink repair, search and local publication.
Both interpreters also passed the fresh synthetic release exercise, import
identity, CLI/deployment resources, log receipts and dependency consistency.
After removing the previous optional packages, both base installations operate
without Python-Markdown, Click or FastAPI.

The complete stopped-site restore check now preserves two notebook owners,
separate same-named images, live grants, revoked credentials and operation logs;
post-restore cross-notebook publication/pruning remains denied. Strict Sphinx,
six documentation checks and all 70 executable examples passed locally.
Final reconciled-head/main CI and actual PyPI publication verification remain
the required final steps; their exact receipts are recorded in REL-05.

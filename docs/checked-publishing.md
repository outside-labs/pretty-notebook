# Checked publishing

The optional web server supports the authenticated `revision-1` protocol alongside
the legacy 0.9 publishing endpoints. It retains the supported one-host, local-SQLite
deployment profile and selects one explicitly granted notebook per API request.
`X-PNBP-Notebook` selects a registered notebook; absent headers select `default`.
See [independent notebooks](web.md#independent-notebooks).

Read `GET /api/publishing/capabilities` to negotiate the protocol. A client may
fall back to legacy mode only when capabilities return 404; authentication,
transport, and server failures must stop publishing. Legacy mode uses timestamps
and cannot provide checked revision guarantees.

`GET /api/publishing/inventory` returns the server notebook ID, public pages, and
images. Pages include strong ETags, revisions, source and rendered SHA-256 hashes,
renderer fingerprints, aliases, and detected HTML feature flags. Legacy source
hashes and fingerprints remain unknown until replaced by a checked publication.
Files added outside the catalog after startup have no checked ETag: restart from
stable storage to import them before checked publishing.

Use `PUT /api/publishing/publication` with `name`, `content`, `source_hash`,
`rendered_hash`, and `renderer_fingerprint`; optional `title`, `aliases`, and
`previous_name` support route metadata and explicit migration. Hash exact source
bytes and UTF-8 HTML bytes with SHA-256. The server verifies the HTML digest and
stores source/fingerprint metadata with the immutable revision. Submitted IDs and
client clocks never authorize or select an update.

Creates require `If-None-Match: *`. Updates and deletes require the inventory's
strong `If-Match` ETag. A successful write returns its committed ETag and revision.
Delete with `DELETE /api/publishing/publication/{canonical-name}`; omit `.html`.
Recreating a deleted page keeps its history and produces a different ETag.

Missing preconditions return 428; unsupported or conflicting precondition headers
return 400. Stale representations return 412. Route/alias collisions return 409.
Refresh and review a new plan after a conflict. Publication comparison and head
selection occur inside the same SQLite transaction. Failed writes preserve the
previous head; complete unreferenced blobs remain eligible for orphan collection.

Images use `PUT /api/publishing/image` with the existing bounded multipart `file`
format and the same create/update preconditions. Inventory hashes and image ETags
describe exact bytes. Legacy and checked uploads share a process lock around
comparison and atomic replacement. Existing image validation and size bounds
apply. Inventory responses and every publishing API response use `no-store`.

## Local plans

`nb.publication_plan()` returns a bounded JSON-compatible dry-run. Its default
`mode="auto"` negotiates checked publishing and falls back only for a capabilities
404. Use `mode="checked"` to require the revision protocol or `mode="legacy"` to
explicitly use the 0.9 timestamp preview. Authentication, malformed capabilities,
and transport/server errors never trigger a downgrade.

`nb.prepare_publication()` returns an immutable checked plan. It binds the local
root, optional notebook UUID, identity metadata, exact source snapshots, server
notebook UUID, target URL, renderer fingerprint, and expected ETags. Passing
`mode="auto"` or `"legacy"` may return `None`, indicating a legacy server.
`plan.preview(limit=200)` omits source/HTML/image bodies and credentials.

Checked plans compare SHA-256 hashes of exact Markdown and image bytes, the actual
UTF-8 rendered HTML, and a fingerprint of renderer versions, code, and settings.
Changed timestamps alone do not publish. Changed bytes, renderer settings, link
resolution, titles, and new aliases can require an update. Remote pages are
preserved unless `prune=True`; missing checked revisions and route collisions
produce explicit conflicts. `refresh_images=True` explicitly resends matching
images. Image signatures and size limits are validated before mutation.

Planning reads capabilities, inventory, and the non-mutating route preview. It
does not create identities, sync receipts, output directories, or remote content.
The legacy preview retains its timestamp limits and cannot promise checked writes.

## Execution and recovery

`nb.execute_publication(plan)` revalidates the plan's root, target, notebook,
settings, identities, every Markdown source, images, rendered output, saved
checkpoint, and remote heads before writing. Images upload before pages. Every
mutation uses its planned strong ETag or a create-only precondition. The client
stops after any error and performs explicit pruning only after all uploads succeed
and the local snapshot is checked again.

`nb.post_commits_to_web_api()` negotiates and executes a fresh plan. Its
`stage_only=True` option returns a read-only preview. Remote pages remain preserved
by default. Receipts live in private `.pnbp/sync.json`, grouped by target and server
notebook identity. Each successful action is recorded by atomic replacement under
a short exclusive local write lock; failed actions never get successful receipts.
Successful no-op execution can adopt matching remote representations. Dry-run
does not write this state.

After partial success, retry with a fresh plan. Matching acknowledged content is
skipped. A committed write whose response or local checkpoint was lost can also be
recovered from matching source/rendered/fingerprint hashes in the authoritative
inventory. Review interrupted `.pnbp/sync.lock` files before retrying; do not remove
a lock belonging to a live write. Corrupt state, changed notebook identity, or a
different server notebook requires review of the target's checkpoint entry.

Remote edits or deletes since the last receipt become plan conflicts. Review
`nb.publication_plan()` before explicitly choosing `accept_remote=True` to publish
against the current remote versions. This choice still requires fresh checked
ETags and never bypasses concurrent-write protection. A newly appearing remote
page after a plan was prepared also requires replanning. Shared ownership and
shared pruning remain outside this protocol until PUB-04.

The CLI supports `--mode auto|checked|legacy` on `commit-stage`, `commit-remote`,
and `commit-local`. Preview with `pnbp commit-stage --json --mode checked --prune`;
publish with `pnbp commit-remote --mode checked`. After reviewing a remote conflict,
`--accept-remote` selects its current checked versions. `--prune` is always explicit
and requires sole ownership of the target's page namespace. Legacy mode retains
its 0.9 timestamp and concurrency limits.

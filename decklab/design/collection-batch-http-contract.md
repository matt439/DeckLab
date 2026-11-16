# Private collection-batch HTTP contract (staged)

Status: implemented as plain functions in `lib/api/collection_batches.py`, tested
through a fixture-only dispatch shim using the normal server. **No production route,
startup flag, browser control or numbered migration enables it.** The paths below
are reserved proposals, not currently available endpoints.

## Authority and transport

Proposed `GET/HEAD /api/collection/batches?space=...&batch_id=...` and
`POST /api/collection/batches` must use normal server method, JSON body, Origin and
X-Deck-Lab write checks. Every response is no-store. Future registration must add
explicit route-access metadata as well as dispatch; neither exists yet.

Use DeckLab's normal identity model: a verified tunnel profile or a named home-network
viewer. Home's chooser is limited to household profiles; member spaces use the
existing tunnel login. The chooser is not a new password-authentication mechanism. A
body profile must match that viewer, as `_writer` enforces. Normal tunnel transport
first replaces a supplied body profile with the verified login; it never grants the
supplied actor authority. A foreign space is still refused. Anonymous/script-body-only
access cannot claim private batches. Reads also require collection.edit for the space;
a public collection does not make its scratch batches public. The database rechecks
membership and own-space scope on every operation, including committed retries.
Household peers cannot read or complete one another's batches. No admin override.

## Reads

Without batch_id, return `{available:true, space, batches, has_more}`. The index has
at most ten entries: active draft first, then recent terminal batches. Entries contain
batch_id, revision, status, saved_at and draft label (null for terminal entries).
No pagination is implemented yet. An exact owned batch remains retrievable by ID.

With batch_id, return `{available:true, space, batch_id, revision, status, draft,
review, receipt}`. Committed/discarded batches have no draft content. A committed
receipt remains retrievable for lost-response recovery. Hidden/nonexistent IDs answer
the same generic 404. Foreign spaces follow existing generic permission refusals.

## Writes

All bodies require `profile`, `space`, `batch_id` (client-generated UUID) and `action`.
Unknown keys are refused. Bodies are bounded to 278,528 bytes; the draft has its own
256 KiB/200-card-group/30-unresolved-item bounds. No photo/OCR/price fields are accepted.

| action | Additional fields | Result and concurrency rule |
|---|---|---|
| create | draft | Same identity and original payload returns its current state. Conflicting reuse or another active draft is 409. |
| save | expect, draft | Absolute quantities; integer expected revision must match. Revision increases and prior review is invalidated. |
| review | expect | Validates the actual merge under the inventory lock, then returns stored review token and counts. No cards/import/audit are written. Invalid or ambiguous printings return no newly saved token. |
| discard | expect | Keeps a consumed-identity tombstone, never deletes the identity for reuse. |
| complete | review | Exact stored token, same batch identity and current inventory review. Returns committed receipt. Same committed retry returns the original receipt without another inventory/import/audit record. |

A second review at the same draft revision replaces its nonce and invalidates the
first tab's token. `true` or `1.0` is not an integer revision even if a language's
loose numeric equality would treat it as one. Completing a different physical pile
always requires a new batch UUID; identical card contents alone are not duplicates.

## Failures and recovery

- 400: malformed request; `batch_invalid` identifies draft/printing/condition/language validation.
- 403: no selected identity, writer mismatch, insufficient authority or departed member.
- 404 `batch_unavailable`: exact batch inaccessible or absent, without revealing ownership.
- 409 `batch_conflict`, `reload:true`: reload the owned batch. Never force overwrite.
- 413/415: body limit or incorrect transport content type, before processing.
- 503 `batch_not_installed`, `available:false`: capability is not enabled; do not claim a save.
- 503 `batch_unconfirmed`, `retry:"same_batch"`: database outcome is not confirmed. A write
  may have committed. Reload/retry the same identity; never start a replacement batch
  to repeat an uncertain addition. Infrastructure paths/errors are not returned.

Lost create acknowledgement: retry the same original payload/UUID, then honor the
returned current state. Lost save acknowledgement: reload and compare the persisted
revision/content; do not just substitute a new revision into an old write. Lost review
acknowledgement: read its stored token or explicitly review again. Lost completion
acknowledgement: retrieve/retry the same UUID and exact token; a receipt settles it.
Lost discard acknowledgement: reload its tombstone. A stale discard may answer 409.

## Remaining boundaries

No browser integration, durable status indicator, offline queue, pagination, automatic
retry loop or cross-device UI is shipped. The next browser slice must preserve one
stable UUID across uncertainty, show conflicts explicitly, avoid local-cache identity
leaks and never say saved before acknowledgement. Schema promotion and Linux CI
qualification remain coordinated gates. The adapter itself also needs independent
review before registration; current tests do not qualify real Cloudflare JWT validation
or real mobile browsers, which use existing separate authentication/device suites.


Staged draft contract v2 success responses include `draft_contract:2`. Rows preserve
separate condition/language groups (including blanks) of the same printing/finish.
See `batch-browser/metadata-contract-v2.md` for existing inventory transformation,
v1 fixture compatibility and downgrade limits. No numbered schema change occurs.


Staged v3 additionally advertises `draft_contract:3` and accepts optional bounded
scanner evidence; older content remains valid unchanged. Existing evidence cannot be
omitted by a later save. See `batch-browser/evidence-contract-v3.md`. No routes are
registered by this source-only contract extension.

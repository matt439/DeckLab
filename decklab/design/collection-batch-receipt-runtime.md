# Receipt-only runtime candidate, default-off and tunnel-only

Registration/privacy questions were technical risk decisions, not choices the owner
explicitly reserved. This candidate resolves output minimization and authentication in
code without choosing live activation: default settings still register neither GET nor POST.
An explicit boolean collection_batch_receipt_recovery setting now permits GET only on
the existing verified tunnel listener; the normal dispatcher, not a test shim, selects it.

Contract: exact UUID, current verified viewer and database membership, existing collection
permission. Own committed result returns only UUID, space, committed state and original
bounded receipt. No draft content, label, evidence, raw OCR, photo, review nonce or admission
offer is returned. Pending is explicitly unconfirmed; discarded is explicit but is not a
claim about other UUIDs or physical re-entry. Missing/foreign/retired UUIDs share the same
unavailable response. Missing schema or unavailable DB is never proof of no prior commit.
There is no new expiration timer or retention change: the retired-row test models a receipt
no longer available, not an invented supported expiry feature.

Proof uses actual repository signed-token verification, normal dispatcher/query/method guards,
HTTP no-store response, real temporary PostgreSQL, and merged owner tooling. Completion is
performed before pause, then exact owned receipt is read twice and original completion retried
without inventory/import/audit changes. Anonymous and peer reads, stale removed membership,
missing schema, unavailable DB and unsupported POST are covered. Nothing falls back to a
manual add or CSV. Tests alone perform synthetic DDL/data removal in isolated databases.

This is a practical adapter candidate, not a second shipped supported runtime or full two-
server rollback result. No deployment or user-facing installation was performed. The optional startup setting
remains absent/off in all real configuration; no example config was enabled. Separate
review must approve shipping this conditional registration, not merely its fixture proof.


## Listener boundary qualification

The existing tunnel startup forwards only an exact boolean true setting. Its Server keeps
recovery disabled on home listeners even if explicitly passed true. Dispatch requires both
that server-owned flag and verified remote identity; the adapter independently refuses LAN
chooser context. No request header can enable registration. Ordinary route tables remain
unchanged; optional GET access metadata is explicit. No POST path is registered.

Tests cover real normal remote startup with absent/false/string/true test settings, home
listener refusal, signed enabled GET, disabled 404, no-token and invalid-token 403, peer/missing
404 and stale-member 403. Authentication/authorization denials deliberately remain 403;
only absent versus foreign scoped records share 404. These statuses do not leak a row's
existence. Recovery endpoint enablement is distinct from admission enablement: GET works
while writes are paused and cannot change policy. No network/security setting was modified.

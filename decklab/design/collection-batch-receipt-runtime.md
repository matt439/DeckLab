# Receipt-only runtime candidate, isolated and unregistered

Registration/privacy questions were technical risk decisions, not choices the owner
explicitly reserved. This candidate resolves output minimization and authentication in
code without choosing live activation: normal startup still registers neither GET nor POST.
Only the disposable signed-token HTTP fixture injects GET into normal feature dispatch.

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
server rollback result. No runtime toggles, deployment or user-facing installation were added.
Next review can authorize a genuine supported GET registration boundary and any explicit
configuration required, separately from writable batch UI. Until then normal requests remain
unregistered. Do not publish another helper-only PR solely on the basis of this proof.

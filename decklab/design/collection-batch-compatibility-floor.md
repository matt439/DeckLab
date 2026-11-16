# Batch compatibility floor: default-off release candidate

This isolated change makes the existing dormant batch core a candidate **minimum compatible
runtime**, not a released saved-pile feature. It adds no migration, install command, HTTP
registration, browser assets, feature switch or background activation. Ordinary databases do
not acquire a policy table. Existing batch callers with no table and no offer behave as before.

If a future owner-installed `collection_batch_admission` table exists, batch mutations require
its enabled exact contract/epoch. Runtime roles only read policy; callers cannot enable it.
A reviewed intent binds the epoch, so a pending old token cannot be relabelled with a fresh offer.
The existing inventory advisory lock serializes review/completion against owner pause. Pause
must hold that same lock and increment epoch, in its own transaction. No owner transition tool
is included; application calls are not authorization to perform owner DDL or update policy.

Paused mode preserves owned reads, exact already-created UUID/intent reads, and identical
committed-receipt retries. It refuses pending batch mutations before inventory/import/audit
side effects. Receipts remain in place; no drop, prune, restore or destructive downgrade occurs.
Ordinary manual and CSV operations do not participate in this private batch admission contract
and remain unchanged. This does not deduplicate a physical pile entered through another route.

## Evidence and supported boundary

The existing dedicated runner already executes on isolated PostgreSQL in CI. It now adds a
PG-only module, not a browser dependency. Existing absent-policy participant/inventory/release/
HTTP cases remain. Added cases prove paused operations, baseline-to-paused receipt preservation,
foreign-owner refusal, exact original-create read retry, ordinary add/import, malformed offers,
old-token refusal, receipt-failure rollback, role restrictions and both actual lock-wait orders.
The candidate schema exists **only as test fixture SQL** inside that module.

This is a runtime compatibility building block, not certification of all prior binaries.
Pre-floor main does not obey the gate; DatabaseNewer is an informational status, not a read-only
fence. A future rollout must establish its minimum compatible rollback build and stop incompatible
processes. Dropping policy to permit older binaries is not a rollback procedure. A future rollback
uses this compatible runtime paused, retains schema/data/receipts, and still needs full supported
server/version and restore qualification. Routes remain unregistered, so this PR alone provides
no user-facing receipt recovery endpoint.

## Subsequent separately reviewed work

Owner transition tooling and upgrade/rollback policy; additive paused migration and restore/
export/removal qualification; authenticated route/client capability contract; actual app signed
browser/physical-device acceptance; then explicit owner activation. None is authorized or
performed by installing this source change. No production schema or startup behavior is enabled.

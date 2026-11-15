# Dormant collection batch backend: release candidate

## Scope and non-goals

This is a file-level extraction of the reviewed experimental backend onto main after
scanner overflow PR #122 (626f041). It is not a replay of the whole experimental stack.
There is no numbered migration, startup switch, route registration, browser asset,
scanner/manual-picker integration, onboarding change, or end-user save/resume feature.
The candidate SQL remains under design/ and only the disposable proof applies it.

Included: cursor transaction participant and immutable completion receipts; optional
bounded v3 evidence; existing collection metadata merge semantics; internal audited
PgInventory operation; unregistered owner/space-authorized HTTP adapter; private
scratch export/removal fingerprint and journal handling; matching pure and real-PG
fixtures; and a dedicated required CI proof in the existing tests aggregate.

Excluded: onboarding f079443, pure proposal oracle, scanner bridge, both experimental
browser shells and their tests, browser/Playwright CI, and already-merged overflow code.
Onboarding is an independent future UI patch, not a dependency of this backend.

## Runtime consequences while dormant

- PgInventory.apply imports/type-checks the new internal operation. Ordinary operations
  still run their existing operation body. No new HTTP path can construct this type.
- Member export/removal checks for the optional collection_batch table. Without it,
  there are no scratch records to export/fingerprint/remove; existing behavior remains.
- If the candidate table exists in a disposable fixture, private drafts participate in
  removal fingerprints and deletion, but never appear in delivered export artifacts.
- No live schema is created by importing any new module or starting the normal server.

## CI and release gates

The new 15-minute collection-batch-proof job installs PostgreSQL 18 binaries through
the existing PGDG mechanism, initializes a new loopback-only temporary cluster with
synthetic identities, and stops it in finally. It never reads application config or
inherits PG connection overrides. It is required by the existing tests aggregate,
with the same documentation-only skip rule. There is no browser dependency in this PR.

Local proof is not hosted Linux acceptance. Publish only after independent scope review;
then require green checks on the exact current PR head before merge. Schema promotion,
route enablement, browser recovery/cancellation/identity wiring and native device QA
remain separate gates. This candidate alone cannot provide resumable onboarding.

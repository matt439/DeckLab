# Owner admission transition candidate

This opt-in module is not registered in normal startup or `decklab.db` command discovery.
It does not install policy/batch tables, add numbered migrations, register HTTP or enable UI.
Only the dedicated test runner executes it here, against newly created disposable PostgreSQL.

`python -m decklab.db.collection_batch_transition` requires explicit `--dbname`, `--contract`,
`--epoch`, `--target enabled|paused`; `--recover` only observes under the inventory lock.
These arguments describe immutable intent, not permission to act on a real installation.
No command in this change has been run against configured/live data.

Implementation requires actual current SQL role decklab_owner and ownership of both tables,
existing compatible policy, a bounded inventory lock wait and a caller-owned transaction.
Epoch advances once; same intent at expected+1 returns target_confirmed with no mutation.
Anything later conflicts. No-op transitions refuse. Committed output appears only after the
connection context commits. Unknown exceptions say unconfirmed and advise identical-intent
recovery, never silently refresh epoch. Recovery waits behind transactions already holding
inventory lock, but an unchanged observation does not exclude a delayed request arriving later.
All retries remain immutable, so that delayed request and retry cannot advance twice.

Confirmation is of state, not attribution to a particular request/operator. There is no new
transition journal or operator identity storage. If durable attribution is required, agree a
separate schema/audit design before promotion. Existing logs are not claimed as an audit trail.

This command is not a schema verifier, migration installer, inventory freeze or process
registry. Owner table/policy checks do not prove every running binary supports the floor.
Installation/rollback qualification still must pin supported builds, exclude old writers,
and validate schema/export/removal/restore. Ordinary CSV/manual writes remain independent.
No old pre-floor binary becomes safe because DatabaseNewer is displayed. Preserve policy,
drafts and receipts on rollback; do not remove tables or restore pre-receipt data to unpause.

Review scope: owner privilege boundary; epoch and same-intent semantics; bounded lock order;
commit-unknown output; receipt preservation; no auto-install/default activation. All shipped
runtime use and operator qualification remain pending independent review and owner approval.

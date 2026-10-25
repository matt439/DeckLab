-- Phase 5: the nightly check's own log. `python -m decklab.db check` (decklab/db/check.py, also
-- a step of the nightly task) checks the database's data each night: the rule checks (accessories,
-- every space's token cards, the orders and the queue, the deck tables), the decks' invariants and
-- a files-against-database round trip of the export. It records each run in ops.backup_run beside
-- the backups (kind 'check'; detail: the revisions it checked and each sub-check's result, as
-- JSON). Operational, so not audited. Runs as decklab_owner, in one transaction.

alter table ops.backup_run drop constraint backup_run_kind_check;
alter table ops.backup_run add constraint backup_run_kind_check
    check (kind in ('dump', 'export', 'restore_check', 'gate', 'check'));

-- A dump's content digests (backup.digest_rows: {schema.table: md5}), read in the dump's snapshot
-- beside its row counts. A column of their own, not part of detail, so detail stays "rows: " and
-- the counts' JSON alone: the pre-phase-5 code (a rollback's) reads the counts with json.loads of
-- everything after "rows: ", and ignores this column.
alter table ops.backup_run add column digests jsonb;

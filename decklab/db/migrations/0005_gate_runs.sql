-- Phase 3: the inventory gate's own log. `python -m decklab.db gate-inventory --live` compares
-- the database's inventory with what today's file readers say, and records each run in
-- ops.backup_run beside the backups (kind 'gate'; detail: the revision and import time it
-- checked, as JSON). `python -m decklab.db inventory backend db` switches Deck Lab to the
-- database only after a recent run passed on that very revision. Operational, so not audited.
-- Runs as decklab_owner, in one transaction.

alter table ops.backup_run drop constraint backup_run_kind_check;
alter table ops.backup_run add constraint backup_run_kind_check
    check (kind in ('dump', 'export', 'restore_check', 'gate'));

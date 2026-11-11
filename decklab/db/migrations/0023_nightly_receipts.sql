-- A whole-nightly operational receipt lets unmanaged schedulers prove a recent
-- completed run, without treating individual backup/check steps as a scheduler.
alter table ops.backup_run drop constraint backup_run_kind_check;
alter table ops.backup_run add constraint backup_run_kind_check
    check (kind in ('dump', 'export', 'restore_check', 'gate', 'check', 'nightly'));

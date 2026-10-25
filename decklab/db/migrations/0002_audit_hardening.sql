-- Tightening 0001's audit trail (a review of phase 1). Runs as decklab_owner, in one transaction.

-- audit.log_row() runs as the owner (SECURITY DEFINER). Without pg_temp named in its
-- search_path, PostgreSQL looks in the session's temporary schema FIRST for types and tables,
-- so a role that can make temporary objects could slip in its own `jsonb` (a domain whose
-- check calls its own function) and have it run with the owner's rights. Naming pg_temp last
-- closes that; the body already names audit.row_change in full.
alter function audit.log_row() set search_path = pg_catalog, pg_temp;

-- Nobody but the owner needs temporary objects here, so PUBLIC loses them as well.
do $$
begin
    execute format('revoke temporary on database %I from public', current_database());
end
$$;

-- The app says who, from where, what and why; it can't choose a change set's time (at keeps
-- its default, now()), so the trail's times are the server's.
revoke insert on audit.change_set from decklab_app;
grant insert (actor, source, message, reason) on audit.change_set to decklab_app;

-- The audit trigger is per row, and TRUNCATE fires no row triggers, so it would empty an
-- audited table without a trace. Refuse it outright (the app has no TRUNCATE anyway; this
-- covers the owner and psql).
create function audit.refuse_truncate() returns trigger
language plpgsql
set search_path = pg_catalog, pg_temp
as $$
begin
    raise exception 'truncate isn''t audited: delete the rows inside decklab.db.conn.change()';
end
$$;
revoke all on function audit.refuse_truncate() from public;

create trigger audit_no_truncate before truncate on space
    for each statement execute function audit.refuse_truncate();
create trigger audit_no_truncate before truncate on profile
    for each statement execute function audit.refuse_truncate();
create trigger audit_no_truncate before truncate on profile_email
    for each statement execute function audit.refuse_truncate();

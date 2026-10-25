-- Phase 1, the foundation: who's who (space, profile, profile_email), the audit trail every
-- write goes through, the backups' log, and the roles' privileges. Runs as decklab_owner,
-- in one transaction (migrate.py), after migrate.py has made public.schema_migration.

create schema audit;
create schema ops;

-- Nobody but the owner makes objects in public; only the three roles may connect.
revoke create on schema public from public;
do $$
begin
    execute format('revoke connect on database %I from public', current_database());
    execute format('grant connect on database %I to decklab_owner, decklab_app, decklab_ro',
                   current_database());
end
$$;

-- Identity, synced from config.json's profiles (profiles_sync.py).
create table space (
    id text primary key
);

create table profile (
    id text primary key,
    name text not null,
    role text not null check (role in ('admin', 'member')),
    space_id text not null references space,
    plays_as text null check (plays_as in ('user', 'wife', 'either')),
    position int not null
);

-- Two profiles may list the same address (profiles.for_email then picks neither), so the
-- address isn't unique on its own.
create table profile_email (
    profile_id text not null references profile on delete cascade,
    email text not null,
    primary key (profile_id, email)
);
create index profile_email_email on profile_email (email);

-- The audit trail: one change_set per saved change (who, from where, what, why), and one
-- row_change per row it touched, with the row before and after.
create table audit.change_set (
    id bigint generated always as identity primary key,
    at timestamptz not null default now(),
    actor text not null,
    source text not null,
    message text not null check (btrim(message) <> ''),
    reason text
);

create table audit.row_change (
    id bigint generated always as identity primary key,
    change_set_id bigint not null references audit.change_set,
    table_name text not null,
    op text not null check (op in ('INSERT', 'UPDATE', 'DELETE')),
    row_key jsonb,
    before jsonb,
    after jsonb
);
create index row_change_change_set on audit.row_change (change_set_id);
create index row_change_table on audit.row_change (table_name);

-- Every audited write needs a change set (conn.change() sets decklab.change_set for its
-- transaction); a plain psql write is refused, so it has to say who and why. An empty
-- setting counts as missing: once set in a session, current_setting returns '' rather than
-- NULL after the transaction ends. The trigger's arguments are the table's primary-key
-- columns, which make row_key. SECURITY DEFINER: only this function writes row_change.
create function audit.log_row() returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public, audit
as $$
declare
    setting text := nullif(current_setting('decklab.change_set', true), '');
    rec jsonb;
    key jsonb := '{}'::jsonb;
    col text;
begin
    if setting is null then
        raise exception 'every write needs a change set: use decklab.db.conn.change()';
    end if;
    if TG_OP = 'DELETE' then
        rec := to_jsonb(OLD);
    else
        rec := to_jsonb(NEW);
    end if;
    foreach col in array TG_ARGV loop
        key := key || jsonb_build_object(col, rec -> col);
    end loop;
    insert into audit.row_change (change_set_id, table_name, op, row_key, before, after)
    values (setting::bigint, TG_TABLE_NAME, TG_OP, key,
            case when TG_OP <> 'INSERT' then to_jsonb(OLD) end,
            case when TG_OP <> 'DELETE' then to_jsonb(NEW) end);
    return null;
end
$$;
revoke all on function audit.log_row() from public;

create trigger audit_row after insert or update or delete on space
    for each row execute function audit.log_row('id');
create trigger audit_row after insert or update or delete on profile
    for each row execute function audit.log_row('id');
create trigger audit_row after insert or update or delete on profile_email
    for each row execute function audit.log_row('profile_id', 'email');

-- The backups' own log (backup.py, export.py): operational, so not audited.
create table ops.backup_run (
    id bigint generated always as identity primary key,
    kind text not null check (kind in ('dump', 'export', 'restore_check')),
    started_at timestamptz not null,
    finished_at timestamptz,
    ok boolean not null default false,
    path text,
    bytes bigint,
    detail text
);

-- Privileges. The app reads and writes public's tables (but never schema_migration), adds
-- change sets and reads the audit trail; ro reads everything. Default privileges give later
-- migrations' tables the same.
grant usage on schema public, audit to decklab_app;
grant usage on schema ops to decklab_app;
grant usage on schema public, audit, ops to decklab_ro;

grant select, insert, update, delete on space, profile, profile_email to decklab_app;
grant select on schema_migration to decklab_app;
grant insert, select on audit.change_set to decklab_app;
grant select on audit.row_change to decklab_app;
grant select on ops.backup_run to decklab_app;

grant select on all tables in schema public, audit, ops to decklab_ro;

alter default privileges for role decklab_owner in schema public
    grant select, insert, update, delete on tables to decklab_app;
alter default privileges for role decklab_owner in schema public
    grant usage, select on sequences to decklab_app;
alter default privileges for role decklab_owner in schema audit
    grant select on tables to decklab_app;
alter default privileges for role decklab_owner in schema ops
    grant select on tables to decklab_app;
alter default privileges for role decklab_owner in schema public, audit, ops
    grant select on tables to decklab_ro;

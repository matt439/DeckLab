-- Public switches are opt-in: a row means Public, and no row means Private.
-- No foreign keys: configuration sync may remove a profile while its historical
-- actor and audit facts must survive (as for migration 0003's state tables).
-- No seed data: installing this migration makes nothing public.
create table visibility (
    owner text not null check (owner ~ '^[a-z0-9_-]{1,64}$'),
    thing text not null check (thing in ('collection', 'decks', 'games', 'accessories')),
    set_by text null,
    set_by_name text not null,
    since timestamptz not null default now(),
    primary key (owner, thing)
);

create trigger audit_row after insert or update or delete on visibility
    for each row execute function audit.log_row('owner', 'thing');
create trigger audit_no_truncate before truncate on visibility
    for each statement execute function audit.refuse_truncate();

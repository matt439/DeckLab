-- A departed member cannot be recreated by stale config or an already queued save.
-- Minimal operational identity only: no names, addresses or member card contents.
-- Written by owner-role member removal in its existing audited transaction.
create table space_departure (
    space_id text primary key check (space_id <> 'home'),
    operation uuid not null unique,
    change_set_id bigint not null references audit.change_set
);

create trigger audit_row after insert or update or delete on space_departure
    for each row execute function audit.log_row('space_id');
create trigger audit_no_truncate before truncate on space_departure
    for each statement execute function audit.refuse_truncate();

revoke insert, update, delete on space_departure from decklab_app;
grant select on space_departure to decklab_app, decklab_ro;

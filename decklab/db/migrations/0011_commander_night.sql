-- The household's current Commander-night notes, never seeded from a venue listing.
-- A cleared note keeps its row and revision, so an older editor cannot overwrite a
-- clear-and-recreate cycle even when the recreated notes happen to be identical.
create table commander_night (
    id boolean primary key default true check (id),
    revision bigint not null check (revision >= 1),
    content jsonb null check (content is null or jsonb_typeof(content) = 'object')
);

create trigger audit_row after insert or update or delete on commander_night
    for each row execute function audit.log_row('id');
create trigger audit_no_truncate before truncate on commander_night
    for each statement execute function audit.refuse_truncate();

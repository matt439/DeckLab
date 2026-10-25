-- Phase 2: the personal state that leaves the files (wishlists, profile settings, the
-- simulations mode and play records), and where a web change came from. Runs as
-- decklab_owner, in one transaction.
--
-- 0001's default privileges already give these tables to the app (select, insert, update,
-- delete) and to ro (select); none of them has a sequence. Nothing here refers to profile:
-- profiles_sync removes profiles no longer in config.json, and a foreign key would either
-- delete a person's data with them (cascade) or stop the sync (restrict). A profile id is
-- checked by its form only, as the file names were, and orphans are kept, as files were.

-- "From where": the listener a web change came through (the home network or the tunnel);
-- null for the command line and everything else.
alter table audit.change_set add column via text null check (via in ('home', 'tunnel'));
grant insert (via) on audit.change_set to decklab_app;

-- A wishlist, one row per card, in the order the page shows them. A card name is the list's
-- identity: Python keeps names unique by casefold (stricter than lower()), so the index below
-- never refuses what Python allows; it's the backstop.
create table wishlist_entry (
    profile_id text not null check (profile_id ~ '^[A-Za-z0-9_-]{1,64}$'),
    position int not null check (position >= 0),
    name text not null check (name <> '' and name = btrim(name) and length(name) <= 150),
    set_code text null check (set_code ~ '^[a-z0-9]{2,8}$'),
    collector_number text null check (length(collector_number) between 1 and 16),
    notes text not null default '' check (length(notes) <= 2000),
    source text not null default '' check (length(source) <= 300),
    primary key (profile_id, position),
    check ((set_code is null) = (collector_number is null))
);
create unique index wishlist_entry_name on wishlist_entry (profile_id, lower(name));

-- A profile's saved settings, as text (api/settings.py checks the values and fills in defaults).
create table profile_setting (
    profile_id text not null check (profile_id ~ '^[A-Za-z0-9_-]{1,64}$'),
    key text not null check (key ~ '^[a-z_]{1,40}$'),
    value text not null check (length(value) <= 200),
    primary key (profile_id, key)
);

-- Who may start Forge runs: one row at most, none until someone first sets it (the default
-- applies). set_by is the profile id when it's known (an import from the old file knows only
-- the name); set_by_name is the name shown, as it was at the time.
create table simulation_mode (
    id boolean primary key default true check (id),
    mode text not null check (mode in ('admins', 'everyone', 'paused')),
    set_by text null,
    set_by_name text not null,
    since timestamptz not null default now()
);

-- Human games and sideboard plans, one row per record. created_on and updated_on keep the
-- exact text Deck Lab wrote (a record's hash covers it), and content holds the kind's own
-- fields as they were in the file; the hash is always worked out in Python from the rebuilt
-- record, never from jsonb text. deck_ids are the decks the record involves (a game's two
-- sides, a plan's deck and opponent), for finding a deck's records.
create table play_record (
    kind text not null check (kind in ('games', 'sideboards')),
    id text not null check (id ~ '^[a-f0-9]{32}$'),
    revision int not null check (revision >= 1),
    created_on text not null check (created_on::timestamptz is not null),
    updated_on text not null check (updated_on::timestamptz is not null),
    updated_by text not null check (length(updated_by) between 1 and 80),
    deck_ids text[] not null,
    content jsonb not null check (jsonb_typeof(content) = 'object'),
    primary key (kind, id)
);
create index play_record_decks on play_record using gin (deck_ids);

-- Audited like 0001's tables: every write needs a change set, and truncate is refused.
create trigger audit_row after insert or update or delete on wishlist_entry
    for each row execute function audit.log_row('profile_id', 'position');
create trigger audit_row after insert or update or delete on profile_setting
    for each row execute function audit.log_row('profile_id', 'key');
create trigger audit_row after insert or update or delete on simulation_mode
    for each row execute function audit.log_row('id');
create trigger audit_row after insert or update or delete on play_record
    for each row execute function audit.log_row('kind', 'id');

create trigger audit_no_truncate before truncate on wishlist_entry
    for each statement execute function audit.refuse_truncate();
create trigger audit_no_truncate before truncate on profile_setting
    for each statement execute function audit.refuse_truncate();
create trigger audit_no_truncate before truncate on simulation_mode
    for each statement execute function audit.refuse_truncate();
create trigger audit_no_truncate before truncate on play_record
    for each statement execute function audit.refuse_truncate();

-- A new deck's editor draft kept for later (E2-S16): one profile's unsaved new deck in one space,
-- before it has a deck id, so the same profile can pick it up on another device. source is '' for a
-- deck started from nothing, else the id of the deck it's a copy of (no reference: that deck may be
-- renamed or deleted since, and the draft holds its own lists). Private to that profile, as 0018's
-- deck_draft: the API (lib/api/deck_drafts.py) answers only the draft's own profile and asks again on
-- every read and write that it may add decks to the space. Scratch work: not audited (no trigger, no
-- change set), not in the general export; a member's removal fingerprints, locks and deletes its rows
-- (space_export, space_apply). A discard keeps a tombstone with its revision, as 0018's does, and the
-- revision only grows. Deleting the profile or the space deletes its drafts.
-- As for deck_draft, 0001's default privileges give decklab_app ordinary
-- SELECT/INSERT/UPDATE/DELETE and decklab_ro SELECT, without TRUNCATE.
create table public.new_deck_draft (
    profile_id text not null references profile (id) on delete cascade,
    space_id text not null references space (id) on delete cascade,
    source text not null default '' check (length(source) <= 200),
    revision bigint not null check (revision >= 1),
    saved_at timestamptz not null,
    device text not null default '' check (length(device) <= 60),
    content jsonb null check (content is null or jsonb_typeof(content) = 'object'),
    primary key (profile_id, space_id, source)
);

create index new_deck_draft_space on public.new_deck_draft (space_id);

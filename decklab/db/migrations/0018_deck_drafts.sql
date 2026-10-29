-- Editor drafts kept for later (E2-S16): one profile's unsaved edit of one list of one deck,
-- so the same profile can pick it up on another device. Private to that profile: the API
-- (lib/api/deck_drafts.py) answers only the draft's own profile and rechecks the deck's
-- privacy on every read and write. A draft is scratch work, like the browser's own drafts:
-- not audited (no trigger, no change set, so its lists never reach Activity), not in the general
-- export. A member's removal fingerprints, locks and deletes its rows (space_export, space_apply).
-- A discarded or saved draft keeps its row and revision with content null (a tombstone), so an
-- older device's revision can't overwrite a draft saved again since; the revision only grows.
-- Deleting the profile or the deck deletes its drafts, and a deck rename carries them along.
-- As for commander_night, 0001's default privileges give decklab_app ordinary
-- SELECT/INSERT/UPDATE/DELETE and decklab_ro SELECT, without TRUNCATE.
create table public.deck_draft (
    profile_id text not null references profile (id) on delete cascade,
    deck_id text not null references deck (id) on update cascade on delete cascade,
    version text not null check (version in ('target', 'owned')),
    revision bigint not null check (revision >= 1),
    saved_at timestamptz not null,
    device text not null default '' check (length(device) <= 60),
    content jsonb null check (content is null or jsonb_typeof(content) = 'object'),
    primary key (profile_id, deck_id, version)
);

create index deck_draft_deck on public.deck_draft (deck_id);

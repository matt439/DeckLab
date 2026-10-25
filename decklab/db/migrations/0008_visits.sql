-- Who visits Deck Lab and which pages they open (lib/visits.py, the owner's request of
-- 2026-10-13): an admin's informal user-testing feedback, on the Settings page's Visits part and
-- `python -m decklab.db visits`. Operational like ops.backup_run, so not audited (no trigger, no
-- change set), not exported, and left out of the dumps' content digests (backup.DIGEST_SCHEMAS);
-- the nightly task deletes days older than about a year (decklab/db/visits.py, KEEP_DAYS).
-- Runs as decklab_owner, in one transaction.

-- One row per profile, day (the PC's local date) and channel: 'home' (the home network, the
-- profile the page's chooser names) or 'remote' (through the tunnel, the Cloudflare Access login).
-- requests: the API requests that profile made that day.
create table ops.visit_day (
    profile_id text not null check (profile_id ~ '^[a-z0-9]+(-[a-z0-9]+)*$' and length(profile_id) <= 40),
    day date not null,
    channel text not null check (channel in ('home', 'remote')),
    first_at timestamptz not null,
    last_at timestamptz not null,
    requests int not null default 0 check (requests >= 0),
    primary key (profile_id, day, channel)
);

-- The pages opened that day (the page's beacon, POST /api/visit): the route's path ("library",
-- "deck", ...) and, for a deck's pages, its id ('' for none). Nothing else of the address is kept.
create table ops.visit_page (
    profile_id text not null,
    day date not null,
    channel text not null,
    route text not null check (route ~ '^[a-z]{1,20}$'),
    deck_id text not null default '' check (length(deck_id) <= 200),
    opens int not null check (opens > 0),
    last_at timestamptz not null,
    primary key (profile_id, day, channel, route, deck_id),
    foreign key (profile_id, day, channel) references ops.visit_day on delete cascade
);

-- The server adds and updates them as decklab_app (ops is otherwise read-only to it); only the
-- owner deletes (the nightly prune).
grant select, insert, update on ops.visit_day, ops.visit_page to decklab_app;

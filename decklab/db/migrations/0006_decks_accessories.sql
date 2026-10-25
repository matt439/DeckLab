-- Phase 4: the decks and the accessories leave the files (decklab/PLAN.md, "Moving storage to a
-- database"; the phase 4 design, D3 as amended by R1-R6 and the design review). Every space's
-- deck texts with their history, accessories.csv's rows and its pictures. Runs as decklab_owner,
-- in one transaction.
--
-- decklab/lib/inventory/pg.py (with pg_decks.py) reads these into the same snapshot the files
-- backend makes and writes an operation's changes back under the advisory lock 'inventory'. The
-- decks part has its own revision (decks_revision), so a deck save never moves the inventory's
-- (which receipt previews and imports fingerprint). Whole texts and picture bytes are kept apart
-- from the audited rows, as collection_import_content is, so the audit trail stays small: the
-- small audited rows (deck, accessory) are what Activity shows. As in 0003 and 0004, nothing
-- refers to space.

-- The decks part's revision: one row, bumped by every write that changes a deck, accessories.csv
-- or a picture. No row means the decks were never imported: until then the backend carries
-- the deck parts as the files hold them, and refuses to save them. Operational, so not audited.
create table decks_revision (
    id boolean primary key default true check (id),
    revision bigint not null check (revision >= 1),
    imported_at timestamptz not null default now()
);

-- A deck (a deck file's identity and what Activity says about it). id is the library's
-- ("<kind>/<slug>" at home, "<space>/<kind>/<slug>" in a person's space). title, status and
-- played_by are read from the text when it's written, for Activity and SQL; '' when the text
-- doesn't say. The Sleeves and Deck box values are never here (accessories are private, from
-- admins too, and this row is audited): kit_version counts their changes instead, so Activity
-- can keep a kit change's words for whoever made it. revision is the number of the text now
-- in deck_text (deck_revision's latest for this id).
create table deck (
    id text primary key,
    space_id text not null check (space_id ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    kind text not null check (kind in ('casual', 'commander')),
    slug text not null check (slug ~ '^[^/\\.][^/\\]*$' and length(slug) <= 200),
    title text not null default '',
    status text not null default '',
    played_by text not null default '',
    kit_version int not null default 0 check (kit_version >= 0),
    revision int not null check (revision >= 1),
    updated_at timestamptz not null default now(),
    check (id = case when space_id = 'home' then kind || '/' || slug else space_id || '/' || kind || '/' || slug end)
);
-- One deck per name in a space and kind, whatever the case (a case-insensitive file system holds
-- one file for both; the deck.create operation also refuses a slug the other kind has).
create unique index deck_space_name on deck (space_id, lower(kind || '/' || slug));

-- The deck's text now, LF line endings (git's blobs are LF; the command line's push turns CRLF
-- into LF). Unaudited: deck_revision keeps every text, deck its audited summary.
create table deck_text (
    deck_id text primary key references deck on delete cascade,
    text text not null check (position(E'\r' in text) = 0)
);

-- Every saved text of every deck, numbered per deck from 1 (a deck made again after it was
-- deleted carries on after its 'D'), never changed afterwards: op 'A' (made), 'M' (changed),
-- 'D' (deleted: no text). A deleted deck keeps its revisions with no deck row. Revisions written
-- by Deck Lab name their change set (whose at, actor and message they repeat); the ones the
-- import brought from git have none (change_set_id NULL) but git's commit, time, author and
-- message. kit is true for a revision that changed the deck's Sleeves or Deck box (or deleted a
-- deck holding them, or made one with them): its message names accessories, which are private
-- from admins too, so the History and a save's "who changed it" show it only to its actor.
-- Unaudited (the texts would swell the trail); the app may add rows, never change or delete them.
create table deck_revision (
    deck_id text not null,
    revision int not null check (revision >= 1),
    change_set_id bigint null references audit.change_set,
    at timestamptz not null,
    actor text not null check (actor <> ''),
    message text not null check (btrim(message) <> ''),
    op text not null check (op in ('A', 'M', 'D')),
    kit boolean not null default false,
    git_commit text null check (git_commit ~ '^[0-9a-f]{40,64}$'),
    text text null check (position(E'\r' in text) = 0),
    primary key (deck_id, revision),
    unique (deck_id, git_commit),
    check ((op = 'D') = (text is null))
);
create index deck_revision_change_set on deck_revision (change_set_id) where change_set_id is not null;

-- Each deck's decklist lines, for SQL only ("which decks use X": python -m decklab.db sql).
-- Derived from the text by decks.parse_deck in the same transaction as every write of it, by
-- the one writer every deck write goes through (pg_decks.put_decks); Python never reads them.
-- version 'target' is the decklist, 'owned' the substitute (owned-only) list; position is the
-- line's place in its section. A text that can't be parsed has none. Unaudited.
create table deck_line (
    deck_id text not null references deck on delete cascade,
    version text not null check (version in ('target', 'owned')),
    section text not null check (section in ('Commander', 'Companion', 'Deck', 'Sideboard')),
    position int not null check (position >= 0),
    quantity int not null,
    name text not null,
    set_code text not null default '',
    collector_number text not null default '',
    finish text not null default 'nonfoil',
    primary key (deck_id, version, section, position)
);
create index deck_line_name on deck_line (lower(name));

-- accessories.csv's rows, every value as written ('' for blank, or for a column an older header
-- lacked). No position: the file's order is always by kind, then id (rules.accessory_sort_key).
create table accessory (
    id text primary key,
    kind text not null default '',
    owner text not null default '',
    brand text not null default '',
    name text not null default '',
    colour text not null default '',
    quantity text not null default '',
    capacity text not null default '',
    image text not null default '',
    crop text not null default '',
    link text not null default '',
    image_source text not null default '',
    notes text not null default ''
);

-- The accessories' pictures (magic/accessories/images/<file name>), byte for byte (never
-- line-ending normalised). Unaudited: the accessory row naming it is audited.
create table accessory_image (
    file_name text primary key check (file_name ~ '^[^/\\.][^/\\]{0,254}$'),
    content bytea not null,
    size bigint not null check (size = octet_length(content)),
    sha256 text not null check (sha256 = encode(sha256(content), 'hex'))
);

-- Audited like 0004's tables (the trigger's arguments are the primary key); truncate is refused
-- on the audited tables and on the history.
create trigger audit_row after insert or update or delete on deck
    for each row execute function audit.log_row('id');
create trigger audit_row after insert or update or delete on accessory
    for each row execute function audit.log_row('id');

create trigger audit_no_truncate before truncate on deck
    for each statement execute function audit.refuse_truncate();
create trigger audit_no_truncate before truncate on accessory
    for each statement execute function audit.refuse_truncate();
create trigger audit_no_truncate before truncate on deck_revision
    for each statement execute function audit.refuse_truncate();

-- The default privileges give the app every table; said again here so the grants are plain to
-- see, and deck_revision taken back to adding and reading (the history is append-only).
grant select, insert, update, delete on decks_revision, deck, deck_text, deck_line, accessory, accessory_image
    to decklab_app;
revoke update, delete on deck_revision from decklab_app;
grant select, insert on deck_revision to decklab_app;
grant select on decks_revision, deck, deck_text, deck_revision, deck_line, accessory, accessory_image
    to decklab_ro;

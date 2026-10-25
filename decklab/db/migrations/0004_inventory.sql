-- Phase 3: the inventory leaves the files (decklab/PLAN.md, "Moving storage to a database";
-- the phase 3 design and its amendments). The collections and token cards of every space,
-- their raw imports, the products and their status rows, the order records with their
-- payloads, and the watchlist. Runs as decklab_owner, in one transaction.
--
-- decklab/lib/inventory/pg.py reads every table here into the same snapshot the files backend
-- makes (lib/inventory/model.py) and writes an operation's changes back as a row diff, under
-- the advisory lock 'inventory'. Text keeps what the files held: a blank value is '' (never
-- NULL) except where a column says NULL means something. Rows are put in order in Python, never
-- by SQL collation. The checks are no stricter than the rules today's writers keep.
--
-- 0001's default privileges already give these tables to the app (select, insert, update,
-- delete; usage on the identity sequences) and to ro (select). As in 0003, nothing refers to
-- space: a space id is checked by its form, and profiles_sync can drop a space without
-- touching (or being stopped by) its cards, which stay as orphans an admin can see.

-- The inventory's revision: one row, bumped by every inventory write, which the database
-- backend caches its snapshot by. There's no row until the import (python -m decklab.db
-- import-files) puts the files in; until then the backend refuses, so an empty inventory is
-- never mistaken for one with no cards. imported_at tells a fresh import from an older one
-- with the same revision number. Operational, so not audited.
create table inventory_revision (
    id boolean primary key default true check (id),
    revision bigint not null check (revision >= 1),
    imported_at timestamptz not null default now()
);

-- A space's collection (collection.csv's rows), one row per printing and finish. The files'
-- order (merge_cards.sort_key) is worked out in Python, so the rows have no position.
create table collection_card (
    space_id text not null check (space_id ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    set_code text not null check (set_code ~ '^[a-z0-9]{2,8}$'),
    collector_number text not null check (collector_number <> '' and collector_number !~ '\s'),
    finish text not null check (finish in ('nonfoil', 'foil', 'etched')),
    name text not null check (name <> '' and name = btrim(name)),
    quantity int not null check (quantity >= 1),
    condition text not null default '',
    language text not null default '',
    notes text not null default '',
    primary key (space_id, set_code, collector_number, finish)
);

-- The raw scanner and app exports a space's collection was merged from (its imports/
-- folder): who, which file and when are audited; the file itself is kept apart, in the
-- unaudited collection_import_content, so the audit trail never holds whole files (an export
-- may carry purchase prices, which Deck Lab never shows).
create table collection_import (
    id bigint generated always as identity primary key,
    space_id text not null check (space_id ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    file_name text not null check (file_name ~ '^[^/\\]{1,255}$' and file_name not in ('.', '..')),
    size bigint not null check (size >= 0),
    sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
    imported_at timestamptz not null default now(),
    unique (space_id, file_name)
);

create table collection_import_content (
    import_id bigint primary key references collection_import on delete cascade,
    content bytea not null
);

-- A space's token and reminder cards (tokens.csv's rows). id is the row's identity, kept
-- across edits (two rows may hold exactly the same card); position is its place in the file,
-- in the order rows are kept (rules.TOKEN_SORT, ties as they were).
create table token_card (
    id bigint generated always as identity primary key,
    space_id text not null check (space_id ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    position int not null check (position >= 0),
    front text not null,
    back text not null default '',
    set_code text not null default '',
    front_collector_number text not null default '',
    back_collector_number text not null default '',
    finish text not null default '',
    quantity int not null check (quantity >= 1),
    front_details text not null default '',
    back_details text not null default '',
    notes text not null default ''
);
create index token_card_space on token_card (space_id, position);

-- A product's fixed card list (products/<stem>.csv). columns is the file's header, in order
-- (four header styles exist: deck, section, plain, and the starter collection's
-- in_play_boosters), and each item's cells line up with it. name and format are the display
-- name and deck format (decks.PRODUCT_INFO's); NULL means none, and each reader falls back
-- in its own way. Whether it reads as decks follows from its columns.
create table product (
    stem text primary key check (stem ~ '^[^/\\.][^/\\]*$' and length(stem) <= 200),
    name text null,
    format text null,
    columns text[] not null check (cardinality(columns) >= 1)
);

create table product_item (
    product_stem text not null references product on delete cascade,
    position int not null check (position >= 0),
    cells text[] not null,
    primary key (product_stem, position)
);

-- products/status.csv's rows, in file order. A status row needs no product file and a
-- product file needs no status row (the readers join them and warn), so this refers to
-- nothing; the values are kept as written, and the readers judge them as they do today.
create table product_status (
    file text primary key,
    position int not null check (position >= 0),
    status text not null default '',
    intact text not null default '',
    sleeves text not null default '',
    deck_box text not null default '',
    notes text not null default ''
);

-- An order record (orders/records/<id>.json). Dates are text, YYYY-MM-DD or '' (five real
-- records have no order date). audit_notes is NULL when the record has none.
create table purchase_order (
    id text primary key check (id ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    seller text not null default '',
    ordered_on text not null default '' check (ordered_on = '' or ordered_on ~ '^\d{4}-\d{2}-\d{2}$'),
    sources text[] not null default '{}',
    notes text not null default '',
    audit_notes text null
);

-- One component of an order, in the record's order (position). file_name is its payload's
-- file name (a product's is <stem>.csv); the path a record shows is worked out from kind,
-- status and file_name. A cards or tokens payload's rows are in order_card_item or
-- order_token_item; a product component names its product. No "received means a date"
-- check: three historic product receipts have none. verified_checks is NULL when the record
-- has none.
create table order_component (
    order_id text not null references purchase_order on delete cascade,
    id text not null check (id ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    position int not null check (position >= 0),
    kind text not null check (kind in ('cards', 'tokens', 'product')),
    file_name text not null check (file_name ~ '^[^/\\]{1,255}\.csv$'),
    status text not null check (status in ('pending', 'received', 'cancelled')),
    received_on text not null default '' check (received_on = '' or received_on ~ '^\d{4}-\d{2}-\d{2}$'),
    checks text[] not null default '{}',
    verified_checks text[] null,
    product_stem text null references product deferrable initially deferred,
    primary key (order_id, id),
    unique (order_id, position) deferrable initially deferred,
    check ((kind = 'product') = (product_stem is not null)),
    check (product_stem is null or file_name = product_stem || '.csv')
);
-- A cards or tokens payload's file name is unique within its kind (two kinds may share one:
-- 2026-10-07-mtgmate.csv is both a cards and a tokens payload).
create unique index order_component_file on order_component (kind, file_name) where kind <> 'product';

create table order_card_item (
    order_id text not null,
    component_id text not null,
    position int not null check (position >= 0),
    name text not null,
    set_code text not null,
    collector_number text not null default '',
    finish text not null,
    quantity int not null check (quantity >= 1),
    condition text not null default '',
    language text not null default '',
    notes text not null default '',
    primary key (order_id, component_id, position),
    foreign key (order_id, component_id) references order_component on delete cascade
);

create table order_token_item (
    order_id text not null,
    component_id text not null,
    position int not null check (position >= 0),
    front text not null,
    back text not null default '',
    set_code text not null default '',
    front_collector_number text not null default '',
    back_collector_number text not null default '',
    finish text not null default '',
    quantity int not null check (quantity >= 1),
    front_details text not null default '',
    back_details text not null default '',
    notes text not null default '',
    primary key (order_id, component_id, position),
    foreign key (order_id, component_id) references order_component on delete cascade
);

-- The purchase queue (watchlist.csv's rows), every value as written but the quantity. id is
-- the row's identity, kept across edits; position its place in the file.
create table watchlist_item (
    id bigint generated always as identity primary key,
    position int not null check (position >= 0),
    name text not null,
    set_code text not null default '',
    collector_number text not null default '',
    finish text not null default '',
    quantity int not null check (quantity >= 1),
    for_deck text not null default '',
    printing text not null default '',
    listed_aud text not null default '',
    listed_at text not null default '',
    in_stock text not null default '',
    checked text not null default '',
    notes text not null default '',
    state text not null default '',
    source text not null default ''
);

-- Audited like 0001's and 0003's tables: every write needs a change set, and truncate is
-- refused. The trigger's arguments are each table's primary key.
create trigger audit_row after insert or update or delete on collection_card
    for each row execute function audit.log_row('space_id', 'set_code', 'collector_number', 'finish');
create trigger audit_row after insert or update or delete on collection_import
    for each row execute function audit.log_row('id');
create trigger audit_row after insert or update or delete on token_card
    for each row execute function audit.log_row('id');
create trigger audit_row after insert or update or delete on product
    for each row execute function audit.log_row('stem');
create trigger audit_row after insert or update or delete on product_item
    for each row execute function audit.log_row('product_stem', 'position');
create trigger audit_row after insert or update or delete on product_status
    for each row execute function audit.log_row('file');
create trigger audit_row after insert or update or delete on purchase_order
    for each row execute function audit.log_row('id');
create trigger audit_row after insert or update or delete on order_component
    for each row execute function audit.log_row('order_id', 'id');
create trigger audit_row after insert or update or delete on order_card_item
    for each row execute function audit.log_row('order_id', 'component_id', 'position');
create trigger audit_row after insert or update or delete on order_token_item
    for each row execute function audit.log_row('order_id', 'component_id', 'position');
create trigger audit_row after insert or update or delete on watchlist_item
    for each row execute function audit.log_row('id');

create trigger audit_no_truncate before truncate on collection_card
    for each statement execute function audit.refuse_truncate();
create trigger audit_no_truncate before truncate on collection_import
    for each statement execute function audit.refuse_truncate();
create trigger audit_no_truncate before truncate on token_card
    for each statement execute function audit.refuse_truncate();
create trigger audit_no_truncate before truncate on product
    for each statement execute function audit.refuse_truncate();
create trigger audit_no_truncate before truncate on product_item
    for each statement execute function audit.refuse_truncate();
create trigger audit_no_truncate before truncate on product_status
    for each statement execute function audit.refuse_truncate();
create trigger audit_no_truncate before truncate on purchase_order
    for each statement execute function audit.refuse_truncate();
create trigger audit_no_truncate before truncate on order_component
    for each statement execute function audit.refuse_truncate();
create trigger audit_no_truncate before truncate on order_card_item
    for each statement execute function audit.refuse_truncate();
create trigger audit_no_truncate before truncate on order_token_item
    for each statement execute function audit.refuse_truncate();
create trigger audit_no_truncate before truncate on watchlist_item
    for each statement execute function audit.refuse_truncate();

-- The default privileges cover the app and ro already; said again here so the grants are
-- plain to see (and hold even if the defaults were ever changed).
grant select, insert, update, delete on inventory_revision, collection_card, collection_import,
    collection_import_content, token_card, product, product_item, product_status, purchase_order,
    order_component, order_card_item, order_token_item, watchlist_item to decklab_app;
grant usage, select on all sequences in schema public to decklab_app;
grant select on inventory_revision, collection_card, collection_import, collection_import_content,
    token_card, product, product_item, product_status, purchase_order, order_component,
    order_card_item, order_token_item, watchlist_item to decklab_ro;

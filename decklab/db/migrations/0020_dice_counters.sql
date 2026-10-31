-- A space's owned dice and counters (E7-S24), kept apart from its token cards: one row per kind of
-- item, as dice.csv's columns (lib/inventory/dice_rules.py). item_type is die or counter; a die has
-- a size (d4 to d20, or spindown) and no kind; a counter's kind ('+1/+1', 'poison', ...) is blank
-- for a generic counter that stands for any kind. quantity may be 0, keeping a used-up row.
-- Per space and audited like token_card (rows by id, positions STEP apart within a space); the
-- inventory's revision moves with every change. Until this is applied Deck Lab reads every space
-- as having none and refuses to record one (pg_dice.py). As for token_card, 0001's default
-- privileges give decklab_app ordinary SELECT/INSERT/UPDATE/DELETE (and the identity's sequence)
-- and decklab_ro SELECT, without TRUNCATE.
create table public.dice_counter (
    id bigint generated always as identity primary key,
    space_id text not null check (space_id ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    position int not null check (position >= 0),
    item_type text not null check (item_type in ('die', 'counter')),
    die_size text not null default ''
        check (die_size in ('', 'd4', 'd6', 'd8', 'd10', 'd12', 'd20', 'spindown')),
    counter_kind text not null default ''
        check (char_length(counter_kind) <= 30 and counter_kind = lower(counter_kind)
               and counter_kind !~ '[[:cntrl:]]'),
    design text not null default '' check (char_length(design) <= 60 and design !~ '[[:cntrl:]]'),
    quantity int not null check (quantity between 0 and 9999),
    notes text not null default '' check (char_length(notes) <= 200 and notes !~ '[[:cntrl:]]'),
    check ((item_type = 'die') = (die_size <> '')),
    check (item_type = 'counter' or counter_kind = '')
);
create index dice_counter_space on public.dice_counter (space_id, position);

create trigger audit_row after insert or update or delete on public.dice_counter
    for each row execute function audit.log_row('id');
create trigger audit_no_truncate before truncate on public.dice_counter
    for each statement execute function audit.refuse_truncate();

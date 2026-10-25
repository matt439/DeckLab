-- Deck renames preserve immutable revision rows and every former public ID.
-- No FK to deck: retirement retains the aliases and the readable history.
create table deck_alias (
    alias_id text primary key,
    deck_id text not null,
    check (alias_id <> deck_id),
    check (regexp_replace(alias_id, '/[^/]*$', '') = regexp_replace(deck_id, '/[^/]*$', ''))
);
create unique index deck_alias_name on deck_alias (lower(alias_id));
create index deck_alias_target on deck_alias (deck_id);
create trigger audit_row after insert or update or delete on deck_alias
    for each row execute function audit.log_row('alias_id');
create trigger audit_no_truncate before truncate on deck_alias
    for each statement execute function audit.refuse_truncate();
grant select, insert, update, delete on deck_alias to decklab_app;
grant select on deck_alias to decklab_ro;

-- Packing tasks must not revive when a name is reused or changed back later.
alter table deck add column rename_version int not null default 0 check (rename_version >= 0);

-- One UPDATE of deck's identity retains kit_version and emits no false kit move.
alter table deck_text drop constraint deck_text_deck_id_fkey;
alter table deck_text add foreign key (deck_id) references deck(id) on update cascade on delete cascade;
alter table deck_line drop constraint deck_line_deck_id_fkey;
alter table deck_line add foreign key (deck_id) references deck(id) on update cascade on delete cascade;

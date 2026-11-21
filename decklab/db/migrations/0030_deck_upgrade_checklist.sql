-- One private list per profile and saved deck. Rename carries it along;
-- deleting either owner deletes the list. Working choices never reach Activity.
create table public.deck_upgrade_checklist (
    profile_id text not null references public.profile (id) on delete cascade,
    deck_id text not null references public.deck (id) on update cascade on delete cascade,
    revision bigint not null check (revision between 1 and 9007199254740991),
    title text not null check (length(title) <= 150),
    rows jsonb not null check (jsonb_typeof(rows) = 'array' and jsonb_array_length(rows) <= 200),
    primary key (profile_id, deck_id)
);

create index deck_upgrade_checklist_deck on public.deck_upgrade_checklist (deck_id);

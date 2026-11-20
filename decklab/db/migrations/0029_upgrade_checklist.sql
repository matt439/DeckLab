-- A private working list, independent of decks, collection counts and purchases.
-- As with editor drafts, its working title and card names never enter audit or Activity.
-- Keep the revision after clearing a list so a stale device cannot resurrect its cards.
create table public.upgrade_checklist (
    profile_id text primary key references public.profile (id) on delete cascade,
    revision bigint not null check (revision between 1 and 9007199254740991),
    title text not null check (length(title) <= 150),
    rows jsonb not null check (jsonb_typeof(rows) = 'array' and jsonb_array_length(rows) <= 200)
);

-- Staged schema ONLY. Not installed by migrate/setup/update.
-- Reserve the next migration number only when the inventory adapter, export/removal
-- fingerprint/delete and db_support rollback entries are integrated and tested.
-- Scratch data: exclude from general export; include in owner deletion fingerprint.
create table public.collection_batch (
    profile_id text not null references profile(id) on delete cascade,
    space_id text not null references space(id) on delete cascade,
    batch_id uuid not null,
    initial_digest text not null check (length(initial_digest)=64),
    revision bigint not null default 1 check (revision>0),
    status text not null default 'draft' check (status in ('draft','committed','discarded')),
    content jsonb,
    review jsonb,
    receipt jsonb,
    saved_at timestamptz not null default now(),
    primary key (profile_id,space_id,batch_id),
    check ((status='draft' and content is not null and jsonb_typeof(content)='object' and receipt is null)
        or (status='committed' and content is null and review is not null and receipt is not null
            and jsonb_typeof(receipt)='object')
        or (status='discarded' and content is null and review is null and receipt is null))
);
create unique index collection_batch_one_draft on collection_batch(profile_id,space_id) where status='draft';

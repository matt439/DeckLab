-- A space's storage as a setting (E8-S25): its containers (a storage box, a binder, a shelf), each
-- with a name, a capacity, its sections and an ordering rule, and the container loose cards go to
-- when no location is recorded. One record per space, saved whole with a revision, as the shops'
-- postage is; edited by the space's own people (permissions' storage.edit). The record's full rules
-- are lib/state/space_storage.py's (db check compares every row with its normalized form); this
-- check holds only its outer shape. No row means the space has saved nothing: home then uses its
-- built-in storage box, any other space none. As for shop_postage, 0001's default privileges give
-- decklab_app ordinary SELECT/INSERT/UPDATE/DELETE and decklab_ro SELECT.
create table public.space_storage (
    space_id text primary key references public.space (id),
    revision bigint not null check (revision >= 1),
    content jsonb not null check (
        jsonb_typeof(content) = 'object'
        and content ?& array['v', 'default', 'containers']
        and content - array['v', 'default', 'containers'] = '{}'::jsonb
        and content ->> 'v' = '1'
        and jsonb_typeof(content -> 'default') in ('null', 'string')
        and jsonb_typeof(content -> 'containers') = 'array'
        and jsonb_array_length(content -> 'containers') <= 20
    )
);

create trigger audit_row after insert or update or delete on public.space_storage
    for each row execute function audit.log_row('space_id');
create trigger audit_no_truncate before truncate on public.space_storage
    for each statement execute function audit.refuse_truncate();

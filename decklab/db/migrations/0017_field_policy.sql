-- Revisioned household field choices for exact deck incarnations. Use-rules entries
-- remain in content as tombstones; no current deck or historic epoch is rewritten.
-- As for commander_night, 0001's default privileges give decklab_app ordinary
-- SELECT/INSERT/UPDATE/DELETE and decklab_ro SELECT, without TRUNCATE.
create table public.field_policy (
    format text primary key check (format in ('Constructed', 'Commander')),
    revision bigint not null check (revision >= 1),
    content jsonb not null check (
        jsonb_typeof(content) = 'object'
        and content ?& array['v', 'rules']
        and content - array['v', 'rules'] = '{}'::jsonb
        and jsonb_typeof(content -> 'v') = 'number' and content ->> 'v' = '1'
        and jsonb_typeof(content -> 'rules') = 'array'
    )
);

create trigger audit_row after insert or update or delete on public.field_policy
    for each row execute function audit.log_row('format');
create trigger audit_no_truncate before truncate on public.field_policy
    for each statement execute function audit.refuse_truncate();

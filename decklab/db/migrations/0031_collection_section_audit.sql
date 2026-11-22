-- The latest physical count for each section belongs to its inventory space.
-- Counts and discrepancies are evidence, separate from the collection's quantities.
create table public.collection_section_audit (
    space_id text not null references public.space (id),
    section_id text not null check (length(section_id) between 1 and 200),
    revision bigint not null check (revision between 1 and 9007199254740991),
    audited_at timestamptz not null,
    digest text not null check (digest ~ '^[0-9a-f]{64}$'),
    expected bigint not null check (expected between 0 and 9007199254740991),
    observed bigint not null check (observed between 0 and 9007199254740991),
    missing bigint not null check (missing between 0 and expected),
    surplus bigint not null check (surplus between 0 and observed),
    extra bigint not null check (extra between 0 and observed),
    mismatch_rows integer not null check (mismatch_rows >= 0),
    differences jsonb not null check (
        jsonb_typeof(differences) = 'array' and jsonb_array_length(differences) = mismatch_rows
    ),
    check (observed = expected - missing + surplus + extra),
    primary key (space_id, section_id)
);

create trigger audit_row after insert or update or delete on public.collection_section_audit
    for each row execute function audit.log_row('space_id', 'section_id');
create trigger audit_no_truncate before truncate on public.collection_section_audit
    for each statement execute function audit.refuse_truncate();

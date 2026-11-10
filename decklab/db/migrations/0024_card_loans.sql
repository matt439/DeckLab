-- Exact-printing loose-card loans (E7-S37). Ownership stays in the collection;
-- open rows reserve copies until returned. Borrower/notes are private space data.
-- Default privileges from 0001 grant app DML and read-only SELECT as for inventory.
create table public.card_loan (
    space_id text not null check (space_id ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    id text not null check (id ~ '^[0-9a-f]{32}$'),
    name text not null check (char_length(name) between 1 and 200 and name !~ '[[:cntrl:]]'),
    set_code text not null check (set_code ~ '^[a-z0-9]{2,8}$'),
    collector_number text not null check (char_length(collector_number) between 1 and 40
                                         and collector_number !~ '[[:space:][:cntrl:]]'),
    finish text not null check (finish in ('nonfoil', 'foil', 'etched')),
    quantity int not null check (quantity between 1 and 9999),
    borrower text not null check (char_length(borrower) between 1 and 80 and borrower !~ '[[:cntrl:]]'),
    lent_on date not null,
    returned_on date,
    notes text not null default '' check (char_length(notes) <= 500 and notes !~ '[[:cntrl:]]'),
    primary key (space_id, id),
    check (returned_on is null or returned_on >= lent_on)
);
create index card_loan_open on public.card_loan (space_id, set_code, collector_number, finish)
    where returned_on is null;
create trigger audit_row after insert or update or delete on public.card_loan
    for each row execute function audit.log_row('space_id', 'id');
create trigger audit_no_truncate before truncate on public.card_loan
    for each statement execute function audit.refuse_truncate();

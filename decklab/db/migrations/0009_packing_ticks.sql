-- Shared home packing progress. A key describes one unchanged physical task, hashed in
-- api/assembly_ticks.py before storage so private sleeves and box labels never enter the
-- shared state or audit trail. Only checked tasks have rows; patches never replace a plan.
create table packing_tick (
    id text primary key check (id ~ '^[a-f0-9]{64}$')
);

create trigger audit_row after insert or update or delete on packing_tick
    for each row execute function audit.log_row('id');
create trigger audit_no_truncate before truncate on packing_tick
    for each statement execute function audit.refuse_truncate();

-- The text remains authoritative. migrate.py's canonical-parser hook validates the
-- existing derived identities and backfills only this new projection, atomically.
-- Nullable/defaulted for older application versions that still insert nine fields.
alter table public.deck_line add column category text default null
    check (category is null or (char_length(category) between 1 and 30));

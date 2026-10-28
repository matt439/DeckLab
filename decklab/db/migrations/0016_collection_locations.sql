-- Where a collection row's storage copies are (E8-S22): one short line such as "Row 2, B" or
-- "Binder", blank when not recorded. It goes with its row, so a row removed takes its location.
-- No data is written: every existing row starts with no location.
alter table collection_card add column location text not null default ''
    check (location = btrim(location) and char_length(location) <= 40 and location !~ '[[:cntrl:]]');

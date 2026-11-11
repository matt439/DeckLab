-- Optional AUD unit-price market targets (E5-S35), never an amount paid or spending.
-- Existing queue rows stay unset; ordinary table privileges/audit cover this column.
alter table public.watchlist_item add column buy_under_aud numeric(11,2) default null
    check (buy_under_aud is null or (buy_under_aud >= 0 and buy_under_aud < 1000000000));

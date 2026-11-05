-- The household's price settings (E11-S53): the currency price estimates are in and the
-- price-check shops, chosen by a home admin on Settings' Prices panel, one record saved whole with
-- a revision, as the shops' postage is. A null field means config.json's applies (and then the
-- default). As for shop_postage, 0001's default privileges give decklab_app ordinary
-- SELECT/INSERT/UPDATE/DELETE and decklab_ro SELECT.
create table public.pricing_setting (
    id boolean primary key default true check (id),
    revision bigint not null check (revision >= 1),
    content jsonb not null check (
        jsonb_typeof(content) = 'object'
        and content ?& array['v', 'currency', 'shops']
        and content - array['v', 'currency', 'shops'] = '{}'::jsonb
        and content ->> 'v' = '1'
        and (jsonb_typeof(content -> 'currency') = 'null'
             or (jsonb_typeof(content -> 'currency') = 'string' and content ->> 'currency' ~ '^[A-Z]{3}$'))
        and jsonb_typeof(content -> 'shops') in ('null', 'array')
    )
);

create trigger audit_row after insert or update or delete on public.pricing_setting
    for each row execute function audit.log_row('id');
create trigger audit_no_truncate before truncate on public.pricing_setting
    for each statement execute function audit.refuse_truncate();

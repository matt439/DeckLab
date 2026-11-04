-- Each price-check shop's postage rules (E5-S27): a flat postage and a free-postage threshold,
-- typed by a home admin in Settings, one household record saved whole with a revision, as the
-- Commander-night notes are. Never a price paid. As for commander_night, 0001's default
-- privileges give decklab_app ordinary SELECT/INSERT/UPDATE/DELETE and decklab_ro SELECT.
create table public.shop_postage (
    id boolean primary key default true check (id),
    revision bigint not null check (revision >= 1),
    content jsonb not null check (
        jsonb_typeof(content) = 'object'
        and content ?& array['v', 'shops']
        and content - array['v', 'shops'] = '{}'::jsonb
        and content ->> 'v' = '1'
        and jsonb_typeof(content -> 'shops') = 'object'
    )
);

create trigger audit_row after insert or update or delete on public.shop_postage
    for each row execute function audit.log_row('id');
create trigger audit_no_truncate before truncate on public.shop_postage
    for each statement execute function audit.refuse_truncate();

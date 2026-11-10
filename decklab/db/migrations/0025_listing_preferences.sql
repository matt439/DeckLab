-- Household listing preferences (E5-S34). Existing v1 price settings stay
-- unchanged. Only a chosen preference needs v2; null still accepts every listing.
alter table public.pricing_setting drop constraint pricing_setting_content_check;
alter table public.pricing_setting add constraint pricing_listing_preferences_check check (
    jsonb_typeof(content) = 'object'
    and content ?& array['v', 'currency', 'shops']
    and (jsonb_typeof(content -> 'currency') = 'null'
         or (jsonb_typeof(content -> 'currency') = 'string' and content ->> 'currency' ~ '^[A-Z]{3}$'))
    and jsonb_typeof(content -> 'shops') in ('null', 'array')
    and (
        (content ->> 'v' = '1' and content - array['v', 'currency', 'shops'] = '{}'::jsonb)
        or (content ->> 'v' = '2' and content ? 'listing_preferences'
            and content - array['v', 'currency', 'shops', 'listing_preferences'] = '{}'::jsonb
            and (jsonb_typeof(content -> 'listing_preferences') = 'null'
                 or (jsonb_typeof(content -> 'listing_preferences') = 'object'
                     and (content -> 'listing_preferences') ?& array['minimum_condition', 'english_only']
                     and (content -> 'listing_preferences') - array['minimum_condition', 'english_only'] = '{}'::jsonb
                     and (jsonb_typeof(content -> 'listing_preferences' -> 'minimum_condition') = 'null'
                          or content -> 'listing_preferences' ->> 'minimum_condition' in ('NM', 'LP', 'MP', 'HP', 'DMG'))
                     and jsonb_typeof(content -> 'listing_preferences' -> 'english_only') = 'boolean')))
    )
);

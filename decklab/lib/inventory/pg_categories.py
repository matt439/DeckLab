"""Optional derived deck-line categories before and after migration0027."""


def ready(connection):
    return connection.execute("select exists(select 1 from pg_catalog.pg_attribute "
                              "where attrelid=to_regclass('public.deck_line') and attname='category' "
                              "and not attisdropped)").fetchone()[0]

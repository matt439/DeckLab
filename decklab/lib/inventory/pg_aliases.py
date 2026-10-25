"""Rename metadata inside the inventory transaction; no connections or live writes on import."""


def ready(c):
    return bool(c.execute("select to_regclass('public.deck_alias') is not null").fetchone()[0])


def select(c):
    """Snapshot metadata. Historical IDs prevent a rename from merging unrelated histories."""
    available = ready(c)
    aliases = dict(c.execute("select alias_id, deck_id from deck_alias").fetchall()) if available else {}
    history = tuple(row[0] for row in c.execute("select distinct deck_id from deck_revision order by deck_id"))
    return {"deck_aliases": aliases, "aliases_ready": available, "deck_history_ids": history}


def lineage(c, deck_id):
    if not ready(c):
        return [deck_id]
    return [r[0] for r in c.execute("with canonical as (select coalesce((select deck_id from deck_alias "
                                    "where alias_id = %s), %s) as deck_id) select deck_id from canonical "
                                    "union all select a.alias_id from deck_alias a join canonical c "
                                    "on a.deck_id = c.deck_id", (deck_id, deck_id))]


def write(cur, old, new):
    """An alias map's audited difference, as one part of the caller's rename transaction."""
    dropped = [(key,) for key in old.keys() - new.keys()]
    if dropped:
        cur.executemany("delete from deck_alias where alias_id = %s", dropped)
    changed = [(key, value) for key, value in new.items() if old.get(key) != value]
    if changed:
        cur.executemany("insert into deck_alias (alias_id, deck_id) values (%s, %s) "
                        "on conflict (alias_id) do update set deck_id = excluded.deck_id", changed)


def rename(cur, before, after, move, change_set_id, actor, message):
    """Move one deck's current row and append one M; retain every old revision unchanged."""
    from . import pg_decks
    from .ops_rename import title_text
    source, target = move["from"], move["to"]
    old, new = before.deck(source), after.deck(target)
    if old is None or new is None:
        raise ValueError("A rename must keep one current deck")
    parsed = pg_decks.parsed(target, new.text)
    if parsed is None or new.text != title_text(old.text, parsed.title):
        raise ValueError("A rename may change only the title heading")
    if (old.space, old.kind) != (new.space, new.kind):
        raise ValueError("A rename keeps the deck's space and kind")
    pg_decks._check_lf(target, new.text)
    members = lineage(cur.connection, source)
    cur.execute("select coalesce(max(revision), 0) + 1 from deck_revision where deck_id = any(%s)", (members,))
    number = cur.fetchone()[0]
    cur.execute("update deck set id = %s, slug = %s, title = %s, revision = %s, rename_version = rename_version + 1, "
                "updated_at = now() where id = %s",
                (target, new.slug, parsed.title, number, source))
    cur.execute("update deck_text set text = %s where deck_id = %s", (new.text, target))
    write(cur, dict(before.deck_aliases), dict(after.deck_aliases))
    pg_decks._add_revisions(cur, [(target, number, change_set_id, actor, message, "M", new.text, False)])
    return 1

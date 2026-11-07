"""Invented supporting inventory and Activity rows for page-family review."""
import csv
import io


def seed(fixture):
    from decklab.lib import accessories, purchases, tokens

    def write(name, fields, rows):
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        (fixture.root / "magic" / name).write_text(stream.getvalue(), encoding="utf-8")

    write("tokens.csv", tokens.FIELDS, [
        dict(front="Rabbit", back="Rabbit", quantity="2", notes="Synthetic double-sided token"),
        dict(front="Dog", back="Beast", quantity="1", back_details="3/3", notes="Synthetic token awaiting details"),
    ])
    write("accessories.csv", accessories.FIELDS, [
        dict(id="review-sleeves", kind="sleeves", owner="shared", brand="Example", name="Matte",
             colour="green", quantity="120", notes="Synthetic shared sleeves"),
        dict(id="review-box", kind="deck_box", owner="matt", brand="Example", name="Deck box",
             colour="black", quantity="1", capacity="100", notes="Synthetic deck box"),
        dict(id="review-mat", kind="playmat", owner="shared", brand="Example", name="Plain",
             colour="blue", quantity="1", notes="Synthetic shared playmat"),
    ])
    write("watchlist.csv", purchases.QUEUE_FIELDS, [
        dict(name=name, quantity="2", printing="any", finish="nonfoil", state=state,
             notes="Synthetic purchase intent; no paid price or live shop data")
        for name, state in (("Llanowar Visionary", "ready"), ("Harmonize", "waiting_for_stock"),
                            ("Overrun", "waiting_for_reprint"), ("Reclamation Sage", "deferred"))])


def activity():
    """Renderer adapter only: FileInventory has no database audit trail."""
    rows = []
    for n, (kind, table, words) in enumerate([
        ("settings", "profile_setting", "changed the display theme"),
        ("decks", "deck", "saved the woodland deck"),
        ("collection", "collection_card", "added a synthetic card import"),
        ("tokens", "token_card", "recorded token details"),
    ], 1):
        rows.append(dict(id=n, at=f"2000-01-05T0{n}:00:00+00:00", actor="matt", actor_name="Matt",
                         source="web", via="home", message="", reason=None,
                         headline=f"Matt {words}", kinds=[kind], link=None,
                         rows=[dict(table=table, op="UPDATE", summary=f"Synthetic {kind} change",
                                    before={}, after={})]))
    return dict(changes=rows, next=None, everything=False, cards={})


def settings(path):
    """Read adapters for database-only admin panels; no configured services."""
    if path == "/api/visits":
        return dict(days=30, people=[dict(profile="matt", name="Matt", seen=False)])
    if path == "/api/settings/members":
        return dict(editable=True, config_sha256="a" * 64, membership_sha256="b" * 64,
                    members=[dict(id="user2", name="User2", emails=["user2@example.com"])])
    stamp = "2000-01-05T01:00:00+00:00"
    run = dict(started_at=stamp, finished_at=stamp, outcome="success")
    return dict(available=True, checked_at=stamp, recent_limit=5, jobs=[
        dict(kind=kind, latest=run, last_success=run, recent=[run], health="success", freshness="current",
             interval=dict(value=7 if kind == "restore_check" else 48,
                           unit="days" if kind == "restore_check" else "hours",
                           source="restore_check_days" if kind == "restore_check" else "stale_backup_hours",
                           basis="finished_at" if kind in {"dump", "export"} else "started_at"))
        for kind in ("dump", "export", "check", "restore_check")])
